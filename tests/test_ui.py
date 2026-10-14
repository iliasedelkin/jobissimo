"""The read model agrees with db.py, and the local UI server enforces its
security model and routes writes through the deterministic CLIs."""
from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import EN_APP, FIXTURE_CONFIG, REPO, make_workspace, run_script


def seed(env):
    """A tiny synthetic pipeline: one prepared+applied job with a round, one
    shortlisted, one ready."""
    def db(*a):
        r = run_script("db.py", *a, env=env)
        assert r.returncode == 0, r.stderr
    for jid, status in (("sample001", "ready"), ("sample002", "shortlisted"), ("sample003", "ready")):
        db("add-job", "--job-id", jid, "--source", "sample", "--company", f"Co {jid}",
           "--title", "Product Manager", "--url", f"https://example.com/{jid}",
           "--date-found", "2030-01-10", "--jd-path", f"jd_texts/{jid}.md", "--status", status)
    db("set-field", "--job-id", "sample001", "application_folder", f"applications/{EN_APP}")
    db("set-status", "--job-id", "sample001", "--status", "applied", "--date", "2030-01-12")
    db("stage", "add", "--job-id", "sample001", "--kind", "hr", "--date", "2030-01-20")


class TestReadModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))
        seed(self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def view(self, *args):
        res = run_script("readmodel.py", *args, env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_overview_matches_dashboard(self):
        o = self.view("overview")
        dash = run_script("db.py", "dashboard", env=self.env).stdout
        f = o["funnel"]
        self.assertIn(f"{f['applied']} applied → {f['responded']} responded", dash)
        self.assertEqual(o["queue"]["ready"]["count"], 1)
        self.assertEqual(o["queue"]["shortlisted"]["count"], 1)
        self.assertEqual([j["job_id"] for j in o["in_process"]], ["sample001"])

    def test_job_view_links_cv_bullets_to_knowledge(self):
        j = self.view("job", "sample001")
        self.assertEqual(j["stages"][0]["kind"], "hr")
        ids = {b["id"] for b in j["folder"]["bullets"]}
        self.assertIn("FERN-PM-001", ids)
        self.assertTrue(all(b["status"] == "verified" for b in j["folder"]["bullets"]))

    def test_every_view_renders(self):
        for v in ("overview", "jobs", "analytics", "knowledge", "gaps", "pipeline", "suggestions", "insights"):
            self.view(v)
        k = self.view("knowledge")
        used = next(b for r in k["roles"] for b in r["bullets"] if b["id"] == "FERN-PM-001")
        self.assertGreaterEqual(used["usage"]["applications"], 1)
        gaps = self.view("gaps")
        self.assertIn("analytics tooling rollout", [g["term"] for g in gaps["items"]])

    def test_read_only(self):
        db = Path(self.env["JOBISSIMO_HOME"]) / "state" / "pipeline.db"
        before = db.read_bytes()
        for v in ("overview", "analytics", "knowledge", "pipeline"):
            self.view(v)
        self.assertEqual(db.read_bytes(), before)


class UiServerBase(unittest.TestCase):
    """Starts ui.py on a seeded temp workspace; signs in. No tests of its own."""
    extra_env: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = make_workspace(Path(cls.tmp.name))
        cls.env.update(cls.extra_env)
        cfg = Path(cls.tmp.name) / "config"
        shutil.copytree(FIXTURE_CONFIG, cfg)
        cls.env["JOBISSIMO_CONFIG"] = str(cfg)
        seed(cls.env)
        cls.proc = subprocess.Popen([sys.executable, "-u", str(REPO / "scripts" / "ui.py"), "--no-open", "--port", "0"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=cls.env)
        deadline = time.time() + 10
        url = None
        while time.time() < deadline and url is None:
            line = cls.proc.stdout.readline()
            m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=(\S+)", line)
            if m:
                url = m
        assert url, "ui.py did not print its URL"
        cls.port, cls.token = int(url.group(1)), url.group(2)
        cls.host = f"127.0.0.1:{cls.port}"
        status, headers, _ = cls.request("GET", f"/?t={cls.token}")
        assert status == 303, status
        cls.cookie = headers["Set-Cookie"].split(";")[0]
        _, _, body = cls.request("GET", "/api/session", cookie=cls.cookie)
        cls.csrf = json.loads(body)["csrf"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.proc.stdout.close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, body=None, cookie=None, csrf=None, host=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{cls.port}"}
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if origin:
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        out = res.status, dict(res.getheaders()), res.read().decode()
        conn.close()
        return out

    def post(self, path, body, **kw):
        kw.setdefault("cookie", self.cookie)
        kw.setdefault("csrf", self.csrf)
        status, _, text = self.request("POST", path, body, **kw)
        return status, json.loads(text)


class TestUiServer(UiServerBase):
    def test_every_get_endpoint(self):
        for path in ("/api/overview", "/api/jobs", "/api/jobs/sample001", "/api/analytics",
                     "/api/analytics?since=2030-01-01", "/api/knowledge", "/api/gaps",
                     "/api/pipeline", "/api/insights"):
            status, _, body = self.request("GET", path, cookie=self.cookie)
            self.assertEqual(status, 200, f"{path}: {body[:200]}")
            json.loads(body)
        self.assertEqual(self.request("GET", "/api/jobs/nope", cookie=self.cookie)[0], 404)

    def test_auth_host_and_csrf(self):
        self.assertEqual(self.request("GET", "/api/overview")[0], 401)
        self.assertEqual(self.request("GET", "/api/overview", cookie="jobissimo_session=wrong")[0], 401)
        self.assertEqual(self.request("GET", "/api/overview", cookie=self.cookie, host="evil.example:80")[0], 403)
        self.assertEqual(self.request("GET", "/?t=wrong")[0], 403)
        body = {"status": "on_hold"}
        self.assertEqual(self.post("/api/jobs/sample002/status", body, csrf="bad")[0], 403)
        self.assertEqual(self.post("/api/jobs/sample002/status", body, origin="http://evil.example")[0], 403)
        self.assertEqual(self.post("/api/jobs/sample002/status", body, cookie=None)[0], 401)

    def test_static_files_are_confined(self):
        self.assertEqual(self.request("GET", "/")[0], 200)
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/../scripts/db.py")[0], 404)
        _, headers, _ = self.request("GET", "/")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_writes_go_through_db_rules(self):
        # an illegal transition is refused with db.py's own message
        status, out = self.post("/api/jobs/sample002/status", {"status": "applied"})
        self.assertEqual(status, 400)
        self.assertIn("not allowed", out["error"])
        # statuses the UI must never set
        status, out = self.post("/api/jobs/sample002/status", {"status": "discarded"})
        self.assertEqual(status, 400)
        # a legal one works and is logged
        status, out = self.post("/api/jobs/sample003/status", {"status": "applied", "date": "2030-01-15",
                                                               "applied_via": "employer_site"})
        self.assertEqual(status, 200, out)
        _, _, body = self.request("GET", "/api/jobs/sample003", cookie=self.cookie)
        self.assertEqual(json.loads(body)["status"], "applied")

    def test_knowledge_and_config_writes(self):
        status, out = self.post("/api/knowledge/propose", {"op": "add_phrasing", "target": "FERN-PM-003",
                                                           "payload": {"phrasing": "Built a triage loop."},
                                                           "accept": True})
        self.assertEqual(status, 200, out)
        self.assertIn("accepted", out["message"])
        status, out = self.post("/api/config", {"file": "pipeline", "key": "thresholds.ready_wip_cap",
                                                "value": 6})
        self.assertEqual(status, 400)  # reason required
        status, out = self.post("/api/config", {"file": "pipeline", "key": "thresholds.ready_wip_cap",
                                                "value": 6, "reason": "too many unsent"})
        self.assertEqual(status, 200, out)
        _, _, body = self.request("GET", "/api/pipeline", cookie=self.cookie)
        hist = json.loads(body)["history"]
        self.assertEqual(hist[0]["key"], "thresholds.ready_wip_cap")
        self.assertEqual(hist[0]["reason"], "too many unsent")


if __name__ == "__main__":
    unittest.main()
