#!/usr/bin/env python3
"""ui.py — the local Jobissimo UI: a small stdlib web server on 127.0.0.1.

    python3 scripts/ui.py              # prints a one-time URL and opens it
    python3 scripts/ui.py --no-open --port 8765
    python3 scripts/launcher.py open   # the same, without a terminal (what the app runs)

It serves the static app in `ui/` and a JSON API over the read model
(scripts/readmodel.py). It never writes the workspace itself: every change is
a subprocess call to the same deterministic CLIs an agent uses — db.py,
knowledge.py, config.py — so validation, transition rules and event logging
are identical whoever makes the change. There is deliberately no control to
submit an application, bypass an audit, or force a lifecycle transition.

It can also *start* a command in the user's own Claude Code or Codex
(scripts/agent_runner.py) — a fixed list of commands with validated
arguments, `/apply` never — stream the agent's steps to the page, and carry
the conversation: the agent's questions and permission requests are answered
by the user in the run panel, and a finished run takes a reply. Runs that
touch different things go side by side. The Settings page checks and sets up
what runs need (scripts/agent_setup.py).

Security, for a server that can read a career:
- binds 127.0.0.1 only; requests whose Host header is not this server are
  refused (DNS-rebinding guard);
- a random token is minted per launch; the printed URL swaps it for an
  HttpOnly, SameSite=Strict cookie, and every /api call requires it;
- every POST also needs a CSRF token from /api/session and a same-origin
  Origin header; there is no CORS;
- static files are served only from ui/, with an extension allowlist.
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_runner  # noqa: E402
import agent_setup  # noqa: E402
import launcher  # noqa: E402
import paths  # noqa: E402
import readmodel  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
UI_DIR = paths.REPO_ROOT / "ui"
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
COOKIE = "jobissimo_session"
MAX_BODY = 64 * 1024
MAX_UPLOAD = 25 * 1024 * 1024
# status moves the UI may request — never discarded->*, never --force
UI_STATUSES = {"applied", "responded", "closed", "on_hold", "skipped", "missed", "shortlisted"}
JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def run_cli(script: str, *args: str) -> str:
    """Run one of the deterministic CLIs. Its refusal becomes a 400 carrying
    the script's own message — the UI never second-guesses the rules."""
    res = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip().splitlines()
        msg = [m for m in msg if not m.startswith("# WARNING")] or msg
        raise ApiError(400, re.sub(r"^ERROR:\s*", "", " ".join(msg[-3:])) or f"{script} failed")
    return res.stdout


def _s(body: dict, key: str, required: bool = True, maxlen: int = 2000) -> str | None:
    v = body.get(key)
    if v is None or v == "":
        if required:
            raise ApiError(400, f"`{key}` is required.")
        return None
    if not isinstance(v, (str, int, float)):
        raise ApiError(400, f"`{key}` must be text.")
    v = str(v).strip()
    if len(v) > maxlen:
        raise ApiError(400, f"`{key}` is too long.")
    return v


def _date(body: dict, key: str, required: bool = False) -> str | None:
    v = _s(body, key, required, 10)
    if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise ApiError(400, f"`{key}` must be YYYY-MM-DD.")
    return v


# ---------------------------------------------------------------- actions

def act_status(job_id: str, body: dict) -> dict:
    status = _s(body, "status")
    if status not in UI_STATUSES:
        raise ApiError(400, f"Status `{status}` cannot be set from the UI.")
    args = ["set-status", "--job-id", job_id, "--status", status, "--run-id", "ui"]
    if (d := _date(body, "date")):
        args += ["--date", d]
    if (o := _s(body, "outcome", False, 40)):
        args += ["--outcome", o]
    if (v := _s(body, "applied_via", False, 40)):
        args += ["--applied-via", v]
    return {"message": run_cli("db.py", *args).strip()}


def act_stage(job_id: str, body: dict) -> dict:
    args = ["stage", "add", "--job-id", job_id, "--kind", _s(body, "kind", maxlen=10),
            "--date", _date(body, "date", True), "--run-id", "ui"]
    for key, flag in (("label", "--label"), ("result", "--result"), ("note", "--note")):
        if (v := _s(body, key, False, 300)):
            args += [flag, v]
    return {"message": run_cli("db.py", *args).strip()}


def act_stage_resolve(job_id: str, body: dict) -> dict:
    args = ["stage", "resolve", "--job-id", job_id, "--result", _s(body, "result", maxlen=12),
            "--run-id", "ui"]
    if body.get("seq") is not None:
        args += ["--seq", str(int(body["seq"]))]
    if (d := _date(body, "date")):
        args += ["--date", d]
    return {"message": run_cli("db.py", *args).strip()}


def act_propose(body: dict) -> dict:
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise ApiError(400, "`payload` must be an object.")
    args = ["propose", "--op", _s(body, "op", maxlen=20), "--by", "user",
            "--payload", json.dumps(payload)]
    if (t := _s(body, "target", False, 64)):
        args += ["--target", t]
    if (n := _s(body, "note", False, 500)):
        args += ["--note", n]
    out = run_cli("knowledge.py", *args).strip()
    item_id = out.split()[1].rstrip(":") if out.startswith("Proposed ") else None
    result = {"message": out, "id": item_id}
    # a change the user makes themselves is accepted in the same step; the
    # inbox keeps the record either way
    if body.get("accept") and item_id:
        result["message"] = run_cli("knowledge.py", "decide", item_id, "accept").strip()
    return result


def act_inbox(item_id: str, body: dict) -> dict:
    decision = _s(body, "decision", maxlen=10)
    if decision not in ("accept", "reject"):
        raise ApiError(400, "decision must be accept or reject.")
    args = ["decide", item_id, decision]
    if (r := _s(body, "reason", False, 500)):
        args += ["--reason", r]
    if isinstance(body.get("payload"), dict):
        args += ["--payload", json.dumps(body["payload"])]
    return {"message": run_cli("knowledge.py", *args).strip()}


def act_config(body: dict) -> dict:
    if "value" not in body:
        raise ApiError(400, "`value` is required.")
    args = ["set", _s(body, "file", maxlen=20), _s(body, "key", maxlen=80),
            "--json-value", json.dumps(body["value"]), "--reason", _s(body, "reason", maxlen=500),
            "--run-id", "ui"]
    if (sid := _s(body, "suggestion", False, 40)):
        args += ["--suggestion", sid]
    return {"message": run_cli("config.py", *args).strip()}


def act_suggestion(sid: str, body: dict) -> dict:
    status = _s(body, "status", maxlen=12)
    args = ["suggestion", "decide", sid, "--status", status, "--run-id", "ui"]
    if (r := _s(body, "reason", False, 500)):
        args += ["--reason", r]
    msg = run_cli("db.py", *args).strip()
    if status == "approved" and body.get("apply"):
        msg += "\n" + run_cli("config.py", "apply-suggestion", sid).strip()
    return {"message": msg}


def _runs(fn, *args):
    try:
        return {"run": fn(*args).meta()}
    except agent_runner.RunError as exc:
        raise ApiError(exc.status, str(exc))


def start_run(app, body: dict) -> dict:
    """Start one command in the user's own agent CLI. Runs whose work
    overlaps (the same job, the browser, the cycle) never run together."""
    return _runs(app.manager.start, _s(body, "agent", maxlen=10), _s(body, "command", maxlen=20),
                 _s(body, "arg", False, 600))


def settings_view(app, refresh: bool) -> dict:
    """agent_setup.py check, cached: the Claude probe takes a few seconds."""
    with app.settings_lock:
        if refresh or app.settings_cache is None or time.time() - app.settings_cache[0] > 120:
            app.settings_cache = (time.time(), agent_setup.check())
        return app.settings_cache[1]


def act_settings(app, what: str, body: dict) -> dict:
    if what == "permission":
        out = run_cli("agent_setup.py", "permission", _s(body, "capability", maxlen=20), _s(body, "mode", maxlen=20))
    elif what == "pref":
        value = body.get("value")
        value = "" if value is None else (json.dumps(value) if isinstance(value, bool) else str(value))
        out = run_cli("agent_setup.py", "pref", _s(body, "key", maxlen=40), value)
    elif what == "codex-trust":
        out = run_cli("agent_setup.py", "codex-trust")
    elif what == "install":
        return _runs(app.manager.start_task, _s(body, "tool", maxlen=20))
    else:
        raise ApiError(404, "Not found.")
    app.settings_cache = None
    return {"message": out.strip()}


def act_launcher(app, what: str, body: dict) -> dict:
    if what == "app":
        action = _s(body, "action", maxlen=12)
        if action not in ("install", "uninstall"):
            raise ApiError(400, "action must be install or uninstall.")
        out = run_cli("launcher.py", f"{action}-app")
    else:
        out = run_cli("launcher.py", "login", "on" if body.get("on") else "off")
    return {"message": out.strip(), "launcher": launcher.status()}


def act_upload(name: str, data: bytes) -> dict:
    """A document for /setup, written by intake.py like every other source."""
    if not name or len(name) > 200:
        raise ApiError(400, "The file needs a name.")
    res = subprocess.run([sys.executable, str(SCRIPTS / "intake.py"), "--upload", name], input=data,
                         capture_output=True, timeout=120)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).decode("utf-8", "replace").strip().splitlines()
        raise ApiError(400, re.sub(r"^ERROR:\s*", "", msg[-1] if msg else "intake.py failed"))
    return {"message": res.stdout.decode("utf-8", "replace").strip().splitlines()[-1],
            "documents": readmodel.onboarding_view()["documents"]}


# ---------------------------------------------------------------- server

class App:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.token = secrets.token_urlsafe(24)
        self.csrf = secrets.token_urlsafe(24)
        self.lock = threading.Lock()  # one write at a time
        self.manager = agent_runner.Manager()  # agent runs of this session
        self.settings_lock = threading.Lock()
        self.settings_cache = None
        self.last_seen = time.time()  # any signed-in request; the page pings while open
        self.server = None

    def shutdown(self) -> None:
        """Stop serving; serve() then stops the runs and clears the state file."""
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def allowed_hosts(self) -> set:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "jobissimo-ui"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet; no request log of a career
            pass

        # ---- helpers
        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                             "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'self'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, readmodel.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in app.allowed_hosts()

        def _authed(self) -> bool:
            c = SimpleCookie(self.headers.get("Cookie", ""))
            got = c[COOKIE].value if COOKIE in c else ""
            return hmac.compare_digest(got, app.token)

        # ---- GET
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden host", "text/plain")
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/" and "t" in q:
                if not hmac.compare_digest(q["t"][0], app.token):
                    return self._send(403, b"This link has expired. Open Jobissimo from the app (or restart "
                                      b"scripts/ui.py) for a fresh one.", "text/plain")
                cookie = f"{COOKIE}={app.token}; HttpOnly; SameSite=Strict; Path=/"
                return self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
            if url.path == "/api/health":  # for launcher.py: is this a Jobissimo UI? nothing more
                return self._json(200, {"app": "jobissimo"})
            if url.path.startswith("/api/"):
                if not self._authed():
                    return self._json(401, {"error": "Open Jobissimo from the app, or the link printed by scripts/ui.py."})
                app.last_seen = time.time()
                try:
                    return self._json(200, self.api_get(url.path, q))
                except ApiError as e:
                    return self._json(e.status, {"error": e.message})
                except Exception as e:  # never leak a traceback to the page
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            return self.static(url.path)

        do_HEAD = do_GET

        def api_get(self, path: str, q: dict):
            one = lambda k: (q.get(k) or [None])[0]  # noqa: E731
            if path == "/api/session":
                ws = paths.home()
                return {"csrf": app.csrf, "workspace": ws.name,
                        "onboarding_complete": readmodel.onboarding_view()["complete"]}
            if path == "/api/ping":
                return {"ok": True, "busy": len(app.manager.busy())}
            if path == "/api/onboarding":
                out = readmodel.onboarding_view()
                out["launcher"] = launcher.status()
                return out
            if path == "/api/overview":
                return readmodel.overview()
            if path == "/api/jobs":
                return readmodel.jobs_view(status=q.get("status"), source=one("source"),
                                           since=one("since"), q=one("q"))
            m = re.fullmatch(r"/api/jobs/([^/]+)", path)
            if m:
                if not JOB_ID_RE.fullmatch(m.group(1)):
                    raise ApiError(400, "bad job id")
                out = readmodel.job_view(m.group(1))
                if out is None:
                    raise ApiError(404, "Unknown job.")
                return out
            if path == "/api/analytics":
                since = one("since")
                if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
                    raise ApiError(400, "since must be YYYY-MM-DD")
                ctx = readmodel.Ctx()
                a = readmodel.analytics(ctx, since)
                a["insights"] = readmodel.insights_mod.diagnose(a, readmodel.overview(ctx))
                return a
            if path == "/api/knowledge":
                return readmodel.knowledge_view()
            if path == "/api/gaps":
                return readmodel.gaps_view()
            if path == "/api/pipeline":
                return readmodel.pipeline_view()
            if path == "/api/insights":
                return readmodel.insights_view()
            if path == "/api/agents":
                runs = sorted(app.manager.runs.values(), key=lambda r: r.t0, reverse=True)
                return {"agents": agent_runner.detect(), "commands": agent_runner.COMMANDS,
                        "not_from_ui": agent_runner.NOT_FROM_UI,
                        "max_parallel": agent_setup.load_prefs()["runs.max_parallel"],
                        "runs": [r.meta() for r in runs if r.busy] + [r.meta() for r in runs if not r.busy][:12]}
            if path == "/api/settings":
                out = dict(settings_view(app, one("refresh") == "1"))
                out["launcher"] = launcher.status()
                return out
            m = re.fullmatch(rf"/api/runs/({agent_runner.RUN_ID_RE})", path)
            if m:
                try:
                    run = app.manager.get(m.group(1))
                except agent_runner.RunError as exc:
                    raise ApiError(exc.status, str(exc))
                try:
                    after = max(0, int(one("after") or 0))
                except ValueError:
                    raise ApiError(400, "after must be a number")
                return {"run": run.meta(), "events": run.since(after)}
            raise ApiError(404, "Not found.")

        def static(self, path: str):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (UI_DIR / rel).resolve()
            if UI_DIR.resolve() not in target.parents or target.suffix not in STATIC_TYPES \
                    or not target.is_file():
                # client-side routes fall back to the shell
                if "." not in rel.rsplit("/", 1)[-1]:
                    target = UI_DIR / "index.html"
                else:
                    return self._send(404, b"Not found", "text/plain")
            self._send(200, target.read_bytes(), STATIC_TYPES[target.suffix])

        # ---- POST
        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden host", "text/plain")
            if urlparse(self.path).path == "/api/quit-local":
                # launcher.py stop: the token from the owner-only state file, no browser involved
                if not hmac.compare_digest(self.headers.get("X-Jobissimo-Token", ""), app.token):
                    return self._json(403, {"error": "Bad token."})
                app.manager.stop_all()
                app.shutdown()
                return self._json(200, {"message": "Stopping."})
            if not self._authed():
                return self._json(401, {"error": "Not signed in."})
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc not in app.allowed_hosts():
                return self._json(403, {"error": "Cross-origin request refused."})
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), app.csrf):
                return self._json(403, {"error": "Missing or invalid CSRF token."})
            app.last_seen = time.time()
            try:
                n = int(self.headers.get("Content-Length") or 0)
                url = urlparse(self.path)
                if url.path == "/api/intake":
                    if n > MAX_UPLOAD:
                        raise ApiError(413, "That file is over 25 MB.")
                    name = (parse_qs(url.query).get("name") or [""])[0]
                    data = self.rfile.read(n) if n else b""
                    with app.lock:
                        return self._json(200, act_upload(name, data))
                if n > MAX_BODY:
                    raise ApiError(413, "Request too large.")
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    raise ApiError(400, "Body must be a JSON object.")
                with app.lock:
                    return self._json(200, self.api_post(urlparse(self.path).path, body))
            except ApiError as e:
                return self._json(e.status, {"error": e.message})
            except json.JSONDecodeError:
                return self._json(400, {"error": "Body must be JSON."})
            except subprocess.TimeoutExpired:
                return self._json(504, {"error": "The command timed out."})

        def api_post(self, path: str, body: dict):
            m = re.fullmatch(r"/api/jobs/([^/]+)/(status|stage|stage/resolve)", path)
            if m:
                if not JOB_ID_RE.fullmatch(m.group(1)):
                    raise ApiError(400, "bad job id")
                fn = {"status": act_status, "stage": act_stage,
                      "stage/resolve": act_stage_resolve}[m.group(2)]
                return fn(m.group(1), body)
            m = re.fullmatch(r"/api/inbox/(INB-[0-9]+-[0-9]+)/decision", path)
            if m:
                return act_inbox(m.group(1), body)
            if path == "/api/knowledge/propose":
                return act_propose(body)
            if path == "/api/config":
                return act_config(body)
            m = re.fullmatch(r"/api/suggestions/((?:OPT|PS)-[0-9A-Za-z-]+)/decision", path)
            if m:
                return act_suggestion(m.group(1), body)
            if path == "/api/runs":
                return start_run(app, body)
            m = re.fullmatch(rf"/api/runs/({agent_runner.RUN_ID_RE})/(stop|reply)", path)
            if m:
                if m.group(2) == "stop":
                    return _runs(app.manager.stop, m.group(1))
                return _runs(app.manager.reply, m.group(1), _s(body, "text", maxlen=4000))
            m = re.fullmatch(rf"/api/runs/({agent_runner.RUN_ID_RE})/asks/(a\d{{1,4}})", path)
            if m:
                return _runs(app.manager.answer, m.group(1), m.group(2), body)
            m = re.fullmatch(r"/api/settings/(permission|pref|codex-trust|install)", path)
            if m:
                return act_settings(app, m.group(1), body)
            m = re.fullmatch(r"/api/launcher/(app|login)", path)
            if m:
                return act_launcher(app, m.group(1), body)
            if path == "/api/quit":
                busy = app.manager.busy()
                if busy and not body.get("force"):
                    raise ApiError(409, f"{', '.join(r.label for r in busy)} "
                                        f"{'is' if len(busy) == 1 else 'are'} still running.")
                app.manager.stop_all()
                app.shutdown()
                return {"message": "Jobissimo is stopping."}
            raise ApiError(404, "Not found.")

    return Handler


def watch_idle(app: App, minutes: float) -> None:
    """Stop when no page has been open and no run has gone for `minutes`
    (an open page pings every minute). For UIs the app started."""
    while True:
        time.sleep(min(15.0, max(1.0, minutes * 60 / 4)))
        if app.manager.busy():
            app.last_seen = time.time()
        elif time.time() - app.last_seen > minutes * 60:
            print(f"No open page or run for {minutes:g} minutes — stopping.", flush=True)
            app.shutdown()
            return


def serve(host: str, port: int, open_browser: bool = True, idle_exit: float = 0) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise SystemExit("ui.py binds to localhost only.")
    server = ThreadingHTTPServer((host, port), None)
    app = App(host, server.server_address[1])
    app.server = server
    server.RequestHandlerClass = make_handler(app)
    url = f"http://127.0.0.1:{app.port}/?t={app.token}"
    launcher.write_state(app.port, app.token)  # so the app can find and reuse this server
    print(f"Jobissimo UI for workspace {paths.home()}\n\n  {url}\n\n"
          "This link signs you in for this session only. Ctrl+C (or Quit in the page) stops the server.",
          flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    if idle_exit > 0:
        threading.Thread(target=watch_idle, args=(app, idle_exit), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        busy = app.manager.busy()
        if busy:
            print(f"Stopping {', '.join(r.label for r in busy)}…", flush=True)
            app.manager.stop_all()
            deadline = time.time() + 6
            while app.manager.busy() and time.time() < deadline:
                time.sleep(0.2)
        launcher.clear_state()
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765, help="0 picks a free port.")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost only.")
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser.")
    parser.add_argument("--idle-exit", type=float, default=0, metavar="MIN",
                        help="Stop after MIN minutes with no open page and no run (0 = never; "
                             "the app uses 30).")
    parser.add_argument("--new", action="store_true",
                        help="Start a new server even if one already serves this workspace.")
    args = parser.parse_args()
    mimetypes.init()
    st = None if args.new else launcher.running()
    if st:  # the app (or another terminal) already serves this workspace: reuse it
        url = launcher.url_for(st)
        print(f"Jobissimo is already running for workspace {paths.home()}\n\n  {url}\n\n"
              "Quit it from the page, or: python3 scripts/launcher.py stop", flush=True)
        if not args.no_open:
            webbrowser.open(url)
        return 0
    serve(args.host, args.port, not args.no_open, args.idle_exit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
