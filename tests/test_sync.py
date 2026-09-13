"""sync.py + db.py CSV round-trip, path resolution, and the push gates."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, make_workspace, run_script

sys.path.insert(0, str(REPO / "scripts"))
import paths  # noqa: E402
import sync   # noqa: E402


def add(env, job_id, company="Acme", title="Widget Lead", status="found", url=None):
    return run_script(
        "db.py", "add-job", "--job-id", job_id, "--source", "sample",
        "--company", company, "--title", title,
        "--url", url or f"https://example.com/{job_id}",
        "--date-found", "2026-01-10", "--jd-path", f"jd_texts/{job_id}.md",
        "--status", status, env=env)


class TestCsvRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)
        self.home = Path(self.tmp.name) / "profile"
        self.backup = self.home / "state" / "backup"
        # Seed jobs, an event, and an id reservation so all four tables + the
        # events AUTOINCREMENT sequence are exercised.
        add(self.env, "sample001")
        add(self.env, "sample002", company="Beta", title="PM")
        run_script("db.py", "next-id", "sample", env=self.env)
        run_script("db.py", "log", "--run-id", "r1", "--command", "hunt",
                   "--action", "job_added", "--job-id", "sample001", env=self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def _export(self):
        return run_script("db.py", "export-csv", env=self.env)

    def test_round_trip_byte_identical(self):
        self.assertEqual(self._export().returncode, 0)
        first = {f.name: f.read_bytes() for f in self.backup.glob("*.csv")}
        self.assertEqual(set(first), {"jobs.csv", "events.csv",
                                      "id_reservations.csv", "meta.csv"})
        seq_before = self._events_seq()

        # import into the existing DB, then export again
        imp = run_script("db.py", "import-csv", env=self.env)
        self.assertEqual(imp.returncode, 0, imp.stderr)
        self.assertIn("Moved existing database aside", imp.stdout)
        self.assertEqual(self._export().returncode, 0)
        second = {f.name: f.read_bytes() for f in self.backup.glob("*.csv")}

        for name in first:
            self.assertEqual(first[name], second[name], f"{name} not byte-identical")
        self.assertEqual(seq_before, self._events_seq(),
                         "events AUTOINCREMENT sequence not preserved")
        self.assertNotEqual(seq_before, None)

    def test_import_moves_existing_db_aside(self):
        self._export()
        run_script("db.py", "import-csv", env=self.env)
        baks = list((self.home / "state").glob("pipeline.db.bak.*"))
        self.assertTrue(baks, "existing DB was not moved aside")

    def test_verify_csv_detects_alteration(self):
        self._export()
        ok = run_script("db.py", "verify-csv", env=self.env)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        # mutate a row behind the CSVs' back
        run_script("db.py", "set-field", "--job-id", "sample001",
                   "notes", "changed", env=self.env)
        bad = run_script("db.py", "verify-csv", env=self.env)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("MISMATCH", bad.stderr + bad.stdout)

    def _events_seq(self):
        conn = sqlite3.connect(self.home / "state" / "pipeline.db")
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        conn.close()
        return row[0] if row else None


class TestPathResolution(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._pointer = paths.POINTER_FILE
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        paths.POINTER_FILE = self._pointer
        self.tmp.cleanup()

    def test_config_dir_order(self):
        ws = Path(self.tmp.name) / "ws"
        (ws / "config").mkdir(parents=True)
        cfg_env = Path(self.tmp.name) / "cfgenv"
        cfg_env.mkdir()
        os.environ.pop("JOBISSIMO_CONFIG", None)
        os.environ["JOBISSIMO_HOME"] = str(ws)

        # workspace/config wins when no env override
        _, src = paths.config_dir_with_source()
        self.assertEqual(src, "workspace/config")

        # env override is highest
        os.environ["JOBISSIMO_CONFIG"] = str(cfg_env)
        path, src = paths.config_dir_with_source()
        self.assertEqual(src, "JOBISSIMO_CONFIG env")
        self.assertEqual(path, cfg_env.resolve())

        # legacy repo dir when neither env nor workspace/config exist
        os.environ.pop("JOBISSIMO_CONFIG", None)
        os.environ["JOBISSIMO_HOME"] = str(Path(self.tmp.name) / "bare")
        _, src = paths.config_dir_with_source()
        self.assertEqual(src, "legacy <repo>/config")

    def test_home_order(self):
        target = Path(self.tmp.name) / "elsewhere"
        target.mkdir()
        pointer = Path(self.tmp.name) / ".jobissimo"
        paths.POINTER_FILE = pointer

        # env highest
        os.environ["JOBISSIMO_HOME"] = str(target)
        _, src = paths.home_with_source()
        self.assertEqual(src, "JOBISSIMO_HOME env")

        # pointer next
        os.environ.pop("JOBISSIMO_HOME", None)
        pointer.write_text(str(target) + "\n")
        path, src = paths.home_with_source()
        self.assertEqual(src, ".jobissimo pointer")
        self.assertEqual(path, target.resolve())

        # default last
        pointer.unlink()
        _, src = paths.home_with_source()
        self.assertEqual(src, "default <repo>/profile")


class TestPushGate(unittest.TestCase):
    """The push gate must refuse on a verify mismatch and on a scrub finding,
    before any commit or push. Exercised in-process with the external calls
    stubbed so no real repo or remote is touched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)  # not a git repo -> commit/push steps are no-ops
        self._save = (sync.WORKSPACE, sync.run_db, sync.SCRUB_CLI)
        sync.WORKSPACE = self.ws

    def tearDown(self):
        sync.WORKSPACE, sync.run_db, sync.SCRUB_CLI = self._save
        self.tmp.cleanup()

    def _fake_db(self, verify_rc):
        import subprocess
        def run_db(*args):
            rc = verify_rc if args and args[0] == "verify-csv" else 0
            return subprocess.CompletedProcess(args, rc, "", "")
        return run_db

    def test_push_aborts_on_verify_mismatch(self):
        sync.run_db = self._fake_db(verify_rc=1)
        self.assertEqual(sync.cmd_push(object()), 1)

    def test_push_aborts_on_scrub_finding(self):
        sync.run_db = self._fake_db(verify_rc=0)
        # a scrub invocation that reports a finding
        sync.SCRUB_CLI = [sys.executable, "-c",
                          "import sys; print('SCRUB: 1 finding'); sys.exit(1)"]
        self.assertEqual(sync.cmd_push(object()), 1)


if __name__ == "__main__":
    unittest.main()
