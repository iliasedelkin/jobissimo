"""Opening Jobissimo without a terminal: the generated app (macOS) and
app-menu entry (Linux), start-at-login, reusing a running UI, Quit and the
idle stop, document upload for /setup, the onboarding view, and install.sh.

Nothing here touches the real ~/Applications, LaunchAgents or autostart
folders: $JOBISSIMO_APPS_DIR / $JOBISSIMO_LOGIN_DIR point into temp dirs, and
$JOBISSIMO_LAUNCHER_OS picks the platform being generated for.
"""
from __future__ import annotations

import http.client
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import REPO, make_workspace, run_script
from test_ui import UiServerBase


def launcher(env, *args, timeout=60):
    return subprocess.run([sys.executable, str(REPO / "scripts" / "launcher.py"), *args],
                          capture_output=True, text=True, env=env, timeout=timeout, cwd=REPO)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = make_workspace(root, with_apps=False)
        self.env.pop("JOBISSIMO_CONFIG", None)  # the workspace's own config/ — like a real install
        self.env["JOBISSIMO_APPS_DIR"] = str(root / "apps")
        self.env["JOBISSIMO_LOGIN_DIR"] = str(root / "login")
        self.home = Path(self.env["JOBISSIMO_HOME"])

    def tearDown(self):
        launcher(self.env, "stop")
        self.tmp.cleanup()


class TestAppAndLogin(Base):
    def test_mac_app_bundle(self):
        env = dict(self.env, JOBISSIMO_LAUNCHER_OS="mac")
        res = launcher(env, "install-app")
        self.assertEqual(res.returncode, 0, res.stderr)
        app = Path(env["JOBISSIMO_APPS_DIR"]) / "Jobissimo.app"
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        self.assertEqual(info["CFBundleExecutable"], "Jobissimo")
        stub = app / "Contents" / "MacOS" / "Jobissimo"
        self.assertTrue(os.access(stub, os.X_OK))
        text = stub.read_text()
        self.assertIn("launcher.py", text)
        self.assertTrue(text.rstrip().endswith(" open"))
        self.assertIn(f"JOBISSIMO_HOME={self.home}", text)        # set explicitly: baked in
        self.assertNotIn("JOBISSIMO_CONFIG", text)                # not set: the pointer decides
        self.assertTrue(json.loads(launcher(env, "status").stdout)["app"]["installed"])
        self.assertEqual(launcher(env, "uninstall-app").stdout.strip(), "Removed.")
        self.assertFalse(app.exists())

    def test_linux_menu_entry(self):
        env = dict(self.env, JOBISSIMO_LAUNCHER_OS="linux")
        self.assertEqual(launcher(env, "install-app").returncode, 0)
        desktop = Path(env["JOBISSIMO_APPS_DIR"]) / "jobissimo.desktop"
        text = desktop.read_text()
        self.assertIn("Name=Jobissimo", text)
        self.assertIn("Terminal=false", text)
        exec_line = next(l for l in text.splitlines() if l.startswith("Exec="))
        stub = Path(exec_line[5:].strip("'"))
        self.assertTrue(os.access(stub, os.X_OK))
        launcher(env, "uninstall-app")
        self.assertFalse(desktop.exists())
        self.assertFalse(stub.exists())

    def test_login_items(self):
        for system, name in (("mac", "io.github.jobissimo.ui.plist"), ("linux", "jobissimo.desktop")):
            env = dict(self.env, JOBISSIMO_LAUNCHER_OS=system)
            self.assertEqual(launcher(env, "login", "on").returncode, 0)
            item = Path(env["JOBISSIMO_LOGIN_DIR"]) / name
            self.assertTrue(item.exists())
            if system == "mac":
                plist = plistlib.loads(item.read_bytes())
                self.assertTrue(plist["RunAtLoad"])
                self.assertIn("jobissimo-serve", plist["ProgramArguments"][1])
            self.assertTrue(json.loads(launcher(env, "status").stdout)["login"]["on"])
            launcher(env, "login", "off")
            self.assertFalse(item.exists())


class TestOpenReuseStop(Base):
    def test_open_reuses_then_stops(self):
        first = launcher(self.env, "open", "--no-browser")
        self.assertEqual(first.returncode, 0, first.stderr)
        url = first.stdout.strip()
        self.assertRegex(url, r"^http://127\.0\.0\.1:\d+/\?t=\S+$")
        state = self.home / "config" / "local" / "ui_server.json"
        self.assertEqual(oct(state.stat().st_mode & 0o777), "0o600")
        self.assertEqual(launcher(self.env, "open", "--no-browser").stdout.strip(), url)  # reused
        reuse = run_script("ui.py", "--no-open", env=self.env)               # the terminal reuses it too
        self.assertIn("already running", reuse.stdout)
        self.assertTrue(json.loads(launcher(self.env, "status").stdout)["running"])
        self.assertEqual(launcher(self.env, "stop").stdout.strip(), "Stopped.")
        self.assertFalse(json.loads(launcher(self.env, "status").stdout)["running"])
        self.assertFalse(state.exists())

    def test_idle_stop(self):
        out = launcher(self.env, "open", "--no-browser", "--idle-exit", "0.05")  # 3 seconds
        self.assertEqual(out.returncode, 0, out.stderr)
        deadline = time.time() + 20
        while time.time() < deadline and json.loads(launcher(self.env, "status").stdout)["running"]:
            time.sleep(0.5)
        self.assertFalse(json.loads(launcher(self.env, "status").stdout)["running"])
        self.assertIn("stopping", (self.home / "config" / "local" / "ui.log").read_text())


class TestQuit(UiServerBase):
    """Its own server, because the test quits it."""

    def test_health_quit(self):
        status, _, body = self.request("GET", "/api/health")   # no sign-in needed, nothing revealed
        self.assertEqual((status, json.loads(body)), (200, {"app": "jobissimo"}))
        self.assertEqual(self.request("POST", "/api/quit-local", body={})[0], 403)
        self.assertEqual(self.post("/api/quit", {}, csrf="bad")[0], 403)
        status, out = self.post("/api/quit", {})
        self.assertEqual(status, 200, out)
        self.proc.wait(10)
        self.assertEqual(self.proc.returncode, 0)


class TestUploadAndOnboarding(UiServerBase):
    def upload(self, name, data, csrf=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": self.host, "Cookie": self.cookie, "Content-Type": "application/octet-stream"}
        if csrf:
            headers["X-CSRF-Token"] = self.csrf
        conn.request("POST", f"/api/intake?name={name}", body=data, headers=headers)
        res = conn.getresponse()
        out = res.status, json.loads(res.read())
        conn.close()
        return out

    def test_upload_feeds_intake(self):
        status, out = self.upload("cv_2030.md", b"# Sam Rivera\n\nProduct manager, 2030.\n")
        self.assertEqual(status, 200, out)
        self.assertIn("cv_2030.md", [d["name"] for d in out["documents"]])
        home = Path(self.env["JOBISSIMO_HOME"])
        self.assertTrue((home / "_intake" / "originals" / "cv_2030.md").exists())
        self.assertEqual(self.upload("../../evil.sh", b"x")[0], 400)
        self.assertEqual(self.upload("cv.md", b"x", csrf=False)[0], 403)
        self.assertFalse((home.parent / "evil.sh").exists())

    def test_onboarding_view(self):
        _, _, body = self.request("GET", "/api/onboarding", cookie=self.cookie)
        o = json.loads(body)
        self.assertEqual([s["id"] for s in o["setup"]["stages"]][:2], ["preflight", "intake"])
        self.assertFalse(o["setup"]["started"])
        self.assertFalse(o["complete"])
        self.assertIn("app", o["launcher"])
        _, _, body = self.request("GET", "/api/session", cookie=self.cookie)
        self.assertFalse(json.loads(body)["onboarding_complete"])


class TestInstallScript(unittest.TestCase):
    def test_install_and_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Jobissimo"
            env = dict(os.environ, JOBISSIMO_DIR=str(root), JOBISSIMO_SOURCE_DIR=str(REPO), HOME=tmp)
            for k in ("JOBISSIMO_HOME", "JOBISSIMO_CONFIG"):
                env.pop(k, None)
            for _ in range(2):  # the second run is an update
                res = subprocess.run(["sh", str(REPO / "install.sh"), "--no-open", "--no-app"],
                                     capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            engine, ws = root / "engine", root / "workspace"
            self.assertTrue((engine / "scripts" / "ui.py").exists())
            self.assertFalse((engine / "profile").exists())
            self.assertEqual((engine / ".jobissimo").read_text().strip(), str(ws))
            self.assertTrue(ws.is_dir())
            if shutil.which("git"):
                self.assertTrue((ws / ".git").is_dir())
                self.assertIn("config/local/", (ws / ".gitignore").read_text())
            where = subprocess.run([sys.executable, str(engine / "scripts" / "paths.py")],
                                   capture_output=True, text=True, env=env, cwd=engine)
            self.assertIn(".jobissimo pointer", where.stdout)
        self.assertNotEqual(subprocess.run(["sh", str(REPO / "install.sh"), "--bogus"],
                                           capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
