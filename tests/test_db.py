"""db.py — enum validation, dedupe gates, and the full transition matrix."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, make_workspace, run_script

sys.path.insert(0, str(REPO / "scripts"))
import db  # noqa: E402  (imported for the TRANSITIONS/STATUSES constants only)


def add(env, job_id, company="Acme", title="Widget Lead", status="found", url=None):
    return run_script(
        "db.py", "add-job", "--job-id", job_id, "--source", "sample",
        "--company", company, "--title", title,
        "--url", url or f"https://example.com/{job_id}",
        "--date-found", "2026-01-10", "--jd-path", f"jd_texts/{job_id}.md",
        "--status", status, env=env)


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_get_and_url_dedupe(self):
        self.assertEqual(add(self.env, "sample001").returncode, 0)
        got = run_script("db.py", "get", "sample001", env=self.env)
        self.assertIn("Acme", got.stdout)
        dup = add(self.env, "sample002", company="Other", title="Other Role",
                  url="https://example.com/sample001")
        self.assertEqual(dup.returncode, 1)
        self.assertIn("URL already recorded", dup.stderr)

    def test_company_title_repost_gate(self):
        add(self.env, "sample001")
        dup = add(self.env, "sample002", company="acme", title="widget  lead!")
        self.assertEqual(dup.returncode, 1)
        self.assertIn("likely a repost", dup.stderr)
        distinct = add(self.env, "sample003", company="Acme", title="Senior Widget Lead")
        self.assertEqual(distinct.returncode, 0)

    def test_transition_matrix_exhaustive(self):
        """Every legal transition succeeds; every illegal one is refused."""
        n = 0
        for src in db.STATUSES:
            for dst in db.STATUSES:
                if dst == src:
                    continue
                n += 1
                job = f"tmx{n:03d}"
                self.assertEqual(
                    add(self.env, job, company=f"C{n}", title=f"T{n}", status=src).returncode, 0)
                res = run_script("db.py", "set-status", "--job-id", job,
                                 "--status", dst, env=self.env)
                if dst in db.TRANSITIONS[src]:
                    self.assertEqual(res.returncode, 0,
                                     f"{src}->{dst} should be allowed: {res.stderr}")
                else:
                    self.assertEqual(res.returncode, 1,
                                     f"{src}->{dst} should be refused")
                    self.assertIn("not allowed", res.stderr)

    def test_score_sets_status_and_requires_reason(self):
        add(self.env, "sample010", company="ScoreCo", title="PM")
        no_reason = run_script(
            "db.py", "score", "--job-id", "sample010", "--fit-score", "2.0",
            "--role-cluster", "PM", "--seniority-match", "yes",
            "--location-fit", "match", "--apply-recommendation", "no",
            "--priority", "low", env=self.env)
        self.assertEqual(no_reason.returncode, 1)
        self.assertIn("rejection-reason", no_reason.stderr)
        ok = run_script(
            "db.py", "score", "--job-id", "sample010", "--fit-score", "4.2",
            "--role-cluster", "PM", "--seniority-match", "yes",
            "--location-fit", "match", "--apply-recommendation", "yes",
            "--priority", "high", env=self.env)
        self.assertEqual(ok.returncode, 0)
        self.assertIn("status=shortlisted", ok.stdout)

    def test_role_cluster_validates_against_pack_union_config(self):
        add(self.env, "sample020", company="ClusterCo", title="PM")
        bad = run_script(
            "db.py", "score", "--job-id", "sample020", "--fit-score", "4.0",
            "--role-cluster", "Wizard", "--seniority-match", "yes",
            "--location-fit", "match", "--apply-recommendation", "yes",
            "--priority", "high", env=self.env)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("Invalid role_cluster", bad.stderr)
        # a config with extra_role_clusters admits the extra value
        cfg = Path(self.tmp.name) / "config2"
        cfg.mkdir()
        base = (Path(self.env["JOBISSIMO_CONFIG"]) / "pipeline.yaml").read_text()
        (cfg / "pipeline.yaml").write_text(base + "extra_role_clusters: [Wizard]\n")
        env2 = dict(self.env, JOBISSIMO_CONFIG=str(cfg))
        ok = run_script(
            "db.py", "score", "--job-id", "sample020", "--fit-score", "4.0",
            "--role-cluster", "Wizard", "--seniority-match", "yes",
            "--location-fit", "match", "--apply-recommendation", "yes",
            "--priority", "high", env=env2)
        self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_next_id_and_urls_check(self):
        first = run_script("db.py", "next-id", "sample", env=self.env)
        self.assertEqual(first.stdout.strip(), "sample001")
        second = run_script("db.py", "next-id", "sample", env=self.env)
        self.assertEqual(second.stdout.strip(), "sample002")  # reservation persists
        add(self.env, "sample005", url="https://www.example.com/jobs/route?utm=x")
        chk = run_script("db.py", "urls", "--check",
                         "http://example.com/jobs/route/", env=self.env)
        self.assertIn("KNOWN", chk.stdout)

    def test_applied_follow_up_is_warm_channel_only(self):
        add(self.env, "sample030", company="WarmCo", title="PM", status="ready")
        cold = run_script("db.py", "set-status", "--job-id", "sample030",
                          "--status", "applied", "--applied-via", "linkedin", env=self.env)
        self.assertEqual(cold.returncode, 0)
        got = run_script("db.py", "get", "sample030", env=self.env)
        self.assertNotIn("follow_up_date", got.stdout)
        add(self.env, "sample031", company="WarmCo2", title="PM2", status="ready")
        warm = run_script("db.py", "set-status", "--job-id", "sample031",
                          "--status", "applied", "--applied-via", "referral", env=self.env)
        self.assertEqual(warm.returncode, 0)
        got = run_script("db.py", "get", "sample031", env=self.env)
        self.assertIn("follow_up_date", got.stdout)


if __name__ == "__main__":
    unittest.main()
