#!/usr/bin/env python3
"""agent_runner.py — run a Jobissimo command in the user's own Claude Code or
Codex, turn its event stream into steps a UI can show, and carry the
conversation: questions, permission requests and replies go to the user.

The local UI (scripts/ui.py) uses this for its Run buttons. Nothing here is a
new agent: it starts the CLI the user already has, logged in with the user's
own account, on this machine — exactly as typing the command would.

- **Claude Code** runs in stream mode (`claude -p --input-format stream-json
  --output-format stream-json --permission-prompt-tool stdio`). When the
  agent wants a tool its permissions don't cover, or asks a question
  (AskUserQuestion), the request comes here and waits for the user's answer
  in the run panel. Edits are allowed without asking only inside the
  workspace.
- **Codex** runs `codex exec --json` in its workspace-write sandbox. It cannot
  ask mid-run, so where a command would ask it ends its turn with the
  question; the user's reply resumes the same session (`codex exec resume`).
- A finished run can always be continued: a reply starts the next turn in the
  same session (`claude --resume`, `codex exec resume`).

Only a fixed set of commands can be started, each with validated arguments.
`/apply` is not one of them (it fills forms in your browser and must stop for
you before submitting), nor is /sync. Runs that touch the same
things never overlap; others run side by side up to a limit.

    python3 scripts/agent_runner.py detect           # which agents are usable
    python3 scripts/agent_runner.py commands         # what the UI may start
    python3 scripts/agent_runner.py run claude dashboard   # stream steps to stdout

Raw transcripts are kept in <workspace>/state/agent_runs/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_setup  # noqa: E402
import paths  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
EXTRA_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin"),
                  str(Path.home() / ".npm-global/bin"), str(Path.home() / ".bun/bin")]
JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
ENRICH_ARG_RE = re.compile(r"\d{1,2}|metrics|skills|targets|identity")
SETUP_ARG_RE = re.compile(r"--resume|--stage [a-z_]{2,20}")
OUTPUT_CAP = 6000   # characters of tool output kept per step for the UI
TEXT_CAP = 20000
RUN_ID_RE = r"ui_\d{8}_\d{6}_[a-z]+_[0-9a-f]{4}"


def run_note(agent: str, command: str = "") -> str:
    """Appended to the agent's instructions for every UI-started run."""
    ws = str(paths.home())
    extra = ""
    if command == "setup":
        extra = (" Setup started from the UI: the user may already have uploaded documents there — "
                 "they are ingested in _intake/ (`python3 scripts/intake.py --list`). Read those before "
                 "asking for files, and ask only for what is missing. The user can upload more in the UI "
                 "(Get started → Your documents) and tell you when they have.")
    common = (
        f"You were started from the Jobissimo local UI. The workspace for this run is {ws} "
        "($JOBISSIMO_HOME): read and write workspace files only there — never in another workspace, "
        "even if a .jobissimo pointer or an additional directory names one. AGENTS.md invariants "
        "apply unchanged: never bypass an audit, submit an application, or accept a knowledge inbox "
        "item unless the user chose exactly that in an answer. End with the command's stdout summary; "
        "list anything still open under a 'Needs your decision' heading."
    )
    common += extra
    if agent == "claude":
        return common + (
            " The user watches this run in a side panel and can answer you. Where the command says to "
            "ask the user (an audit fix/bypass/halt decision, a confirmation, a missing fact), use the "
            "AskUserQuestion tool with short options; the user can also type an answer. If a question "
            "is declined or times out, take the safe default (halt that item) and carry on with the rest."
            " Shell: one plain command per Bash call — no `;`, `&&`, pipes, loops, `$VAR` or `$(...)`: "
            "those cannot be pre-approved and stop the run for a manual approval. Filter output with the "
            "Grep and Read tools rather than head/grep/awk; look jobs up with `db.py list`/`db.py get` or "
            "`readmodel.py jobs`. To read a web page use WebFetch, never curl. "
            "`python3 scripts/sync.py status` is allowed; other sync.py verbs are not."
        )
    prefs = agent_setup.load_prefs()
    web = ("Network access is on in this sandbox." if prefs["codex.network"]
           else "This sandbox has no network: a step that needs the web is recorded as blocked, not retried.")
    return common + (
        " Nobody can answer you mid-run. Where the command says to ask the user, do everything that "
        "does not depend on the answer, then end your turn with the questions as a short numbered list "
        "under 'Needs your decision' — the user replies in the UI and this session continues. " + web
    )


# name -> spec. `arg`: None | "job_id" | "text" | "enrich" ; `locks`: what a
# run of it touches (two runs whose locks meet never run at the same time).
COMMANDS = {
    "cycle": {"label": "Run a cycle", "help": "Reconcile mail, hunt, prepare the freshest, report.",
              "arg": None, "browser": True, "long": True,
              "locks": ["cycle", "hunt", "refresh", "track", "prepare:*", "browser"]},
    "hunt": {"label": "Hunt", "help": "Find, score and record new postings.",
             "arg": None, "browser": True, "long": True, "locks": ["hunt", "browser"]},
    "prepare": {"label": "Prepare", "help": "Generate, audit, score and export an application.",
                "arg": "job_id", "arg_required": False, "browser": False, "long": True, "locks": None},
    "refresh": {"label": "Check postings", "help": "Verify open postings are still live.",
                "arg": None, "browser": True, "long": False, "locks": ["refresh", "browser"]},
    "track": {"label": "Record an update", "help": "Tell Jobissimo what happened, in your words.",
              "arg": "text", "arg_required": True, "browser": False, "long": False, "locks": ["track"]},
    "enrich": {"label": "Answer profile questions", "help": "The profile gaps that matter most, asked "
               "in five minutes; your answers are written to your knowledge.",
               "arg": "enrich", "arg_required": False, "browser": False, "long": False,
               "locks": ["knowledge"], "conversation": True},
    "optimise": {"label": "Optimise", "help": "Analyse outcomes and propose changes for you to decide.",
                 "arg": None, "browser": False, "long": True, "locks": ["optimise"]},
    "setup": {"label": "Set up", "help": "Your documents into a knowledge base, your targets, "
              "and a first audited application — about 25 minutes, in the run panel.",
              "arg": "setup", "arg_required": False, "browser": True, "long": True, "conversation": True,
              "locks": ["setup", "knowledge", "hunt", "prepare:*", "browser"]},
    "doctor": {"label": "Health check", "help": "Config health, provenance and drift.",
               "arg": None, "browser": False, "long": False, "locks": []},
    "dashboard": {"label": "Dashboard", "help": "The pipeline dashboard, read-only.",
                  "arg": None, "browser": False, "long": False, "locks": []},
}
NOT_FROM_UI = {"apply": "it fills your browser and must stop for you before submitting — run it in Claude Code or Codex",
               "sync": "it pushes to a remote"}

# Never offered to the user as a permission, never run: an agent run does not
# start agents, open the UI, or change its own permissions.
PROTECTED_COMMAND = re.compile(
    r"(agent_runner|agent_setup|launcher|ui)\.py\b|(^|[\s;&|(`])(claude|codex)(\s|$)|settings(\.local)?\.json")
PROTECTED_PATH = re.compile(r"(^|/)\.claude/|(^|/)\.codex/|(^|/)\.claude\.json$|(^|/)config/local/")


class RunError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- detection

def search_path() -> str:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(parts + [d for d in EXTRA_BIN_DIRS if d not in parts])


def resolve(agent: str) -> str | None:
    """The agent binary: $JOBISSIMO_AGENT_<NAME> (tests, unusual installs),
    else the PATH plus the usual install dirs a GUI-started process lacks."""
    override = os.environ.get(f"JOBISSIMO_AGENT_{agent.upper()}")
    if override:
        return override if Path(override).exists() else None
    return shutil.which(agent, path=search_path())


def _version(binary: str) -> str | None:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL, env=child_env())
        return (out.stdout or out.stderr).strip().splitlines()[0][:80] if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


_detected: dict | None = None


def detect(refresh: bool = False) -> dict:
    global _detected
    if _detected is not None and not refresh:
        return _detected
    out = {}
    for agent, label in (("claude", "Claude Code"), ("codex", "Codex")):
        binary = resolve(agent)
        version = _version(binary) if binary else None
        out[agent] = {"label": label, "path": binary, "version": version,
                      "available": bool(binary and version),
                      "asks_live": agent == "claude"}
    _detected = out
    return out


# ---------------------------------------------------------------- argv

def child_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = search_path()
    env.setdefault("JOBISSIMO_HOME", str(paths.home()))
    return env


def prompt_for(agent: str, command: str, arg: str | None) -> str:
    sigil = "/" if agent == "claude" else "$"
    return f"{sigil}{command}" + (f" {arg}" if arg else "")


def validate(command: str, arg: str | None) -> str | None:
    if command in NOT_FROM_UI:
        raise RunError(f"/{command} cannot be started from the UI: {NOT_FROM_UI[command]}.")
    spec = COMMANDS.get(command)
    if spec is None:
        raise RunError(f"Unknown command `{command}`.")
    arg = (arg or "").strip() or None
    if spec["arg"] is None and arg:
        raise RunError(f"/{command} takes no argument.")
    if spec.get("arg_required") and not arg:
        raise RunError(f"/{command} needs {'a job id' if spec['arg'] == 'job_id' else 'a message'}.")
    if arg and spec["arg"] == "job_id" and not JOB_ID_RE.fullmatch(arg):
        raise RunError("That is not a job id.")
    if arg and spec["arg"] == "setup" and not SETUP_ARG_RE.fullmatch(arg):
        raise RunError("/setup takes --resume or --stage <name>.")
    if arg and spec["arg"] == "enrich" and not ENRICH_ARG_RE.fullmatch(arg):
        raise RunError("/enrich takes a number or one of: metrics, skills, targets, identity.")
    if arg and spec["arg"] == "text":
        arg = re.sub(r"\s+", " ", arg)
        if len(arg) > 600:
            raise RunError("Keep the message under 600 characters.")
    return arg


def locks_for(command: str, arg: str | None) -> list:
    if command == "prepare":
        return [f"prepare:{arg}" if arg else "prepare:*"]
    return list(COMMANDS.get(command, {}).get("locks") or [])


def _meets(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.startswith("prepare:") and b.startswith("prepare:"):
        return a == "prepare:*" or b == "prepare:*"
    return False


def clash(a: list, b: list) -> bool:
    return any(_meets(x, y) for x in a for y in b)


def _workspace_roots() -> list:
    roots = []
    for p in (str(paths.home()), os.environ.get("JOBISSIMO_HOME", "")):
        if p:
            for q in (p.rstrip("/"), os.path.realpath(p)):
                if q not in roots:
                    roots.append(q)
    return roots


def claude_argv(command: str, resume: str | None = None) -> list:
    binary = resolve("claude")
    if not binary:
        raise RunError("claude is not installed or not on PATH.")
    prefs = agent_setup.load_prefs()
    ws = str(paths.home())
    tools = ["Read", "Glob", "Grep", "TodoWrite", "Bash(mkdir -p *)", "Bash(ls *)"]
    for root in _workspace_roots():  # edits without asking: the workspace, nowhere else
        tools += [f"Edit(/{root}/**)", f"Write(/{root}/**)"]
    argv = [binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--permission-prompt-tool", "stdio", "--permission-mode", "default",
            "--add-dir", ws, "--allowedTools", *tools,
            "--append-system-prompt", run_note("claude", command)]
    if COMMANDS.get(command, {}).get("browser") and prefs["claude.chrome"]:
        argv.append("--chrome")
    if prefs["claude.model"]:
        argv += ["--model", prefs["claude.model"]]
    if prefs["claude.effort"]:
        argv += ["--effort", prefs["claude.effort"]]
    if resume:
        argv += ["--resume", resume]
    return argv


def codex_argv(prompt: str, resume: str | None = None, command: str = "") -> list:
    binary = resolve("codex")
    if not binary:
        raise RunError("codex is not installed or not on PATH.")
    prefs = agent_setup.load_prefs()
    ws = str(paths.home())
    conf = []
    if prefs["codex.network"]:
        conf += ["-c", "sandbox_workspace_write.network_access=true"]
    if prefs["codex.web_search"]:
        conf += ["-c", 'web_search="live"']
    if prefs["codex.reasoning_effort"]:
        conf += ["-c", f'model_reasoning_effort="{prefs["codex.reasoning_effort"]}"']
    if resume:
        return [binary, "exec", "resume", "--json", "-c", 'sandbox_mode="workspace-write"',
                "-c", f"sandbox_workspace_write.writable_roots={json.dumps([ws])}", *conf, resume, prompt]
    return [binary, "exec", "--json", "--sandbox", "workspace-write", "--add-dir", ws, *conf,
            f"{prompt}\n\n{run_note('codex', command)}"]


def build_argv(agent: str, command: str, arg: str | None) -> list:
    """The first turn's argv (Claude reads its prompt from stdin)."""
    if agent == "claude":
        return claude_argv(command)
    if agent == "codex":
        return codex_argv(prompt_for(agent, command, arg), command=command)
    raise RunError(f"Unknown agent `{agent}`.")


# ---------------------------------------------------------------- normalising

def _short(s, n=OUTPUT_CAP) -> str:
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False) if s is not None else ""
    return s if len(s) <= n else s[:n] + f"\n… ({len(s) - n} more characters)"


def _tool_title(name: str, inp: dict) -> tuple:
    """(verb, target) for a Claude tool call, Cursor-style."""
    inp = inp or {}
    if name == "Bash":
        return "Ran", inp.get("command", "")
    if name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        verb = {"Read": "Read", "Write": "Wrote"}.get(name, "Edited")
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return verb, _rel(p)
    if name in ("Glob", "Grep"):
        return "Searched", inp.get("pattern", "")
    if name == "WebFetch":
        return "Fetched", inp.get("url", "")
    if name == "WebSearch":
        return "Searched the web", inp.get("query", "")
    if name.startswith("mcp__claude-in-chrome__"):
        action = name.rsplit("__", 1)[-1].replace("_", " ")
        return "Browser", inp.get("url") or action
    if name.startswith("mcp__claude_ai_Gmail__"):
        return "Gmail", name.rsplit("__", 1)[-1].replace("_", " ") + (f" · {inp['query']}" if inp.get("query") else "")
    if name.startswith("mcp__"):
        return name.split("__")[1], name.rsplit("__", 1)[-1]
    if name in ("Skill", "SlashCommand"):
        return "Loaded", inp.get("skill") or inp.get("command") or name
    if name == "ToolSearch":
        return "Loaded", (inp.get("query") or "").replace("select:", "") + " tools"
    if name == "TodoWrite":
        return "Planned", f"{len(inp.get('todos') or [])} steps"
    return name, _short(json.dumps(inp, ensure_ascii=False), 160)


def _rel(p: str) -> str:
    """Workspace- or repo-relative, whichever spelling of the path the agent
    used (macOS: /var is /private/var)."""
    bases = []
    for root in (paths.home(), paths.REPO_ROOT):
        bases += [str(root), str(root.resolve())]
    if os.environ.get("JOBISSIMO_HOME"):
        bases.append(os.environ["JOBISSIMO_HOME"].rstrip("/"))
    for base in sorted(set(bases), key=len, reverse=True):
        if p.startswith(base + "/"):
            return p[len(base) + 1:]
    return p


SILENT_TOOLS = {"AskUserQuestion"}  # shown as a question card instead


def normalize_claude(e: dict) -> list:
    t = e.get("type")
    out = []
    if t == "system" and e.get("subtype") == "init":
        out.append({"kind": "init", "session": e.get("session_id"), "model": e.get("model")})
    elif t == "assistant":
        for b in (e.get("message") or {}).get("content") or []:
            bt = b.get("type")
            if bt == "thinking" and b.get("thinking"):
                out.append({"kind": "thinking", "text": _short(b["thinking"], TEXT_CAP)})
            elif bt == "text" and b.get("text", "").strip():
                out.append({"kind": "text", "text": _short(b["text"], TEXT_CAP)})
            elif bt == "tool_use" and b.get("name") not in SILENT_TOOLS:
                verb, target = _tool_title(b.get("name", ""), b.get("input"))
                out.append({"kind": "tool", "id": b.get("id"), "tool": b.get("name"),
                            "verb": verb, "target": _short(target, 400), "status": "running"})
    elif t == "user":
        content = (e.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                out.append({"kind": "tool_result", "id": b.get("tool_use_id"),
                            "status": "error" if b.get("is_error") else "done", "output": _short(c)})
    elif t == "result":
        out.append({"kind": "result", "ok": not e.get("is_error") and e.get("subtype") == "success",
                    "text": _short(e.get("result") or "", TEXT_CAP), "duration_ms": e.get("duration_ms"),
                    "turns": e.get("num_turns"), "cost_usd": e.get("total_cost_usd"),
                    "session": e.get("session_id")})
    return out


def normalize_codex(e: dict) -> list:
    t = e.get("type") or ""
    item = e.get("item") or {}
    it = item.get("type")
    out = []
    if t == "thread.started":
        out.append({"kind": "init", "session": e.get("thread_id")})
    elif t in ("item.started", "item.completed") and it == "command_execution":
        cmd = item.get("command") or ""
        m = re.match(r"^/bin/\w*sh -lc '(.*)'$", cmd, re.S)
        cmd = m.group(1) if m else cmd
        if t == "item.started":
            out.append({"kind": "tool", "id": item.get("id"), "tool": "shell", "verb": "Ran",
                        "target": _short(cmd, 400), "status": "running"})
        else:
            code = item.get("exit_code")
            out.append({"kind": "tool_result", "id": item.get("id"),
                        "status": "done" if code in (0, None) else "error",
                        "output": _short(item.get("aggregated_output") or ""), "exit_code": code})
    elif t == "item.completed" and it == "agent_message":
        out.append({"kind": "text", "text": _short(item.get("text") or "", TEXT_CAP)})
    elif t == "item.completed" and it == "reasoning":
        out.append({"kind": "thinking", "text": _short(item.get("text") or "", TEXT_CAP)})
    elif t == "item.completed" and it == "file_change":
        files = ", ".join(_rel(c.get("path", "")) for c in item.get("changes") or [])
        out.append({"kind": "tool", "id": item.get("id"), "tool": "edit", "verb": "Edited",
                    "target": files, "status": "done"})
    elif t in ("item.started", "item.completed") and it == "web_search":
        if t == "item.completed":
            out.append({"kind": "tool", "id": item.get("id"), "tool": "web_search", "verb": "Searched the web",
                        "target": item.get("query") or "", "status": "done"})
    elif t in ("item.started", "item.completed") and it == "mcp_tool_call":
        tid = item.get("id")
        if t == "item.started":
            out.append({"kind": "tool", "id": tid, "tool": item.get("tool"), "verb": item.get("server") or "Tool",
                        "target": item.get("tool") or "", "status": "running"})
        else:
            out.append({"kind": "tool_result", "id": tid,
                        "status": "error" if item.get("error") else "done",
                        "output": _short(item.get("result") or item.get("error") or "")})
    elif t == "item.completed" and it == "todo_list":
        out.append({"kind": "tool", "id": item.get("id"), "tool": "plan", "verb": "Planned",
                    "target": f"{len(item.get('items') or [])} steps", "status": "done"})
    elif t == "turn.completed":
        out.append({"kind": "usage", "tokens": (e.get("usage") or {})})
    elif t in ("turn.failed", "error"):
        msg = e.get("message") or (e.get("error") or {}).get("message") or json.dumps(e)[:300]
        out.append({"kind": "error", "text": _short(msg, 2000)})
    return out


def normalize_text(line: str) -> list:
    return [{"kind": "log", "text": _short(line, 500)}]


# ---------------------------------------------------------------- asks

def describe_permission(tool: str, inp: dict, req: dict) -> dict:
    """What the agent wants to do, in the user's words."""
    inp = inp or {}
    if tool == "Bash":
        return {"title": "Run a command", "detail": inp.get("command", ""), "mono": True,
                "why": inp.get("description")}
    if tool == "WebFetch":
        return {"title": "Read a web page", "detail": inp.get("url", ""), "url": inp.get("url")}
    if tool == "WebSearch":
        return {"title": "Search the web", "detail": inp.get("query", "")}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        return {"title": "Change a file outside the workspace" if not _in_workspace(p) else "Change a file",
                "detail": p, "mono": True}
    if tool == "Read":
        return {"title": "Read a file outside the workspace", "detail": inp.get("file_path", ""), "mono": True}
    if tool.startswith("mcp__claude-in-chrome__"):
        action = tool.rsplit("__", 1)[-1].replace("_", " ")
        return {"title": f"Use your Chrome — {action}", "detail": inp.get("url") or _short(json.dumps(inp), 300),
                "url": inp.get("url")}
    if tool.startswith("mcp__claude_ai_Gmail__"):
        return {"title": f"Gmail — {tool.rsplit('__', 1)[-1].replace('_', ' ')}",
                "detail": inp.get("query") or inp.get("thread_id") or inp.get("message_id") or ""}
    return {"title": f"Use {req.get('display_name') or tool}", "detail": _short(json.dumps(inp, ensure_ascii=False), 600),
            "mono": True}


def _in_workspace(p: str) -> bool:
    return any(p == r or p.startswith(r + "/") for r in _workspace_roots())


def protected(tool: str, inp: dict) -> str | None:
    """Why this request is refused without asking, or None."""
    inp = inp or {}
    if tool == "Bash" and PROTECTED_COMMAND.search(inp.get("command", "")):
        return "A run started from the UI may not start agents, open the UI, or change agent permissions."
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        if PROTECTED_PATH.search(p):
            return "A run may not edit agent settings or permissions."
    return None


class Ask:
    def __init__(self, run: "Run", request_id: str, req: dict):
        self.run = run
        self.request_id = request_id
        self.id = f"a{len(run.asks) + 1}"
        self.tool = req.get("tool_name") or ""
        self.input = req.get("input") or {}
        self.kind = "question" if self.tool == "AskUserQuestion" else "permission"
        self.status = "pending"
        self.created = time.time()
        self.answer_summary = None
        self.rules = []
        if self.kind == "permission":
            for s in req.get("permission_suggestions") or []:
                if s.get("type") == "addRules" and s.get("behavior", "allow") == "allow":
                    for r in s.get("rules") or []:
                        txt = r.get("toolName", "") + (f"({r['ruleContent']})" if r.get("ruleContent") else "")
                        self.rules.append(txt)
            self.suggestions = [s for s in req.get("permission_suggestions") or []
                                if s.get("type") == "addRules" and s.get("behavior", "allow") == "allow"]
            self.desc = describe_permission(self.tool, self.input, req)
        self.timer: threading.Timer | None = None

    def public(self) -> dict:
        out = {"id": self.id, "kind": self.kind, "status": self.status, "tool": self.tool,
               "answer": self.answer_summary}
        if self.kind == "question":
            out["questions"] = [{"question": q.get("question", ""), "header": q.get("header", ""),
                                 "multiSelect": bool(q.get("multiSelect")),
                                 "options": [{"label": o.get("label", ""), "description": o.get("description", "")}
                                             for o in q.get("options") or []]}
                                for q in self.input.get("questions") or []]
        else:
            out.update(self.desc)
            out["rules"] = self.rules
        return out


# ---------------------------------------------------------------- runs

class Run:
    def __init__(self, agent: str, command: str, arg: str | None):
        self.agent, self.command, self.arg = agent, command, arg
        self.id = f"ui_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{command}_{secrets.token_hex(2)}"
        self.status = "starting"
        self.started_at, self.ended_at = now_iso(), None
        self.t0 = time.time()
        self.turn = 0
        self.turn_t0 = self.t0
        self.active_s = 0.0
        self.events: list = []
        self.session = None
        self.cost_usd = None
        self.tokens = None
        self.summary = None
        self.error = None
        self.exit_code = None
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.wlock = threading.Lock()
        self.stderr_tail: list = []
        self.transcript: Path | None = None
        self.stopping = False
        self.asks: dict = {}
        self.locks = locks_for(command, arg) if agent != "task" else ["install"]
        self.on_done = None
        self.argv_task: list | None = None

    @property
    def label(self) -> str:
        if self.agent == "task":
            return f"Install {self.arg}"
        return prompt_for(self.agent, self.command, self.arg)

    @property
    def busy(self) -> bool:
        return self.status in ("starting", "running", "needs_input")

    def pending_asks(self) -> list:
        return [a.public() for a in self.asks.values() if a.status == "pending"]

    def meta(self) -> dict:
        elapsed = self.active_s + (time.time() - self.turn_t0 if self.busy else 0)
        return {"id": self.id, "agent": self.agent, "command": self.command, "arg": self.arg,
                "label": self.label, "status": self.status, "started_at": self.started_at,
                "ended_at": self.ended_at, "elapsed_s": round(elapsed, 1), "turn": self.turn,
                "session": self.session, "cost_usd": self.cost_usd, "tokens": self.tokens,
                "summary": self.summary, "error": self.error, "exit_code": self.exit_code,
                "stopping": self.stopping, "events": len(self.events), "asks": self.pending_asks(),
                "can_reply": (not self.busy and bool(self.session) and self.agent in ("claude", "codex")),
                "conversation": bool(COMMANDS.get(self.command, {}).get("conversation"))}

    def add(self, ev: dict) -> None:
        with self.lock:
            ev = {"seq": len(self.events) + 1, "ts": round(time.time() - self.t0, 1), "turn": self.turn, **ev}
            self.events.append(ev)
            if ev["kind"] == "init" and ev.get("session"):
                self.session = ev["session"]
            if ev["kind"] == "result":
                self.summary = ev.get("text")
                if ev.get("cost_usd") is not None:
                    self.cost_usd = round((self.cost_usd or 0) + ev["cost_usd"], 4)
                if ev.get("session"):
                    self.session = ev["session"]
            if ev["kind"] == "usage":
                tok = dict(self.tokens or {})
                for k, v in (ev.get("tokens") or {}).items():
                    if isinstance(v, (int, float)):
                        tok[k] = tok.get(k, 0) + v
                self.tokens = tok
            if ev["kind"] == "text" and self.agent == "codex":
                self.summary = ev.get("text")  # codex: the last message is the summary

    def since(self, after: int) -> list:
        with self.lock:
            return self.events[after:]

    # ---- the Claude control channel
    def _send(self, obj: dict) -> None:
        with self.wlock:
            if self.proc and self.proc.stdin and not self.proc.stdin.closed:
                try:
                    self.proc.stdin.write(json.dumps(obj) + "\n")
                    self.proc.stdin.flush()
                except (BrokenPipeError, ValueError, OSError):
                    pass

    def _close_stdin(self) -> None:
        with self.wlock:
            if self.proc and self.proc.stdin and not self.proc.stdin.closed:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass

    def _respond(self, request_id: str, response: dict | None = None, error: str | None = None) -> None:
        if error is not None:
            body = {"subtype": "error", "request_id": request_id, "error": error}
        else:
            body = {"subtype": "success", "request_id": request_id, "response": response or {}}
        self._send({"type": "control_response", "response": body})

    def _control(self, o: dict) -> None:
        req = o.get("request") or {}
        rid = o.get("request_id")
        if req.get("subtype") != "can_use_tool":
            self._respond(rid, error=f"unsupported control request: {req.get('subtype')}")
            return
        tool, inp = req.get("tool_name") or "", req.get("input") or {}
        why = protected(tool, inp)
        if why:
            self._respond(rid, {"behavior": "deny", "message": why})
            self.add({"kind": "error", "text": f"Blocked {tool}: {why}"})
            return
        ask = Ask(self, rid, req)
        self.asks[ask.id] = ask
        self.status = "needs_input"
        self.add({"kind": "ask", "ask": ask.public()})
        minutes = agent_setup.load_prefs()["runs.ask_timeout_min"]
        ask.timer = threading.Timer(minutes * 60, self._expire, args=(ask.id, minutes))
        ask.timer.daemon = True
        ask.timer.start()

    def _expire(self, ask_id: str, minutes: int) -> None:
        ask = self.asks.get(ask_id)
        if not ask or ask.status != "pending":
            return
        msg = (f"No answer from the user within {minutes} minutes. Take the safe default — halt or skip "
               "this item — and list it under 'Needs your decision'.")
        self._resolve(ask, {"behavior": "deny", "message": msg}, "expired", "No answer — took the safe default")

    def _cancel(self, request_id: str) -> None:
        for ask in self.asks.values():
            if ask.request_id == request_id and ask.status == "pending":
                ask.status = "cancelled"
                self.add({"kind": "ask_done", "id": ask.id, "outcome": "cancelled", "answer": "Withdrawn by the agent"})
        self._after_answer()

    def _resolve(self, ask: Ask, response: dict, outcome: str, summary: str) -> None:
        if ask.timer:
            ask.timer.cancel()
        ask.status, ask.answer_summary = outcome, summary
        self._respond(ask.request_id, response)
        self.add({"kind": "ask_done", "id": ask.id, "outcome": outcome, "answer": summary})
        self._after_answer()

    def _after_answer(self) -> None:
        if self.status == "needs_input" and not any(a.status == "pending" for a in self.asks.values()):
            self.status = "running"

    def answer(self, ask_id: str, body: dict) -> None:
        ask = self.asks.get(ask_id)
        if ask is None:
            raise RunError("Unknown question.", 404)
        if ask.status != "pending":
            raise RunError("That was already answered.", 409)
        if ask.kind == "question":
            if body.get("decline"):
                self._resolve(ask, {"behavior": "deny", "message": "The user chose not to answer. Take the "
                                    "safe default and list it under 'Needs your decision'."},
                              "declined", "Not answered")
                return
            answers = body.get("answers")
            if not isinstance(answers, dict):
                raise RunError("`answers` must map each question to an answer.")
            out, shown = {}, []
            for q in ask.input.get("questions") or []:
                text = q.get("question", "")
                a = answers.get(text)
                if isinstance(a, list):
                    a = ", ".join(str(x).strip() for x in a if str(x).strip())
                a = re.sub(r"\s+", " ", str(a or "")).strip()[:2000]
                if not a:
                    raise RunError(f"Answer: {text}")
                out[text] = a
                shown.append(a)
            self._resolve(ask, {"behavior": "allow", "updatedInput": {**ask.input, "answers": out}},
                          "answered", " · ".join(shown))
            return
        decision = body.get("decision")
        if decision == "deny":
            note = re.sub(r"\s+", " ", str(body.get("message") or "")).strip()[:500]
            msg = "The user denied this." + (f" They said: {note}" if note else
                                             " Do not retry it; take the safe default for that step.")
            self._resolve(ask, {"behavior": "deny", "message": msg}, "denied", "Denied" + (f": {note}" if note else ""))
        elif decision in ("allow", "always"):
            resp = {"behavior": "allow", "updatedInput": ask.input}
            summary = "Allowed once"
            if decision == "always" and ask.suggestions:
                resp["updatedPermissions"] = ask.suggestions
                summary = "Always allowed: " + ", ".join(ask.rules)
            self._resolve(ask, resp, "allowed", summary)
        else:
            raise RunError("decision must be allow, always or deny.")

    def expire_all(self, reason: str) -> None:
        for ask in self.asks.values():
            if ask.status == "pending":
                if ask.timer:
                    ask.timer.cancel()
                ask.status = "cancelled"
                self.add({"kind": "ask_done", "id": ask.id, "outcome": "cancelled", "answer": reason})


def _log_event(run_id: str, action: str, detail: dict) -> None:
    subprocess.run([sys.executable, str(SCRIPTS / "db.py"), "log", "--run-id", run_id,
                    "--command", "ui", "--action", action, "--detail", json.dumps(detail)],
                   capture_output=True, text=True, env=child_env())


def transcript_dir() -> Path:
    d = paths.home() / "state" / "agent_runs"
    d.mkdir(parents=True, exist_ok=True)
    ignore = d / ".gitignore"
    if not ignore.exists():  # transcripts are bulky and machine-local; never synced
        ignore.write_text("*\n", encoding="utf-8")
    return d


def _turn(run: Run, argv: list, first_message: str | None) -> None:
    """Start one process for one turn of `run` and pump it on threads."""
    run.turn += 1
    run.turn_t0 = time.time()
    run.stopping = False
    run.error = None
    run.status = "running"
    claude = run.agent == "claude"
    run.proc = subprocess.Popen(argv, cwd=paths.REPO_ROOT, env=child_env(),
                                stdin=subprocess.PIPE if claude else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                                start_new_session=True)
    if run.agent != "task":
        _log_event(run.id, "agent_run_started", {"agent": run.agent, "command": run.command, "arg": run.arg,
                                                 "turn": run.turn})
    if claude:
        run._send({"type": "control_request", "request_id": f"init_{run.turn}",
                   "request": {"subtype": "initialize"}})
        run._send({"type": "user", "message": {"role": "user", "content": first_message},
                   "parent_tool_use_id": None, "session_id": run.session or ""})
    normalize = {"claude": normalize_claude, "codex": normalize_codex}.get(run.agent)
    proc = run.proc

    def pump_stderr():
        for line in proc.stderr:
            run.stderr_tail = (run.stderr_tail + [line.rstrip()])[-20:]

    def pump():
        asked_before = len(run.asks)
        with run.transcript.open("a", encoding="utf-8") as raw:
            for line in proc.stdout:
                raw.write(line)
                line = line.strip()
                if not line:
                    continue
                if normalize is None:
                    for ev in normalize_text(line):
                        run.add(ev)
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    run.add({"kind": "log", "text": _short(line, 500)})
                    continue
                if claude and e.get("type") == "control_request":
                    run._control(e)
                    continue
                if claude and e.get("type") == "control_cancel_request":
                    run._cancel(e.get("request_id"))
                    continue
                if e.get("type") == "control_response":
                    continue
                for ev in normalize(e):
                    run.add(ev)
                if claude and e.get("type") == "result":
                    run._close_stdin()  # the turn is over; the process exits
        code = proc.wait()
        end = time.time()
        run.expire_all("The run ended first")
        if run.stopping:
            status, error = "stopped", "Stopped by you."
        else:
            results = [ev for ev in run.events if ev["kind"] == "result" and ev["turn"] == run.turn]
            ok = code == 0 and not any(not ev.get("ok") for ev in results) and (results or not claude)
            status, error = ("succeeded" if ok else "failed"), None
            if not ok:
                tail = [ln for ln in run.stderr_tail if ln.strip() and "stdin" not in ln.lower()]
                error = tail[-1] if tail else f"exited with code {code}"
        turn_asks = list(run.asks.values())[asked_before:]
        if run.agent != "task":
            # log first, publish second: whoever sees the final status can rely on the event
            _log_event(run.id, "agent_run_finished", {
                "agent": run.agent, "command": run.command, "status": status, "exit_code": code,
                "cost_usd": run.cost_usd, "duration_s": round(end - run.turn_t0, 1), "turn": run.turn,
                "asked": len(turn_asks), "denied": sum(a.status in ("denied", "expired") for a in turn_asks)})
        run.active_s += end - run.turn_t0
        run.exit_code, run.ended_at, run.error = code, now_iso(), error
        run.status = status
        if run.on_done:
            run.on_done(run)

    threading.Thread(target=pump_stderr, daemon=True).start()
    threading.Thread(target=pump, daemon=True).start()


class Manager:
    """The runs of one UI session: which may start, side by side or not."""

    def __init__(self):
        self.runs: dict = {}
        self.lock = threading.Lock()

    def busy(self) -> list:
        return [r for r in self.runs.values() if r.busy]

    def _admit(self, locks: list, exclude: Run | None = None) -> None:
        busy = [r for r in self.busy() if r is not exclude]
        limit = agent_setup.load_prefs()["runs.max_parallel"]
        if len(busy) >= limit:
            raise RunError(f"{len(busy)} run{'s are' if len(busy) > 1 else ' is'} going (your limit is {limit}). "
                           "Wait for one to finish, or raise the limit in Settings.", 409)
        for r in busy:
            if clash(locks, r.locks):
                raise RunError(f"{r.label} is still running and works on the same things — "
                               "wait for it to finish or stop it.", 409)

    def get(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise RunError("Unknown run (runs are kept for this server session).", 404)
        return run

    def start(self, agent: str, command: str, arg: str | None = None, on_done=None) -> Run:
        arg = validate(command, arg)
        info = detect().get(agent)
        if not info or not info["available"]:
            raise RunError(f"{agent} is not available on this machine.")
        with self.lock:
            self._admit(locks_for(command, arg))
            argv = build_argv(agent, command, arg)
            run = Run(agent, command, arg)
            run.on_done = on_done
            run.transcript = transcript_dir() / f"{run.id}_{agent}.jsonl"
            self.runs[run.id] = run
            _turn(run, argv, prompt_for(agent, command, arg) if agent == "claude" else None)
        return run

    def start_task(self, tool: str, on_done=None) -> Run:
        if tool not in agent_setup.INSTALLABLE:
            raise RunError(f"Unknown tool `{tool}`.")
        if not agent_setup.brew():
            raise RunError("Homebrew is not installed; install the tool another way.")
        with self.lock:
            self._admit(["install"])
            run = Run("task", "install", tool)
            run.on_done = on_done
            run.transcript = transcript_dir() / f"{run.id}_task.log"
            self.runs[run.id] = run
            _turn(run, [sys.executable, str(SCRIPTS / "agent_setup.py"), "install", tool], None)
        return run

    def reply(self, run_id: str, text: str) -> Run:
        run = self.get(run_id)
        text = (text or "").strip()
        if not text:
            raise RunError("Write a reply first.")
        if len(text) > 4000:
            raise RunError("Keep the reply under 4000 characters.")
        with self.lock:
            if run.busy:
                raise RunError("The agent is still working — answer its question in the panel, or wait.", 409)
            if not run.session or run.agent not in ("claude", "codex"):
                raise RunError("This run cannot be continued.", 409)
            self._admit(run.locks, exclude=run)
            argv = claude_argv(run.command, resume=run.session) if run.agent == "claude" \
                else codex_argv(text, resume=run.session)
            run.add({"kind": "user", "text": text, "turn": run.turn + 1})
            _turn(run, argv, text if run.agent == "claude" else None)
        return run

    def answer(self, run_id: str, ask_id: str, body: dict) -> Run:
        run = self.get(run_id)
        run.answer(ask_id, body)
        return run

    def stop(self, run_id: str) -> Run:
        run = self.get(run_id)
        stop(run)
        return run

    def stop_all(self) -> None:
        for run in self.busy():
            stop(run)


def stop(run: Run) -> None:
    if run.proc and run.proc.poll() is None:
        run.stopping = True  # the final status is set when the process has actually ended
        run.expire_all("Stopped by you")
        try:
            os.killpg(run.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        proc = run.proc

        def reap():
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        threading.Thread(target=reap, daemon=True).start()


# ---------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect", help="Which agent CLIs are installed and runnable.")
    sub.add_parser("commands", help="The commands the UI may start.")
    r = sub.add_parser("run", help="Run one command and print its steps (questions are declined).")
    r.add_argument("agent", choices=["claude", "codex"])
    r.add_argument("command")
    r.add_argument("arg", nargs="?")
    args = parser.parse_args()
    if args.cmd == "detect":
        print(json.dumps(detect(), indent=2))
        return 0
    if args.cmd == "commands":
        print(json.dumps({"commands": COMMANDS, "not_from_ui": NOT_FROM_UI}, indent=2))
        return 0
    manager = Manager()
    try:
        done = threading.Event()
        run = manager.start(args.agent, args.command, args.arg, on_done=lambda _r: done.set())
    except RunError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    seen = 0
    while not (done.is_set() and seen >= len(run.events)):
        for ev in run.since(seen):
            seen += 1
            if ev["kind"] == "tool":
                print(f"[{ev['ts']:>6}s] {ev['verb']} {ev['target'][:120]}")
            elif ev["kind"] in ("text", "error"):
                print(f"[{ev['ts']:>6}s] {ev['kind']}: {ev['text'][:200]}")
            elif ev["kind"] == "ask":  # no one to answer in a terminal: decline
                a = ev["ask"]
                print(f"[{ev['ts']:>6}s] asked: {a.get('title') or a['questions'][0]['question']} — declined")
                body = {"decline": True} if a["kind"] == "question" else {"decision": "deny"}
                try:
                    run.answer(a["id"], body)
                except RunError:
                    pass
        time.sleep(0.3)
    print(json.dumps({k: v for k, v in run.meta().items() if k != "summary"}, indent=2))
    return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
