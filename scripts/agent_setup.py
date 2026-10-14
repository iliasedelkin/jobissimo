#!/usr/bin/env python3
"""agent_setup.py — check and set up what agent runs started from the local
UI need: the agent CLIs and their sign-in, the permissions a run may use
without asking, the browser and mail connectors, and the local tools the
pipeline shells out to.

    python3 scripts/agent_setup.py check [--quick]      # JSON report
    python3 scripts/agent_setup.py permission web_pages job_sites
    python3 scripts/agent_setup.py pref claude.effort medium
    python3 scripts/agent_setup.py codex-trust          # trust this repo in Codex
    python3 scripts/agent_setup.py install pandoc       # brew install, streamed

Where things live:
- Claude Code permission rules: `<repo>/.claude/settings.local.json` — Claude
  Code's own per-machine file (git-ignored). A rule added here applies to
  chat sessions too, exactly as if you had clicked "always allow" there.
- Codex trust: `$CODEX_HOME/config.toml` (default ~/.codex), `[projects."<repo>"]`.
- Run preferences (model, effort, web access for Codex, parallel runs):
  `<workspace>/config/local/agents.json` — machine-specific, never synced.

This script is deliberately on neither agent allowlist: an agent never
changes its own permissions. The UI calls it only on the user's click.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent

# ---------------------------------------------------------------- permissions

# Hosts job postings live on: boards plus the hosted ATSs employers use.
# Wildcards match any subdomain (company.teamtailor.com).
JOB_SITE_DOMAINS = [
    "linkedin.com", "*.linkedin.com",
    "*.ashbyhq.com", "*.lever.co", "*.greenhouse.io", "*.workable.com", "*.teamtailor.com",
    "*.myworkdayjobs.com", "*.smartrecruiters.com", "*.recruitee.com", "*.personio.de",
    "*.personio.com", "*.bamboohr.com", "*.breezy.hr", "*.jobvite.com", "*.icims.com",
    "*.successfactors.com", "*.successfactors.eu", "*.join.com", "*.homerun.co", "*.pinpointhq.com",
    "*.rippling.com", "*.gem.com", "*.dover.com", "*.workatastartup.com", "*.welcometothejungle.com",
    "*.revolutpeople.com", "*.indeed.com", "*.glassdoor.com", "*.wellfound.com",
]
GMAIL_READ_TOOLS = ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_thread",
                    "mcp__claude_ai_Gmail__get_message", "mcp__claude_ai_Gmail__list_labels"]

# capability -> label, help, {mode: rules}. "ask" (no rule) is always a mode:
# the run then asks you in the run panel each time.
CAPABILITIES = {
    "web_pages": {
        "label": "Read web pages",
        "help": "WebFetch — how /hunt and /refresh read a posting when the browser is not used.",
        "modes": {"ask": [], "job_sites": None, "any": ["WebFetch"]},
        "mode_labels": {"ask": "Ask each time", "job_sites": "Job sites without asking",
                        "any": "Any site without asking"},
    },
    "web_search": {
        "label": "Search the web",
        "help": "WebSearch — finding an employer's own posting for a board listing.",
        "modes": {"ask": [], "allow": ["WebSearch"]},
        "mode_labels": {"ask": "Ask each time", "allow": "Allow"},
    },
    "browser": {
        "label": "Use your Chrome",
        "help": "Claude in Chrome — the browse adapter for logged-in boards. Without it a run asks "
                "before every browser step.",
        "modes": {"ask": [], "allow": ["mcp__claude-in-chrome"]},
        "mode_labels": {"ask": "Ask each step", "allow": "Allow browser steps"},
    },
    "mail": {
        "label": "Read Gmail",
        "help": "Read-only Gmail tools — job alerts and replies for /hunt and /track. Sending is never "
                "allowed.",
        "modes": {"ask": [], "read": GMAIL_READ_TOOLS},
        "mode_labels": {"ask": "Ask each time", "read": "Read without asking"},
    },
}


def _board_domains() -> list:
    """Hosts named in boards.yaml (pack + config), as WebFetch domains."""
    hosts = set()
    for path in (paths.config_dir() / "boards.yaml",):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        hosts.update(h.lower() for h in re.findall(r"https?://([A-Za-z0-9.-]+)", text))
    return sorted(hosts)


def job_site_rules() -> list:
    domains = list(JOB_SITE_DOMAINS)
    for host in _board_domains():
        base = host[4:] if host.startswith("www.") else host
        if base not in domains and f"*.{base}" not in domains:
            domains += [base, f"*.{base}"]
    return [f"WebFetch(domain:{d})" for d in domains]


def rules_for(capability: str, mode: str) -> list:
    spec = CAPABILITIES[capability]
    if mode not in spec["modes"]:
        raise SetupError(f"`{capability}` has no mode `{mode}` (one of: {', '.join(spec['modes'])}).")
    rules = spec["modes"][mode]
    return job_site_rules() if rules is None else list(rules)


def managed_rules(capability: str) -> set:
    out = set()
    for mode in CAPABILITIES[capability]["modes"]:
        out.update(rules_for(capability, mode))
    if capability == "web_pages":  # any domain rule, including ones a run saved
        out.add("WebFetch")
    return out


class SetupError(RuntimeError):
    pass


def claude_settings_path() -> Path:
    override = os.environ.get("JOBISSIMO_CLAUDE_LOCAL_SETTINGS")
    return Path(override) if override else paths.REPO_ROOT / ".claude" / "settings.local.json"


def read_claude_settings() -> dict:
    p = claude_settings_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise SetupError(f"{p} is not valid JSON ({exc}); fix it by hand first.")
    return data if isinstance(data, dict) else {}


def allow_rules() -> list:
    return list(((read_claude_settings().get("permissions") or {}).get("allow")) or [])


def current_mode(capability: str, rules: list | None = None) -> str:
    rules = set(allow_rules() if rules is None else rules)
    modes = CAPABILITIES[capability]["modes"]
    if capability == "web_pages":
        if "WebFetch" in rules:
            return "any"
        ours = set(job_site_rules())
        if ours and ours <= rules:
            return "job_sites"
        return "ask"
    for mode in modes:
        want = rules_for(capability, mode)
        if want and set(want) <= rules:
            return mode
    return "ask"


def set_permission(capability: str, mode: str) -> dict:
    if capability not in CAPABILITIES:
        raise SetupError(f"Unknown capability `{capability}` (one of: {', '.join(CAPABILITIES)}).")
    new_rules = rules_for(capability, mode)
    data = read_claude_settings()
    perms = data.setdefault("permissions", {})
    allow = list(perms.get("allow") or [])
    managed = managed_rules(capability)
    if capability == "web_pages" and mode == "ask":
        # "ask each time" means every site, including ones a run saved
        managed |= {r for r in allow if r == "WebFetch" or r.startswith("WebFetch(")}
    kept = [r for r in allow if r not in managed]
    perms["allow"] = kept + [r for r in new_rules if r not in kept]
    p = claude_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _log("agent_permission_changed", {"capability": capability, "mode": mode, "rules": len(new_rules)})
    return {"capability": capability, "mode": mode, "rules": new_rules}


# ---------------------------------------------------------------- prefs

PREFS = {
    "claude.model": {"type": "choice", "choices": ["", "opus", "sonnet", "haiku"], "default": "",
                     "label": "Claude model", "help": "Empty = your Claude Code default."},
    "claude.effort": {"type": "choice", "choices": ["", "low", "medium", "high", "xhigh", "max"],
                      "default": "", "label": "Claude effort", "help": "Empty = your default."},
    "claude.chrome": {"type": "bool", "default": None, "label": "Start browser runs with Chrome",
                      "help": "Passes --chrome to /hunt, /refresh and /cycle. Default follows "
                              "capabilities.yaml (browse: claude-in-chrome)."},
    "codex.network": {"type": "bool", "default": False, "label": "Codex web access",
                      "help": "Lets commands in the Codex sandbox reach the network (curl a posting)."},
    "codex.web_search": {"type": "bool", "default": False, "label": "Codex web search",
                         "help": "Turns on Codex's web search tool for UI runs."},
    "codex.reasoning_effort": {"type": "choice", "choices": ["", "minimal", "low", "medium", "high", "xhigh"],
                               "default": "", "label": "Codex reasoning effort",
                               "help": "Empty = your ~/.codex/config.toml. High effort makes short "
                                       "commands take minutes."},
    "runs.max_parallel": {"type": "int", "min": 1, "max": 4, "default": 3, "label": "Runs at once",
                          "help": "Commands that touch the same things never overlap, whatever this says."},
    "runs.ask_timeout_min": {"type": "int", "min": 5, "max": 240, "default": 30,
                             "label": "Wait for an answer (minutes)",
                             "help": "After this, an unanswered question or permission takes the safe "
                                     "default (deny / halt) and the run carries on."},
}


def prefs_path() -> Path:
    return paths.config_dir() / "local" / "agents.json"


def load_prefs() -> dict:
    out = {k: spec["default"] for k, spec in PREFS.items()}
    try:
        stored = json.loads(prefs_path().read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            for k, v in stored.items():
                if k in PREFS:
                    try:
                        out[k] = _coerce(k, v)
                    except SetupError:
                        pass
    except (OSError, json.JSONDecodeError):
        pass
    if out["claude.chrome"] is None:
        out["claude.chrome"] = browse_adapter() == "claude-in-chrome"
    return out


def _coerce(key: str, value):
    spec = PREFS[key]
    if spec["type"] == "bool":
        if isinstance(value, bool) or value is None:
            return value
        if str(value).lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).lower() in ("false", "0", "no", "off"):
            return False
        raise SetupError(f"{key} must be true or false.")
    if spec["type"] == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise SetupError(f"{key} must be a number.")
        if not spec["min"] <= n <= spec["max"]:
            raise SetupError(f"{key} must be between {spec['min']} and {spec['max']}.")
        return n
    value = "" if value is None else str(value)
    if value not in spec["choices"]:
        raise SetupError(f"{key} must be one of: {', '.join(c or '(default)' for c in spec['choices'])}.")
    return value


def set_pref(key: str, value) -> dict:
    if key not in PREFS:
        raise SetupError(f"Unknown preference `{key}`.")
    value = _coerce(key, value)
    p = prefs_path()
    try:
        stored = json.loads(p.read_text(encoding="utf-8"))
        stored = stored if isinstance(stored, dict) else {}
    except (OSError, json.JSONDecodeError):
        stored = {}
    stored[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"key": key, "value": value}


def browse_adapter() -> str:
    try:
        return str((packs.load_config("capabilities").get("adapters") or {}).get("browse") or "")
    except Exception:
        return ""


def _log(action: str, detail: dict) -> None:
    subprocess.run([sys.executable, str(SCRIPTS / "db.py"), "log", "--run-id", "ui", "--command", "ui",
                    "--action", action, "--detail", json.dumps(detail)], capture_output=True, text=True)


# ---------------------------------------------------------------- agents

def _agent_runner():
    import agent_runner  # late: agent_runner imports this module
    return agent_runner


def probe_claude(binary: str, timeout: float = 12.0) -> dict:
    """Sign-in and connectors without spending a token: start the CLI in
    stream mode, send `initialize` and `mcp_status`, then close it."""
    env = _agent_runner().child_env()
    try:
        proc = subprocess.Popen([binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                                 "--verbose", "--permission-prompt-tool", "stdio", "--chrome"],
                                cwd=paths.REPO_ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1)
    except OSError as exc:
        return {"error": str(exc)}
    deadline = time.time() + timeout

    def ask(rid: str, subtype: str):
        proc.stdin.write(json.dumps({"type": "control_request", "request_id": rid,
                                     "request": {"subtype": subtype}}) + "\n")
        proc.stdin.flush()
        while time.time() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], max(0.0, deadline - time.time()))
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "control_response" and (o.get("response") or {}).get("request_id") == rid:
                return (o["response"] or {}).get("response") or {}
        return None

    out: dict = {}
    try:
        init = ask("init", "initialize")
        if init is None:
            return {"error": "Claude Code did not answer (old version, or not signed in)."}
        acct = init.get("account") or {}
        out["signed_in"] = bool(acct.get("email") or acct.get("apiProvider"))
        out["account"] = {k: acct.get(k) for k in ("email", "subscriptionType", "apiProvider") if acct.get(k)}
        out["models"] = [m.get("value") for m in init.get("models") or [] if m.get("value")]
        servers = []
        for i in range(4):
            time.sleep(1.0 if i else 1.5)
            status = ask(f"mcp{i}", "mcp_status")
            servers = (status or {}).get("mcpServers") or []
            if not any(s.get("status") == "pending" for s in servers):
                break
        out["connectors"] = {s["name"]: s.get("status") for s in servers
                             if s.get("name") and not s["name"].startswith("plugin:")}
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return out


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _codex_config_text() -> str:
    try:
        return (codex_home() / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return ""


def codex_config() -> dict:
    text = _codex_config_text()
    try:
        import tomllib
        data = tomllib.loads(text) if text else {}
    except Exception:
        data = {}
    repo = str(paths.REPO_ROOT)
    trust = ((data.get("projects") or {}).get(repo) or {}).get("trust_level")
    return {"model": data.get("model"), "reasoning_effort": data.get("model_reasoning_effort"),
            "trusted": trust == "trusted", "repo": repo, "config": str(codex_home() / "config.toml")}


def codex_trust() -> dict:
    repo = str(paths.REPO_ROOT)
    if codex_config()["trusted"]:
        return {"trusted": True, "changed": False}
    text = _codex_config_text()
    header = f'[projects."{repo}"]'
    if header in text:
        start = text.index(header)
        nxt = text.find("\n[", start + len(header))
        block = text[start:nxt if nxt != -1 else len(text)]
        if re.search(r"(?m)^trust_level\s*=", block):
            new_block = re.sub(r'(?m)^trust_level\s*=.*$', 'trust_level = "trusted"', block)
        else:
            new_block = block.rstrip("\n") + '\ntrust_level = "trusted"\n'
        text = text.replace(block, new_block, 1)
    else:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f'{header}\ntrust_level = "trusted"\n'
    path = codex_home() / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"trusted": True, "changed": True}


def codex_login(binary: str) -> dict:
    try:
        r = subprocess.run([binary, "login", "status"], capture_output=True, text=True, timeout=15,
                           stdin=subprocess.DEVNULL, env=_agent_runner().child_env())
        text = (r.stdout + r.stderr).strip().splitlines()
        line = text[0] if text else ""
        return {"signed_in": r.returncode == 0 and "not logged" not in line.lower(), "login": line[:120]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"signed_in": None, "login": str(exc)[:120]}


# ---------------------------------------------------------------- tools

TOOLS = [
    {"id": "python3", "label": "Python 3", "purpose": "Every script", "bins": ["python3"], "required": True},
    {"id": "git", "label": "Git", "purpose": "/sync — your private workspace repo", "bins": ["git"]},
    {"id": "pandoc", "label": "Pandoc", "purpose": "DOCX export of CVs and letters", "bins": ["pandoc"],
     "required": True, "brew": "pandoc"},
    {"id": "pdf_engine", "label": "PDF engine", "purpose": "PDF export (tectonic, xelatex or pdflatex)",
     "bins": ["tectonic", "xelatex", "pdflatex"], "brew": "tectonic"},
    {"id": "poppler", "label": "Poppler", "purpose": "Reading PDF documents at intake; checking a CV's page count",
     "bins": ["pdftotext", "pdftoppm"], "brew": "poppler"},
    {"id": "tesseract", "label": "Tesseract", "purpose": "OCR for scanned PDFs at intake", "bins": ["tesseract"],
     "brew": "tesseract"},
]
INSTALLABLE = {t["id"]: t["brew"] for t in TOOLS if t.get("brew")}


def check_tools() -> list:
    sp = _agent_runner().search_path()
    out = []
    for t in TOOLS:
        found = [(b, shutil.which(b, path=sp)) for b in t["bins"]]
        hit = [(b, p) for b, p in found if p]
        out.append({"id": t["id"], "label": t["label"], "purpose": t["purpose"], "required": t.get("required", False),
                    "found": bool(hit if t["id"] != "poppler" else len(hit) == len(found)),
                    "paths": {b: p for b, p in hit}, "install": t.get("brew")})
    return out


def brew() -> str | None:
    return shutil.which("brew", path=_agent_runner().search_path())


# ---------------------------------------------------------------- report

def check(quick: bool = False) -> dict:
    ar = _agent_runner()
    agents = ar.detect(refresh=True)
    claude = dict(agents.get("claude") or {})
    codex = dict(agents.get("codex") or {})
    if claude.get("available") and not quick:
        claude.update(probe_claude(claude["path"]))
    if codex.get("available"):
        if not quick:
            codex.update(codex_login(codex["path"]))
        codex.update(codex_config())
    rules = allow_rules()
    perms = {}
    for cap, spec in CAPABILITIES.items():
        perms[cap] = {"label": spec["label"], "help": spec["help"], "mode": current_mode(cap, rules),
                      "modes": [{"id": m, "label": spec["mode_labels"][m]} for m in spec["modes"]]}
    saved_domains = sorted(r[len("WebFetch(domain:"):-1] for r in rules
                           if r.startswith("WebFetch(domain:") and r not in set(job_site_rules()))
    perms["web_pages"]["saved"] = saved_domains
    prefs = load_prefs()
    tools = check_tools()
    try:
        adapters = packs.load_config("capabilities").get("adapters") or {}
    except Exception:
        adapters = {}
    ws = paths.home()
    report = {
        "workspace": {"path": str(ws), "config": str(paths.config_dir()), "git": (ws / ".git").exists(),
                      "settings_file": str(claude_settings_path()), "prefs_file": str(prefs_path())},
        "agents": {"claude": claude, "codex": codex},
        "permissions": perms,
        "prefs": prefs,
        "pref_specs": PREFS,
        "tools": tools,
        "brew": brew(),
        "adapters": {k: adapters.get(k) for k in ("browse", "mail", "export")},
        "quick": quick,
    }
    report["recommendations"] = recommendations(report)
    return report


def recommendations(r: dict) -> list:
    out = []
    claude, codex = r["agents"]["claude"], r["agents"]["codex"]
    perms, adapters = r["permissions"], r["adapters"]

    def add(level, text, fix=None):
        out.append({"level": level, "text": text, "fix": fix})

    if not claude.get("available") and not codex.get("available"):
        add("error", "No agent CLI found. Install Claude Code or Codex to run commands from here.")
    if claude.get("available") and claude.get("signed_in") is False:
        add("error", "Claude Code is not signed in. Run `claude` in a terminal and sign in.")
    if claude.get("error"):
        add("warn", f"Claude Code check: {claude['error']}")
    conns = claude.get("connectors") or {}
    if adapters.get("browse") == "claude-in-chrome" and claude.get("available") and not r["quick"]:
        if conns.get("claude-in-chrome") != "connected":
            add("warn", "Your browse adapter is Claude in Chrome, but the extension did not connect. "
                        "Open Chrome with the Claude extension signed in, then check again.")
        elif perms["browser"]["mode"] == "ask":
            add("info", "Browser runs will ask before every browser step. Allow browser steps to let "
                        "/hunt and /refresh browse without stopping.",
                {"kind": "permission", "capability": "browser", "mode": "allow"})
    if adapters.get("mail") == "gmail-mcp" and claude.get("available") and not r["quick"]:
        gm = conns.get("claude.ai Gmail")
        if gm != "connected":
            add("warn", "Your mail adapter is Gmail, but the claude.ai Gmail connector is "
                        f"{gm or 'not set up'}. Connect it at claude.ai → Settings → Connectors.")
        elif perms["mail"]["mode"] == "ask":
            add("info", "Runs will ask before each Gmail read.",
                {"kind": "permission", "capability": "mail", "mode": "read"})
    if claude.get("available") and perms["web_pages"]["mode"] == "ask":
        add("info", "Runs ask before reading each new site. Let them read job sites without asking — "
                    "/refresh and /hunt read many postings.",
            {"kind": "permission", "capability": "web_pages", "mode": "job_sites"})
    if codex.get("available"):
        if not codex.get("trusted"):
            add("warn", "Codex does not trust this repo, so its command rules don't load and more steps "
                        "need approval.", {"kind": "codex_trust"})
        if codex.get("signed_in") is False:
            add("error", "Codex is not signed in. Run `codex login` in a terminal.")
        if (codex.get("reasoning_effort") in ("high", "xhigh")) and not r["prefs"]["codex.reasoning_effort"]:
            add("info", f"Codex uses reasoning effort `{codex['reasoning_effort']}`, so UI runs are slow. "
                        "Use a lower effort for UI runs only.",
                {"kind": "pref", "key": "codex.reasoning_effort", "value": "medium"})
        if not r["prefs"]["codex.network"]:
            add("info", "Codex runs have no network, so /hunt and /refresh can't read postings with Codex.",
                {"kind": "pref", "key": "codex.network", "value": True})
    for t in r["tools"]:
        if not t["found"] and t["required"]:
            add("warn", f"{t['label']} is missing — needed for: {t['purpose']}.",
                {"kind": "install", "tool": t["id"]} if t["install"] and r["brew"] else None)
    return out


# ---------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="Report agents, permissions, connectors and tools as JSON.")
    c.add_argument("--quick", action="store_true", help="Skip the Claude/Codex sign-in probes.")
    p = sub.add_parser("permission", help="Set what runs may do without asking.")
    p.add_argument("capability", choices=list(CAPABILITIES))
    p.add_argument("mode")
    q = sub.add_parser("pref", help="Set one run preference.")
    q.add_argument("key", choices=list(PREFS))
    q.add_argument("value")
    sub.add_parser("codex-trust", help="Trust this repo in Codex so its project rules load.")
    i = sub.add_parser("install", help="Install a missing tool with Homebrew (streams brew's output).")
    i.add_argument("tool", choices=list(INSTALLABLE))
    args = parser.parse_args()
    try:
        if args.cmd == "check":
            print(json.dumps(check(args.quick), indent=2))
        elif args.cmd == "permission":
            print(json.dumps(set_permission(args.capability, args.mode)))
        elif args.cmd == "pref":
            print(json.dumps(set_pref(args.key, args.value)))
        elif args.cmd == "codex-trust":
            print(json.dumps(codex_trust()))
        elif args.cmd == "install":
            b = brew()
            if not b:
                raise SetupError("Homebrew is not installed; install the tool another way.")
            print(f"$ brew install {INSTALLABLE[args.tool]}", flush=True)
            os.execv(b, [b, "install", INSTALLABLE[args.tool]])
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
