"""Agent runs from the UI: only whitelisted commands start, the agent CLIs
get the safety flags, both event streams normalise into steps, a run started
over HTTP streams, asks the user (questions, permissions) and waits for the
answer, takes a reply in the same session, runs side by side with runs that
touch other things — and the Settings page checks and sets up what runs need.

The real CLIs are never called: fake `claude` / `codex` executables speak the
protocols the real ones do (synthetic content), selected through
$JOBISSIMO_AGENT_CLAUDE / $JOBISSIMO_AGENT_CODEX. Settings writes go to temp
files ($JOBISSIMO_CLAUDE_LOCAL_SETTINGS, $CODEX_HOME), never the real ones.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from helpers import REPO, make_workspace, run_script
from test_ui import UiServerBase

sys.path.insert(0, str(REPO / "scripts"))
import agent_runner  # noqa: E402
import agent_setup  # noqa: E402

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("9.9.9 (Claude Code)"); sys.exit(0)
with open(os.environ["FAKE_AGENT_ARGV"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
def out(o): print(json.dumps(o), flush=True)
def log(o):
    with open(os.environ["FAKE_AGENT_ARGV"] + ".answers", "a") as fh:
        fh.write(json.dumps(o) + "\n")
SID = args[args.index("--resume") + 1] if "--resume" in args else "11111111-2222-3333-4444-555555555555"
n = [0]
def ask(tool, inp, suggestions=None):
    n[0] += 1
    rid = f"req-{n[0]}"
    out({"type": "control_request", "request_id": rid, "request": {"subtype": "can_use_tool", "tool_name": tool,
         "input": inp, "permission_suggestions": suggestions or [], "tool_use_id": f"toolu_ask{n[0]}"}})
    while True:
        o = json.loads(sys.stdin.readline())
        if o.get("type") == "control_response" and o["response"]["request_id"] == rid:
            log({"tool": tool, "response": o["response"]["response"]})
            return o["response"]["response"]
def scenario(text):
    if "slow" in text:
        time.sleep(60)
    out({"type": "system", "subtype": "init", "session_id": SID, "model": "fake-model"})
    if "--resume" in args:
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "You said: " + text}]}})
        out({"type": "result", "subtype": "success", "is_error": False, "result": "Continued: " + text,
             "total_cost_usd": 0.02, "session_id": SID})
        return
    if text.startswith("/prepare"):
        jid = text.split()[1] if len(text.split()) > 1 else "sample002"
        d = os.path.join(os.environ["JOBISSIMO_HOME"], "applications", f"2030-01-10_{jid}_co_product-manager")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "cv_draft.md"), "w").write("# CV\n")
        out({"type": "result", "subtype": "success", "is_error": False, "result": "Prepared " + jid,
             "total_cost_usd": 0.01, "session_id": SID})
        return
    if "ask" in text:
        r = ask("AskUserQuestion", {"questions": [{"question": "Fix, bypass or halt?", "header": "Audit",
                "multiSelect": False, "options": [{"label": "Fix", "description": "regenerate"},
                                                  {"label": "Halt", "description": "stop this job"}]}]})
        picked = r.get("updatedInput", {}).get("answers", {}).get("Fix, bypass or halt?", "none")
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Picked " + picked}]}})
        ask("WebFetch", {"url": "https://example.com/job/1", "prompt": "open?"},
            [{"type": "addRules", "destination": "localSettings", "behavior": "allow",
              "rules": [{"toolName": "WebFetch", "ruleContent": "domain:example.com"}]}])
        ask("Bash", {"command": "python3 scripts/agent_setup.py permission web_pages any"})
        out({"type": "result", "subtype": "success", "is_error": False, "result": "Asked and done.",
             "total_cost_usd": 0.01, "session_id": SID})
        return
    out({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Read the dashboard first."}]}})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
         "input": {"command": "python3 scripts/db.py dashboard"}}]}})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1",
         "content": "# Pipeline Dashboard\n100 jobs tracked", "is_error": False}]}})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_2", "name": "Read",
         "input": {"file_path": os.environ.get("JOBISSIMO_HOME", "") + "/knowledge/master_experience.md"}}]}})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_2",
         "content": [{"type": "text", "text": "denied"}], "is_error": True}]}})
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Dashboard: 100 jobs tracked."}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1200, "num_turns": 2,
         "total_cost_usd": 0.01, "result": "Dashboard: 100 jobs tracked.\nView: dashboard", "session_id": SID})
for line in sys.stdin:
    o = json.loads(line)
    if o.get("type") == "control_request":
        sub = o["request"]["subtype"]
        if sub == "initialize":
            body = {"account": {"email": "sam@example.com", "subscriptionType": "Fake Plan"}, "models": [{"value": "default"}]}
        elif sub == "mcp_status":
            body = {"mcpServers": [{"name": "claude-in-chrome", "status": "connected"},
                                   {"name": "claude.ai Gmail", "status": "connected"}]}
        else:
            body = {}
        out({"type": "control_response", "response": {"subtype": "success", "request_id": o["request_id"], "response": body}})
    elif o.get("type") == "user":
        scenario(o["message"]["content"])
'''

FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("codex-cli 9.9.9"); sys.exit(0)
if args[:2] == ["login", "status"]:
    print("Logged in using a fake account"); sys.exit(0)
with open(os.environ["FAKE_AGENT_ARGV"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
def out(o): print(json.dumps(o), flush=True)
resume = "resume" in args
out({"type": "thread.started", "thread_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"})
out({"type": "turn.started"})
if resume:
    out({"type": "item.completed", "item": {"id": "item_9", "type": "agent_message", "text": "Resumed: " + args[-1]}})
else:
    out({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Using the dashboard skill."}})
    out({"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": "/bin/zsh -lc 'python3 scripts/db.py dashboard'", "status": "in_progress"}})
    out({"type": "item.completed", "item": {"id": "item_1", "type": "command_execution", "command": "/bin/zsh -lc 'python3 scripts/db.py dashboard'", "aggregated_output": "# Pipeline Dashboard", "exit_code": 0, "status": "completed"}})
    out({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "Dashboard summary."}})
out({"type": "turn.completed", "usage": {"input_tokens": 1000, "output_tokens": 100}})
'''


def install_fakes(env: dict, root: Path) -> None:
    for name, body in (("claude", FAKE_CLAUDE), ("codex", FAKE_CODEX)):
        path = root / f"fake_{name}"
        path.write_text(body.replace("#!/usr/bin/env python3", f"#!{sys.executable}"), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        env[f"JOBISSIMO_AGENT_{name.upper()}"] = str(path)
    env["FAKE_AGENT_ARGV"] = str(root / "argv.jsonl")
    env["JOBISSIMO_CLAUDE_LOCAL_SETTINGS"] = str(root / "settings.local.json")
    env["CODEX_HOME"] = str(root / "codex_home")
    opener = root / "fake_open"
    opener.write_text(f"#!/bin/sh\necho \"$1\" >> {root / 'argv.jsonl'}.opened\n")
    opener.chmod(0o755)
    env["JOBISSIMO_OPEN_CMD"] = str(opener)


def argv_log(env: dict) -> list:
    p = Path(env["FAKE_AGENT_ARGV"])
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class TestRunnerUnits(unittest.TestCase):
    def test_only_whitelisted_commands(self):
        for cmd, arg, msg in (("sync", None, "cannot be started"), ("apply", None, "needs"),
                              ("apply", "a;b", "not job ids"), ("apply", " ".join(f"j{i}" for i in range(11)), "at most"),
                              ("setup", "--stage x; rm", "takes --resume"),
                              ("rm", None, "Unknown command"), ("prepare", "../etc", "not a job id"),
                              ("track", None, "needs a message"), ("dashboard", "x", "takes no argument"),
                              ("enrich", "x; rm", "takes a number")):
            with self.assertRaises(agent_runner.RunError) as ctx:
                agent_runner.validate(cmd, arg)
            self.assertIn(msg, str(ctx.exception))
        self.assertEqual(agent_runner.validate("track", "Acme  rejected\nme"), "Acme rejected me")
        self.assertEqual(agent_runner.validate("enrich", "metrics"), "metrics")
        self.assertEqual(agent_runner.validate("setup", "--resume"), "--resume")
        self.assertEqual(agent_runner.validate("apply", "a1, a2 a1"), "a1 a2")
        self.assertEqual(agent_runner.locks_for("apply", "a1 a2"), ["browser", "apply:a1", "apply:a2"])
        self.assertIsNone(agent_runner.validate("setup", None))

    def test_argv_carries_the_safety_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_workspace(Path(tmp), with_apps=False)
            install_fakes(env, Path(tmp))
            old = dict(os.environ)
            os.environ.update(env)
            try:
                c = agent_runner.build_argv("claude", "prepare", "sample001")
                cr = agent_runner.claude_argv("prepare", resume="sess-1")
                x = agent_runner.build_argv("codex", "prepare", "sample001")
                xr = agent_runner.codex_argv("go on", resume="thread-1")
                ws = env["JOBISSIMO_HOME"]
            finally:
                os.environ.clear()
                os.environ.update(old)
        self.assertEqual(c[1:6], ["-p", "--input-format", "stream-json", "--output-format", "stream-json"])
        self.assertEqual(c[c.index("--permission-prompt-tool") + 1], "stdio")
        self.assertEqual(c[c.index("--permission-mode") + 1], "default")
        self.assertIn(f"Edit(/{ws}/**)", c)       # edits without asking: the workspace only
        self.assertNotIn("Edit", c)
        self.assertNotIn("acceptEdits", c)
        self.assertIn("--append-system-prompt", c)
        self.assertIn(ws, c[c.index("--append-system-prompt") + 1])
        self.assertEqual(cr[cr.index("--resume") + 1], "sess-1")
        self.assertEqual(x[1:3], ["exec", "--json"])
        self.assertEqual(x[x.index("--sandbox") + 1], "workspace-write")
        self.assertTrue(x[-1].startswith("$prepare sample001"))
        self.assertEqual(xr[1:4], ["exec", "resume", "--json"])
        self.assertEqual(xr[-2:], ["thread-1", "go on"])
        for argv in (c, cr, x, xr):
            self.assertFalse(any("dangerously" in a or a == "bypassPermissions" for a in argv))

    def test_locks(self):
        L = agent_runner.locks_for
        self.assertFalse(agent_runner.clash(L("prepare", "a"), L("prepare", "b")))
        self.assertTrue(agent_runner.clash(L("prepare", None), L("prepare", "b")))
        self.assertTrue(agent_runner.clash(L("cycle", None), L("hunt", None)))
        self.assertTrue(agent_runner.clash(L("hunt", None), L("refresh", None)))  # one browser
        self.assertFalse(agent_runner.clash(L("doctor", None), L("cycle", None)))
        self.assertFalse(agent_runner.clash(L("track", "x"), L("prepare", None)))

    def test_protected_requests_are_refused(self):
        P = agent_runner.protected
        self.assertTrue(P("Bash", {"command": "python3 scripts/agent_setup.py permission web_pages any"}))
        self.assertTrue(P("Bash", {"command": "claude -p hello"}))
        self.assertTrue(P("Bash", {"command": "python3 scripts/ui.py --no-open"}))
        self.assertTrue(P("Bash", {"command": "python3 scripts/launcher.py login on"}))
        self.assertTrue(P("Write", {"file_path": "/x/repo/.claude/settings.local.json"}))
        self.assertIsNone(P("Bash", {"command": "curl -s https://example.com"}))
        self.assertIsNone(P("WebFetch", {"url": "https://example.com"}))

    def test_normalisers(self):
        tool = agent_runner.normalize_claude({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "python3 scripts/db.py get x"}}]}})
        self.assertEqual(tool[0]["verb"], "Ran")
        q = agent_runner.normalize_claude({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "q", "name": "AskUserQuestion", "input": {"questions": []}}]}})
        self.assertEqual(q, [])  # shown as a question card, not a step
        res = agent_runner.normalize_claude({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "x" * 10000, "is_error": True}]}})
        self.assertEqual(res[0]["status"], "error")
        self.assertLess(len(res[0]["output"]), 7000)
        cmd = agent_runner.normalize_codex({"type": "item.started", "item": {"id": "i", "type": "command_execution",
                                            "command": "/bin/zsh -lc 'python3 scripts/db.py dashboard'"}})
        self.assertEqual(cmd[0]["target"], "python3 scripts/db.py dashboard")

    def test_agents_cannot_launch_agents_or_grant_permissions(self):
        settings = (REPO / ".claude" / "settings.json").read_text(encoding="utf-8")
        rules = (REPO / ".codex" / "rules" / "jobissimo.rules").read_text(encoding="utf-8")
        for script in ("agent_runner.py", "agent_setup.py", "ui.py", "launcher.py"):
            self.assertNotIn(f"scripts/{script}", settings)
            self.assertNotIn(f"scripts/{script}", rules)
        self.assertIn("Bash(python3 scripts/sync.py status)", settings)  # read-only, local
        self.assertNotIn("Bash(python3 scripts/sync.py *)", settings)


class TestPermissionFile(unittest.TestCase):
    def test_round_trip_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.local.json"
            path.write_text(json.dumps({"permissions": {"allow": ["Bash(git status)", "WebFetch(domain:example.org)"],
                                                        "additionalDirectories": ["/x"]}, "other": 1}))
            old = os.environ.get("JOBISSIMO_CLAUDE_LOCAL_SETTINGS")
            os.environ["JOBISSIMO_CLAUDE_LOCAL_SETTINGS"] = str(path)
            try:
                with unittest.mock.patch.object(agent_setup, "_log"):
                    agent_setup.set_permission("web_pages", "job_sites")
                    self.assertEqual(agent_setup.current_mode("web_pages"), "job_sites")
                    agent_setup.set_permission("mail", "read")
                    self.assertEqual(agent_setup.current_mode("mail"), "read")
                    data = json.loads(path.read_text())
                    self.assertIn("Bash(git status)", data["permissions"]["allow"])
                    self.assertIn("WebFetch(domain:example.org)", data["permissions"]["allow"])  # saved by a run
                    self.assertEqual(data["permissions"]["additionalDirectories"], ["/x"])
                    self.assertEqual(data["other"], 1)
                    self.assertFalse(any("send" in r for r in data["permissions"]["allow"]))  # mail is read-only
                    agent_setup.set_permission("web_pages", "ask")
                    agent_setup.set_permission("mail", "ask")
                    allow = json.loads(path.read_text())["permissions"]["allow"]
                    self.assertEqual(allow, ["Bash(git status)"])
            finally:
                if old is None:
                    os.environ.pop("JOBISSIMO_CLAUDE_LOCAL_SETTINGS", None)
                else:
                    os.environ["JOBISSIMO_CLAUDE_LOCAL_SETTINGS"] = old


class TestUiRuns(UiServerBase):
    """The UI server with fake agents resolved through the environment."""

    @classmethod
    def setUpClass(cls):
        cls._fake_root = Path(tempfile.mkdtemp())
        cls.extra_env = {}
        install_fakes(cls.extra_env, cls._fake_root)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(cls._fake_root, ignore_errors=True)

    def poll(self, run_id, until, timeout=15):
        deadline = time.time() + timeout
        events = []
        while time.time() < deadline:
            _, _, body = self.request("GET", f"/api/runs/{run_id}?after={len(events)}", cookie=self.cookie)
            data = json.loads(body)
            events += data["events"]
            if until(data["run"]):
                return data["run"], events
            time.sleep(0.15)
        self.fail(f"run never reached the state: {data['run']}")

    def wait_for(self, run_id, timeout=15):
        return self.poll(run_id, lambda r: r["status"] not in ("running", "starting", "needs_input"), timeout)

    def test_agents_detected(self):
        _, _, body = self.request("GET", "/api/agents", cookie=self.cookie)
        data = json.loads(body)
        self.assertTrue(data["agents"]["claude"]["available"])
        self.assertTrue(data["agents"]["codex"]["available"])
        self.assertEqual(data["commands"]["apply"]["agents"], ["claude"])  # asks live, drives Chrome
        self.assertIn("enrich", data["commands"])

    def test_claude_run_streams_and_logs(self):
        status, out = self.post("/api/runs", {"agent": "claude", "command": "dashboard"})
        self.assertEqual(status, 200, out)
        run, events = self.wait_for(out["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["session"], "11111111-2222-3333-4444-555555555555")
        self.assertAlmostEqual(run["cost_usd"], 0.01)
        self.assertTrue(run["can_reply"])
        kinds = [e["kind"] for e in events]
        for k in ("init", "thinking", "tool", "tool_result", "text", "result"):
            self.assertIn(k, kinds)
        read = next(e for e in events if e["kind"] == "tool" and e["verb"] == "Read")
        self.assertEqual(read["target"], "knowledge/master_experience.md")  # workspace-relative
        failed = next(e for e in events if e["kind"] == "tool_result" and e["id"] == "toolu_2")
        self.assertEqual(failed["status"], "error")
        home = Path(self.env["JOBISSIMO_HOME"])
        self.assertTrue(list((home / "state" / "agent_runs").glob(f"{run['id']}_claude.jsonl")))
        self.assertEqual((home / "state" / "agent_runs" / ".gitignore").read_text(), "*\n")
        ev = run_script("db.py", "last-event", "--action", "agent_run_finished", env=self.env).stdout
        self.assertIn('"status": "succeeded"', ev)

        # a reply continues the same session
        status, out = self.post(f"/api/runs/{run['id']}/reply", {"text": "Show only the ready ones"})
        self.assertEqual(status, 200, out)
        run2, events2 = self.wait_for(run["id"])
        self.assertEqual(run2["status"], "succeeded", run2)
        self.assertEqual(run2["turn"], 2)
        self.assertIn("Continued: Show only the ready ones", run2["summary"])
        argv = argv_log(self.env)[-1]
        self.assertEqual(argv[argv.index("--resume") + 1], run["session"])
        self.assertIn({"kind": "user", "text": "Show only the ready ones"},
                      [{k: e[k] for k in ("kind", "text")} for e in events2 if e["kind"] == "user"])

    def test_questions_and_permissions_wait_for_the_user(self):
        status, out = self.post("/api/runs", {"agent": "claude", "command": "track", "arg": "ask about Acme"})
        self.assertEqual(status, 200, out)
        rid = out["run"]["id"]
        run, _ = self.poll(rid, lambda r: r["status"] == "needs_input")
        q = run["asks"][0]
        self.assertEqual(q["kind"], "question")
        self.assertEqual(q["questions"][0]["options"][0]["label"], "Fix")
        # an answer that does not cover the question is refused
        self.assertEqual(self.post(f"/api/runs/{rid}/asks/{q['id']}", {"answers": {}})[0], 400)
        status, out = self.post(f"/api/runs/{rid}/asks/{q['id']}", {"answers": {"Fix, bypass or halt?": "Halt"}})
        self.assertEqual(status, 200, out)
        run, _ = self.poll(rid, lambda r: r["asks"] and r["asks"][0]["kind"] == "permission")
        p = run["asks"][0]
        self.assertEqual(p["title"], "Read a web page")
        self.assertEqual(p["rules"], ["WebFetch(domain:example.com)"])
        self.assertEqual(self.post(f"/api/runs/{rid}/asks/{p['id']}", {"decision": "always"})[0], 200)
        self.assertEqual(self.post(f"/api/runs/{rid}/asks/{p['id']}", {"decision": "deny"})[0], 409)  # once only
        run, events = self.wait_for(rid)
        self.assertEqual(run["status"], "succeeded", run)
        answers = [json.loads(x) for x in Path(self.env["FAKE_AGENT_ARGV"] + ".answers").read_text().splitlines()]
        self.assertEqual(answers[0]["response"]["updatedInput"]["answers"], {"Fix, bypass or halt?": "Halt"})
        self.assertEqual(answers[1]["response"]["updatedPermissions"][0]["rules"][0]["ruleContent"], "domain:example.com")
        # the agent asking to change its own permissions is refused without asking anyone
        self.assertEqual(answers[2]["response"]["behavior"], "deny")
        self.assertTrue(any(e["kind"] == "error" and "may not" in e["text"] for e in events))
        self.assertIn("Picked Halt", [e.get("text") for e in events if e["kind"] == "text"])
        done = [e["outcome"] for e in events if e["kind"] == "ask_done"]
        self.assertEqual(done, ["answered", "allowed"])

    def test_prepare_links_its_folder_and_it_opens(self):
        status, out = self.post("/api/runs", {"agent": "claude", "command": "prepare", "arg": "sample002"})
        self.assertEqual(status, 200, out)
        run, _ = self.wait_for(out["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["folders"], [{"folder": "2030-01-10_sample002_co_product-manager", "job_id": "sample002"}])
        status, res = self.post("/api/folders/open", {"folder": run["folders"][0]["folder"]})
        self.assertEqual(status, 200, res)
        opened = Path(self.env["FAKE_AGENT_ARGV"] + ".opened").read_text()
        self.assertTrue(opened.strip().endswith("applications/2030-01-10_sample002_co_product-manager"))
        # the job's own folder (sample001 has one), and nothing outside applications/
        self.assertEqual(self.post("/api/folders/open", {"job_id": "sample001"})[0], 200)
        self.assertEqual(self.post("/api/folders/open", {"job_id": "sample003"})[0], 400)  # not prepared
        self.assertEqual(self.post("/api/folders/open", {"folder": "../knowledge"})[0], 400)
        self.assertEqual(self.post("/api/folders/open", {"folder": "nope"})[0], 400)

    def test_codex_run_and_reply(self):
        status, out = self.post("/api/runs", {"agent": "codex", "command": "dashboard"})
        self.assertEqual(status, 200, out)
        run, events = self.wait_for(out["run"]["id"])
        self.assertEqual(run["status"], "succeeded", run)
        self.assertEqual(run["summary"], "Dashboard summary.")
        self.assertEqual(run["tokens"]["input_tokens"], 1000)
        self.assertIn("python3 scripts/db.py dashboard", [e.get("target") for e in events])
        status, out = self.post(f"/api/runs/{run['id']}/reply", {"text": "Halt it"})
        self.assertEqual(status, 200, out)
        run, _ = self.wait_for(run["id"])
        self.assertEqual(run["summary"], "Resumed: Halt it")
        argv = argv_log(self.env)[-1]
        self.assertEqual(argv[:3], ["exec", "resume", "--json"])
        self.assertEqual(argv[-2], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def test_refusals(self):
        for body, code in (({"agent": "codex", "command": "apply", "arg": "sample001"}, 400),
                           ({"agent": "claude", "command": "sync"}, 400),
                           ({"agent": "claude", "command": "prepare", "arg": "x; rm -rf /"}, 400),
                           ({"agent": "nope", "command": "dashboard"}, 400)):
            status, out = self.post("/api/runs", body)
            self.assertEqual(status, code, out)
        self.assertEqual(self.post("/api/runs", {"agent": "claude", "command": "dashboard"}, csrf="bad")[0], 403)
        self.assertEqual(self.post("/api/runs/ui_20300101_000000_x_abcd/reply", {"text": "hi"})[0], 404)

    def test_parallel_runs_and_stop(self):
        status, out = self.post("/api/runs", {"agent": "claude", "command": "track", "arg": "slow update"})
        self.assertEqual(status, 200, out)
        rid = out["run"]["id"]
        # a run that touches other things goes side by side…
        status, other = self.post("/api/runs", {"agent": "codex", "command": "dashboard"})
        self.assertEqual(status, 200, other)
        # …one that touches the same things waits
        status, again = self.post("/api/runs", {"agent": "codex", "command": "track", "arg": "another"})
        self.assertEqual(status, 409, again)
        self.assertIn("same things", again["error"])
        self.assertEqual(self.wait_for(other["run"]["id"])[0]["status"], "succeeded")
        t0 = time.time()
        self.assertEqual(self.post(f"/api/runs/{rid}/stop", {})[0], 200)
        run, _ = self.wait_for(rid, timeout=10)
        self.assertEqual(run["status"], "stopped")
        self.assertLess(time.time() - t0, 8)
        ev = run_script("db.py", "last-event", "--action", "agent_run_finished", env=self.env).stdout
        self.assertIn('"status": "stopped"', ev)

    def test_settings_check_and_setup(self):
        _, _, body = self.request("GET", "/api/settings?refresh=1", cookie=self.cookie)
        s = json.loads(body)
        self.assertTrue(s["agents"]["claude"]["signed_in"])
        self.assertEqual(s["agents"]["claude"]["connectors"]["claude-in-chrome"], "connected")
        self.assertTrue(s["agents"]["codex"]["signed_in"])
        self.assertFalse(s["agents"]["codex"]["trusted"])
        self.assertEqual(s["permissions"]["web_pages"]["mode"], "ask")
        self.assertIn({"kind": "codex_trust"}, [r["fix"] for r in s["recommendations"]])
        self.assertTrue(any(t["id"] == "pandoc" for t in s["tools"]))

        self.assertEqual(self.post("/api/settings/permission", {"capability": "web_pages", "mode": "job_sites"})[0], 200)
        self.assertEqual(self.post("/api/settings/permission", {"capability": "web_pages", "mode": "nope"})[0], 400)
        self.assertEqual(self.post("/api/settings/pref", {"key": "runs.max_parallel", "value": 2})[0], 200)
        self.assertEqual(self.post("/api/settings/pref", {"key": "runs.max_parallel", "value": 9})[0], 400)
        self.assertEqual(self.post("/api/settings/pref", {"key": "codex.network", "value": True})[0], 200)
        self.assertEqual(self.post("/api/settings/codex-trust", {})[0], 200)
        _, _, body = self.request("GET", "/api/settings?refresh=1", cookie=self.cookie)
        s = json.loads(body)
        self.assertEqual(s["permissions"]["web_pages"]["mode"], "job_sites")
        self.assertEqual(s["prefs"]["runs.max_parallel"], 2)
        self.assertTrue(s["prefs"]["codex.network"])
        self.assertTrue(s["agents"]["codex"]["trusted"])
        allow = json.loads(Path(self.env["JOBISSIMO_CLAUDE_LOCAL_SETTINGS"]).read_text())["permissions"]["allow"]
        self.assertIn("WebFetch(domain:*.ashbyhq.com)", allow)
        self.assertIn("trust_level = \"trusted\"", (Path(self.env["CODEX_HOME"]) / "config.toml").read_text())
        ev = run_script("db.py", "last-event", "--action", "agent_permission_changed", env=self.env).stdout
        self.assertIn('"capability": "web_pages"', ev)
        # the network preference reaches the next Codex run
        status, out = self.post("/api/runs", {"agent": "codex", "command": "doctor"})
        self.assertEqual(status, 200, out)
        self.wait_for(out["run"]["id"])
        self.assertIn("sandbox_workspace_write.network_access=true", argv_log(self.env)[-1])
        self.post("/api/settings/pref", {"key": "codex.network", "value": False})
        self.post("/api/settings/pref", {"key": "runs.max_parallel", "value": 3})


if __name__ == "__main__":
    unittest.main()
