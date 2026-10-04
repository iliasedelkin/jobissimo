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

    def test_ready_below_ats_threshold_warns_but_succeeds(self):
        """Advisory, not a gate: exit 0 AND a warning on stderr.

        The threshold used to be consulted only by /prepare's regeneration
        loop, so a sub-threshold asset became sendable indistinguishably from
        a good one. Sending a low scorer is still allowed — it is no longer
        silent.
        """
        add(self.env, "sample040", company="LowCo", title="PM", status="generated")
        run_script("db.py", "set-field", "--job-id", "sample040",
                   "ats_score_det", "71", env=self.env)
        res = run_script("db.py", "set-status", "--job-id", "sample040",
                         "--status", "ready", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("below the configured ats_min_score", res.stderr)

        # At or above the floor there is no warning.
        add(self.env, "sample041", company="HighCo", title="PM", status="generated")
        run_script("db.py", "set-field", "--job-id", "sample041",
                   "ats_score_det", "82", env=self.env)
        ok = run_script("db.py", "set-status", "--job-id", "sample041",
                        "--status", "ready", env=self.env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertNotIn("ats_min_score", ok.stderr)

    def test_duplicate_run_end_is_refused(self):
        """A run ends once; a second run_end double-counts it for /optimise."""
        first = run_script("db.py", "log", "--run-id", "20260101_000000_cycle",
                           "--command", "cycle", "--action", "run_end", env=self.env)
        self.assertEqual(first.returncode, 0, first.stderr)
        dup = run_script("db.py", "log", "--run-id", "20260101_000000_cycle",
                         "--command", "cycle", "--action", "run_end", env=self.env)
        self.assertEqual(dup.returncode, 1)
        self.assertIn("run_end already logged", dup.stderr)
        forced = run_script("db.py", "log", "--run-id", "20260101_000000_cycle",
                            "--command", "cycle", "--action", "run_end",
                            "--allow-duplicate-run-end", env=self.env)
        self.assertEqual(forced.returncode, 0, forced.stderr)
        # Other actions are never deduped.
        again = run_script("db.py", "log", "--run-id", "20260101_000000_cycle",
                           "--command", "cycle", "--action", "job_checked", env=self.env)
        self.assertEqual(again.returncode, 0, again.stderr)

    def test_last_event_is_a_per_account_watermark(self):
        """/track's mail window starts at the last scan of *this* mailbox."""
        empty = run_script("db.py", "last-event", "--action", "mail_scanned", env=self.env)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(empty.stdout, "")
        for run, account in (("r1", "a@example.com"), ("r2", "b@example.com"),
                             ("r3", "a@example.com")):
            run_script("db.py", "log", "--run-id", run, "--command", "track",
                       "--action", "mail_scanned",
                       "--detail", f'{{"account":"{account}","threads":1}}', env=self.env)
        latest = run_script("db.py", "last-event", "--action", "mail_scanned", env=self.env)
        self.assertEqual(latest.stdout.split("\t")[1], "r3")
        b = run_script("db.py", "last-event", "--action", "mail_scanned",
                       "--match", "account=b@example.com", env=self.env)
        self.assertEqual(b.stdout.split("\t")[1], "r2")
        none = run_script("db.py", "last-event", "--action", "mail_scanned",
                          "--match", "account=c@example.com", env=self.env)
        self.assertEqual(none.stdout, "")
        bad = run_script("db.py", "last-event", "--action", "mail_scanned",
                         "--match", "account", env=self.env)
        self.assertEqual(bad.returncode, 1)

    def test_dashboard_shows_age_and_flags_low_ats(self):
        """The ready list is ordered work; age and a sub-threshold score decide it."""
        add(self.env, "sample050", company="AgeCo", title="PM", status="generated")
        run_script("db.py", "set-field", "--job-id", "sample050",
                   "ats_score_det", "71", env=self.env)
        run_script("db.py", "set-status", "--job-id", "sample050",
                   "--status", "ready", env=self.env)
        out = run_script("db.py", "dashboard", env=self.env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ats 71 (below 75)", out.stdout)
        # date_found is 2026-01-10 in the add() helper, so the age is large and
        # positive; assert the shape rather than a value that moves daily.
        self.assertRegex(out.stdout, r"found 2026-01-10 \(\d+d\)")


if __name__ == "__main__":
    unittest.main()
