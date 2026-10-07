"""db.py — enum validation, dedupe gates, and the full transition matrix."""
from __future__ import annotations

import csv
import io
import json
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



class TestStages(unittest.TestCase):
    """Stage ledger (#27) and offers (#28): open-ended rounds with results, an
    `offered` status, offer figures with negotiation, and the funnel built on
    them. All values are fictional."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)

    def tearDown(self):
        self.tmp.cleanup()

    def db(self, *args):
        return run_script("db.py", *args, env=self.env)

    def applied(self, job_id, company):
        self.assertEqual(add(self.env, job_id, company=company, status="ready").returncode, 0)
        res = self.db("set-status", "--job-id", job_id, "--status", "applied",
                      "--applied-via", "email", "--date", "2030-01-02")
        self.assertEqual(res.returncode, 0, res.stderr)

    def stage(self, job_id, kind, day, *extra):
        res = self.db("stage", "add", "--job-id", job_id, "--kind", kind,
                      "--date", f"2030-01-{day:02d}", *extra)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res

    def field(self, job_id, name):
        for line in self.db("get", job_id).stdout.splitlines():
            if line.startswith(f"{name}: "):
                return line.split(": ", 1)[1]
        return None

    def test_gate_moves_applied_to_responded_and_settles_previous_round(self):
        self.applied("sample101", "Acme")
        res = self.stage("sample101", "hr", 10)
        self.assertIn("applied -> responded", res.stdout)
        self.assertEqual(self.field("sample101", "response_date"), "2030-01-10")
        res = self.stage("sample101", "hm", 24, "--label", "on site")
        self.assertIn("stage 1 (hr): pending -> passed", res.stdout)
        listing = self.db("stage", "list", "--job-id", "sample101").stdout
        self.assertRegex(listing, r"1\s+hr\s+2030-01-10\s+passed")
        self.assertRegex(listing, r"2\s+hm\s+2030-01-24\s+pending.*\[on site\]")

    def test_offer_flags_validated(self):
        self.applied("sample102", "Acme")
        res = self.db("stage", "add", "--job-id", "sample102", "--kind", "hr",
                      "--date", "2030-01-10", "--amount", "250000")
        self.assertEqual(res.returncode, 1)
        self.assertIn("only apply to kind=offer", res.stderr)
        res = self.db("stage", "add", "--job-id", "sample102", "--kind", "offer",
                      "--date", "2030-01-10", "--party", "employer")
        self.assertEqual(res.returncode, 1)
        self.assertIn("requires --amount and --party", res.stderr)
        res = self.db("stage", "add", "--job-id", "sample102", "--kind", "hr",
                      "--date", "2030-01-10", "--result", "countered")
        self.assertEqual(res.returncode, 1)

    def test_stage_refused_before_an_application(self):
        add(self.env, "sample103", status="shortlisted")
        res = self.db("stage", "add", "--job-id", "sample103", "--kind", "hr",
                      "--date", "2030-01-10")
        self.assertEqual(res.returncode, 1)
        self.assertIn("once an application exists", res.stderr)

    def test_negotiation_then_accept_closes_offer_accepted(self):
        self.applied("sample104", "Acme")
        self.stage("sample104", "hm", 10)
        res = self.stage("sample104", "offer", 20, "--party", "employer", "--amount", "250000")
        self.assertIn("responded -> offered", res.stdout)
        self.assertIn("stage 1 (hm): pending -> passed", res.stdout)
        res = self.stage("sample104", "offer", 21, "--party", "candidate", "--amount", "270000")
        self.assertIn("stage 2 (offer): pending -> countered", res.stdout)
        dash = self.db("dashboard").stdout
        self.assertIn("## Offers", dash)
        self.assertIn("employer 250,000 EUR gross/yr → you 270,000 (pending since 2030-01-21)",
                      dash)
        # the fixture profile's expectation is EUR 100000 (fixture)
        self.assertIn("vs expectation 100,000 (+150%)", dash)
        self.stage("sample104", "offer", 23, "--party", "employer", "--amount", "260000")
        res = self.db("stage", "resolve", "--job-id", "sample104", "--result", "accepted",
                      "--date", "2030-01-24")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("offered -> closed (outcome=offer_accepted)", res.stdout)
        self.assertEqual(self.field("sample104", "outcome"), "offer_accepted")
        stats = self.db("stats").stdout
        self.assertIn("## Offers", stats)
        self.assertIn("negotiated uplift (accepted ÷ first offer): median 1.04×", stats)

    def test_employer_offer_declined_or_withdrawn_closes(self):
        for job, result in (("sample105", "declined"), ("sample106", "withdrawn")):
            self.applied(job, f"Co {job}")
            self.stage(job, "offer", 20, "--party", "employer", "--amount", "250000")
            res = self.db("stage", "resolve", "--job-id", job, "--result", result)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(self.field(job, "outcome"), f"offer_{result}")

    def test_closing_rejected_fails_the_pending_round(self):
        self.applied("sample107", "Acme")
        self.stage("sample107", "hr", 10)
        self.stage("sample107", "tech", 20)
        res = self.db("set-status", "--job-id", "sample107", "--status", "closed",
                      "--outcome", "rejected", "--date", "2030-01-30")
        self.assertIn("stage 2 (tech): pending -> failed", res.stdout)
        listing = self.db("stage", "list", "--job-id", "sample107").stdout
        self.assertRegex(listing, r"2\s+tech\s+2030-01-20\s+failed\s+decided 2030-01-30")

    def test_offered_transitions(self):
        self.assertEqual(db.TRANSITIONS["responded"] >= {"offered"}, True)
        self.assertEqual(db.TRANSITIONS["offered"], {"closed"})
        self.assertNotIn("offer", db.OUTCOMES)

    def test_funnel_counts_round_depth_and_untested_tests(self):
        # 0 rounds passed (test pending), 1 passed then failed, 3 passed + offer
        self.applied("sample111", "A")
        self.stage("sample111", "test", 5)
        self.applied("sample112", "B")
        self.stage("sample112", "hr", 5)
        self.stage("sample112", "hm", 12)
        self.db("set-status", "--job-id", "sample112", "--status", "closed",
                "--outcome", "rejected")
        self.applied("sample113", "C")
        for kind, day in (("hr", 5), ("hm", 12), ("tech", 19), ("final", 26)):
            self.stage("sample113", kind, day)
        self.db("stage", "resolve", "--job-id", "sample113", "--result", "passed")
        self.stage("sample113", "offer", 28, "--party", "employer", "--amount", "250000")
        dash = self.db("dashboard").stdout
        # a pending test is not past screen; B and C are
        self.assertIn("3 applied → 3 responded (100%) → 2 past screen (66%) → "
                      "2 passed round 1 (66%) → 1 passed round 2 (33%) → "
                      "1 passed round 3 (33%) → 1 passed round 4 (33%) → 1 offer (33%)", dash)
        stats = self.db("stats").stdout
        self.assertIn("## Rounds (stage ledger)", stats)
        self.assertRegex(stats, r"hm\s+2\s+1\s+1\s+0\s+0")
        self.assertIn("days between consecutive rounds: median 7", stats)

    def test_legacy_funnel_unchanged_without_ledger(self):
        self.applied("sample121", "A")
        self.db("set-status", "--job-id", "sample121", "--status", "responded")
        self.db("set-field", "--job-id", "sample121", "interview_stage",
                "hr: call held 2030-01-10")
        dash = self.db("dashboard").stdout
        self.assertIn("1 past screen (100%) → 1 interview (100%)", dash)

    def test_v1_backup_imports_and_maps_legacy_offer(self):
        self.applied("sample131", "A")
        self.db("set-status", "--job-id", "sample131", "--status", "closed")
        out = Path(self.tmp.name) / "v1"
        self.assertEqual(self.db("export-csv", "--out", str(out)).returncode, 0)
        # rewrite as a v1 backup: no stages.csv, legacy outcome `offer`
        (out / "stages.csv").unlink()
        man = json.loads((out / "manifest.json").read_text())
        man["schema_version"] = 1
        (out / "manifest.json").write_text(json.dumps(man))
        jobs = (out / "jobs.csv").read_text().splitlines()
        cols = jobs[0].split(",")
        rows = list(csv.reader(jobs[1:]))
        for r in rows:
            r[cols.index("outcome")] = "offer"
        buf = io.StringIO()
        csv.writer(buf).writerows([cols] + rows)
        (out / "jobs.csv").write_text(buf.getvalue())
        res = self.db("import-csv", "--dir", str(out))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.field("sample131", "outcome"), "offer_accepted")


if __name__ == "__main__":
    unittest.main()
