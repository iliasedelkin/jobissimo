"""Schema v3 and the instrumentation around it: the event registry, run
pairing, asset fingerprints, the suggestion ledger, config.py, and backward
compatibility with v1/v2 records."""
from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import EN_APP, FIXTURE_CONFIG, REPO, make_workspace, run_script

sys.path.insert(0, str(REPO / "scripts"))
import db  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))
        cfg = Path(self.tmp.name) / "config"
        shutil.copytree(FIXTURE_CONFIG, cfg)
        self.env["JOBISSIMO_CONFIG"] = str(cfg)
        self.cfg = cfg
        self.home = Path(self.env["JOBISSIMO_HOME"])

    def tearDown(self):
        self.tmp.cleanup()

    def db(self, *args):
        return run_script("db.py", *args, env=self.env)

    def add(self, job_id, status="found", **kw):
        res = self.db("add-job", "--job-id", job_id, "--source", kw.get("source", "sample"),
                      "--company", kw.get("company", job_id.title()), "--title", "Product Manager",
                      "--url", f"https://example.com/{job_id}", "--date-found", "2030-01-10",
                      "--jd-path", f"jd_texts/{job_id}.md", "--status", status)
        self.assertEqual(res.returncode, 0, res.stderr)


class TestEvents(Base):
    def test_unknown_action_warns_then_strict_refuses(self):
        res = self.db("log", "--run-id", "r1", "--command", "hunt", "--action", "made_up_action")
        self.assertEqual(res.returncode, 0)
        self.assertIn("unknown event action", res.stderr)
        res = self.db("log", "--run-id", "r1", "--command", "hunt", "--action", "made_up_action", "--strict")
        self.assertEqual(res.returncode, 1)
        ok = self.db("log", "--run-id", "r1", "--command", "hunt", "--action", "run_start", "--strict")
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_required_detail_keys(self):
        res = self.db("log", "--run-id", "r2", "--command", "config", "--action", "config_changed",
                      "--detail", '{"file": "x"}', "--strict")
        self.assertEqual(res.returncode, 1)
        self.assertIn("missing", res.stderr)

    def test_every_action_in_command_files_is_registered(self):
        import re
        import events
        names = set()
        for f in (REPO / ".claude" / "commands").glob("*.md"):
            names |= set(re.findall(r"--action ([a-z_]+)", f.read_text(encoding="utf-8")))
        self.assertEqual(names - set(events.ACTIONS), set())

    def test_run_start_mints_logs_and_persists(self):
        out = self.db("run-start", "--command", "hunt", "--detail", '{"target_count": 10}')
        self.assertEqual(out.returncode, 0, out.stderr)
        rid = out.stdout.splitlines()[0]
        self.assertRegex(rid, r"^\d{8}_\d{6}_hunt$")
        ev = self.db("last-event", "--action", "run_start").stdout
        self.assertIn(rid, ev)
        self.assertIn('"target_count": 10', ev)
        # the same second twice still gives two runs
        again = self.db("run-start", "--command", "hunt", "--run-id", rid)
        self.assertNotEqual(again.returncode, 0)
        out = self.db("run-start", "--command", "cycle", "--persist").stdout.splitlines()[0]
        self.assertEqual((self.home / "runs" / ".current_run_id").read_text().strip(), out)
        self.assertTrue((self.home / "runs" / ".current_run_start").read_text().strip().isdigit())
        self.assertNotEqual(self.db("run-start", "--command", "x; rm").returncode, 0)

    def test_command_files_never_mint_ids_in_the_shell(self):
        for f in list((REPO / ".claude" / "commands").glob("*.md")) + list((REPO / "engine").rglob("*.md")):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("$RUN_ID", text.replace("`$RUN_ID` don't", ""), f.name)
            self.assertNotIn("date +%Y%m%d", text, f.name)

    def test_runs_and_orphans(self):
        for run, end in (("20300110_090000_hunt", True), ("20300111_090000_prepare", False)):
            cmd = run.rsplit("_", 1)[1]
            self.db("log", "--run-id", run, "--command", cmd, "--action", "run_start")
            if end:
                self.db("log", "--run-id", run, "--command", cmd, "--action", "run_end",
                        "--detail", '{"status": "partial"}')
        out = self.db("runs", "--orphans").stdout
        self.assertIn("20300111_090000_prepare", out)
        self.assertNotIn("20300110_090000_hunt", out)
        full = self.db("runs").stdout
        self.assertIn("partial", full)
        self.assertIn("1 orphan(s) in total", full)


class TestSchemaV3(Base):
    def test_new_fields_validate(self):
        self.add("sample001")
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "seniority_level", "senior").returncode, 0)
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "seniority_level", "guru").returncode, 1)
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "country", "IT").returncode, 0)
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "country", "Italy").returncode, 1)
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "industry", "b2b_saas").returncode, 0)
        self.assertEqual(self.db("set-field", "--job-id", "sample001", "industry", "B2B SaaS").returncode, 1)

    def test_old_database_is_migrated_in_place(self):
        path = self.home / "state" / "pipeline.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        old_schema = db.SCHEMA.replace("    updated_at TEXT NOT NULL,\n    seniority_level TEXT,\n"
                                       "    country TEXT,\n    industry TEXT\n);", "    updated_at TEXT NOT NULL\n);")
        self.assertNotIn("seniority_level", old_schema.split("CREATE TABLE IF NOT EXISTS events")[0])
        conn = sqlite3.connect(path)
        conn.executescript(old_schema)
        conn.close()
        self.add("sample002")
        self.assertEqual(self.db("set-field", "--job-id", "sample002", "country", "DE").returncode, 0)
        self.assertIn("country: DE", self.db("get", "sample002").stdout)

    def test_v2_backup_imports(self):
        self.add("sample003")
        out = Path(self.tmp.name) / "v2"
        self.assertEqual(self.db("export-csv", "--out", str(out)).returncode, 0)
        for f in ("assets.csv", "suggestions.csv"):
            (out / f).unlink()
        man = json.loads((out / "manifest.json").read_text())
        man["schema_version"] = 2
        (out / "manifest.json").write_text(json.dumps(man))
        rows = list(csv.reader(io.StringIO((out / "jobs.csv").read_text())))
        rows = [r[:-3] for r in rows]  # v2 had no taxonomy columns
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        (out / "jobs.csv").write_text(buf.getvalue())
        res = self.db("import-csv", "--dir", str(out))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Product Manager", self.db("get", "sample003").stdout)

    def test_asset_record_and_backfill(self):
        self.add("sample001", status="shortlisted")
        self.db("set-field", "--job-id", "sample001", "application_folder", f"applications/{EN_APP}")
        res = self.db("asset", "record", "--job-id", "sample001")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertRegex(res.stdout, r"cv: variant [0-9a-f]{10}")
        # same bullets -> same variant; backfill is idempotent
        self.assertIn("0 job(s)", self.db("asset", "backfill").stdout)
        self.assertIn("1 job(s)", self.db("asset", "backfill", "--refresh").stdout)
        out = Path(self.tmp.name) / "bk"
        self.db("export-csv", "--out", str(out))
        self.assertEqual((out / "assets.csv").read_text().count("\n"), 3)  # header + cv + cover

    def test_suggestion_ledger(self):
        ops = json.dumps([{"op": "set", "file": "pipeline", "key": "thresholds.ats_min_score", "to": 78}])
        res = self.db("suggestion", "add", "--title", "Raise the ATS floor", "--lens", "assets",
                      "--target", "config/pipeline.yaml", "--ops", ops, "--evidence", '{"n": 100}')
        self.assertEqual(res.returncode, 0, res.stderr)
        sid = res.stdout.split()[2].rstrip(":")
        self.assertRegex(sid, r"OPT-\d{8}-1")
        self.assertEqual(self.db("suggestion", "decide", sid, "--status", "rejected").returncode, 1)  # needs reason
        self.assertEqual(self.db("suggestion", "decide", sid, "--status", "applied").returncode, 1)   # not approved
        self.assertEqual(self.db("suggestion", "decide", sid, "--status", "approved").returncode, 0)
        # config.py applies the approved ops and marks it applied
        res = run_script("config.py", "apply-suggestion", sid, env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("ats_min_score: 78", (self.cfg / "pipeline.yaml").read_text())
        self.assertIn("applied", self.db("suggestion", "list").stdout)
        bad = self.db("suggestion", "add", "--title", "x", "--ops", '[{"op": "delete"}]')
        self.assertEqual(bad.returncode, 1)


class TestConfigWrite(Base):
    def test_set_preserves_comments_and_logs(self):
        before = (self.cfg / "pipeline.yaml").read_text()
        res = run_script("config.py", "set", "pipeline", "thresholds.adaptive_fit_bar", "3.8",
                         "--reason", "fit 3.8 postings replied", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        after = (self.cfg / "pipeline.yaml").read_text()
        diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(diff, [("  adaptive_fit_bar: 4.0", "  adaptive_fit_bar: 3.8")])
        self.assertTrue(after.startswith("# Fixture config"), "header comment lost")
        ev = self.db("last-event", "--action", "config_changed").stdout
        self.assertIn('"reason": "fit 3.8 postings replied"', ev)
        self.assertIn('"rev_before"', ev)

    def test_lists_and_refusals(self):
        res = run_script("config.py", "set", "targets", "geography.work_modes", "[remote, hybrid, onsite]",
                         "--reason", "open to onsite", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("work_modes: [remote, hybrid, onsite]", (self.cfg / "targets.yaml").read_text())
        for args in (["pipeline", "cycle.intensities.daily", "3"],      # a mapping
                     ["pipeline", "thresholds.not_a_key", "3"],          # missing
                     ["nope", "a.b", "1"]):                              # unknown file
            self.assertEqual(run_script("config.py", "set", *args, "--reason", "x", env=self.env).returncode,
                             1 if args[0] != "nope" else 2, args)
        self.assertEqual(run_script("config.py", "set", "pipeline", "thresholds.ats_min_score", "80",
                                    env=self.env).returncode, 2)  # --reason is required


if __name__ == "__main__":
    unittest.main()
