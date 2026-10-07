"""scrub_check.py — the PII gate catches planted personal strings and passes
the clean repo. This test enforces the same thing the pre-commit hook does."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, make_workspace, run_script


class TestScrub(unittest.TestCase):
    def scan(self, *paths):
        return run_script("scrub_check.py", *[str(p) for p in paths])

    def test_clean_tree_passes(self):
        # scan the committed, non-profile parts of the repo
        for d in ("scripts", "engine", "packs", "fixtures", ".claude", ".agents",
                  ".codex", "templates", "docs"):
            p = REPO / d
            if not p.exists():
                continue
            res = self.scan(p)
            self.assertEqual(res.returncode, 0,
                             f"{d} tripped the scrub gate:\n{res.stdout}")

    def test_planted_email_caught(self):
        # assemble the leak at runtime so this source file itself stays clean
        # under `scrub_check.py --all` (which scans tests/ too)
        leak = "real.person@" + "gmail.com"
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "leak.md"
            f.write_text(f"contact me at {leak} anytime\n")
            res = self.scan(f)
            self.assertEqual(res.returncode, 1)
            self.assertIn("email", res.stdout)

    def test_example_email_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "ok.md"
            f.write_text("contact sam.rivera@example.com anytime\n")
            self.assertEqual(self.scan(f).returncode, 0)

    def test_planted_job_id_caught(self):
        leak = "linkedin" + "042"
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "leak.md"
            f.write_text(f"see {leak} for details\n")
            res = self.scan(f)
            self.assertEqual(res.returncode, 1)
            self.assertIn("job-id", res.stdout)

    def _settings_local_repo(self, t: str, ignored: bool) -> Path:
        root = Path(t)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        # isolate from the developer's global excludes file, which may already
        # ignore .claude/settings.local.json
        subprocess.run(["git", "config", "core.excludesFile", "/dev/null"],
                       cwd=root, check=True)
        if ignored:
            (root / ".gitignore").write_text(".claude/settings.local.json\n")
        (root / ".claude").mkdir()
        leak = "real.person@" + "gmail.com"
        (root / ".claude" / "settings.local.json").write_text(f'{{"x": "{leak}"}}\n')
        return root

    def test_ignored_settings_local_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._settings_local_repo(t, ignored=True)
            res = self.scan(root)
            self.assertEqual(res.returncode, 0, res.stdout)

    def test_unignored_settings_local_still_scanned(self):
        with tempfile.TemporaryDirectory() as t:
            root = self._settings_local_repo(t, ignored=False)
            res = self.scan(root)
            self.assertEqual(res.returncode, 1)
            self.assertIn("settings.local.json", res.stdout)

    def test_planted_profile_handle_caught(self):
        leak = "linkedin.com/in/" + "some-real-handle"
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "leak.md"
            f.write_text(f"{leak} here\n")
            res = self.scan(f)
            self.assertEqual(res.returncode, 1)

    def test_fictional_phone_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "ok.md"
            f.write_text("call +1 555 0134 anytime\n")
            self.assertEqual(self.scan(f).returncode, 0)


class TestOutbound(unittest.TestCase):
    """--outbound / --gh-hook: anonymised-but-true values cannot leave the
    workspace (AGENTS.md invariant 11)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)
        # one job the candidate applied to, with an offer figure in its stage log
        for args in (
                ("add-job", "--job-id", "sample071", "--source", "sample",
                 "--company", "Quillfeather", "--title", "Widget Lead",
                 "--url", "https://example.com/sample071", "--date-found", "2026-01-10",
                 "--jd-path", "jd_texts/sample071.md", "--status", "ready"),
                ("set-status", "--job-id", "sample071", "--status", "applied",
                 "--applied-via", "email", "--date", "2026-01-12"),
                ("set-field", "--job-id", "sample071", "interview_stage",
                 "offer: offer received 2026-01-20 — 61,234 EUR")):
            res = run_script("db.py", *args, env=self.env)
            self.assertEqual(res.returncode, 0, res.stderr)

    def tearDown(self):
        self.tmp.cleanup()

    def outbound(self, body: str):
        f = Path(self.tmp.name) / "body.md"
        f.write_text(body)
        return run_script("scrub_check.py", "--outbound", str(f), env=self.env)

    def hook(self, command: str):
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "scrub_check.py"), "--gh-hook"],
            input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True, text=True, env=self.env, cwd=REPO)

    def test_real_amount_date_company_caught_without_names(self):
        for body, what in (("The first offer was 61.234 gross.", "real amount"),
                           ("An offer of 61k arrived.", None),  # 61000 is not the figure
                           ("Applied on 2026-01-12.", "real workspace date"),
                           ("Quillfeather replied quickly.", "company")):
            res = self.outbound(body + "\n")
            if what is None:
                self.assertEqual(res.returncode, 0, res.stdout)
            else:
                self.assertEqual(res.returncode, 1, body)
                self.assertIn(what, res.stdout)

    def test_profile_salary_is_fingerprinted(self):
        # the fixture profile's expectation is a real value for that workspace
        res = self.outbound("vs expectation 100,000\n")
        self.assertEqual(res.returncode, 1)
        self.assertIn("real amount", res.stdout)

    def test_telemetry_shapes_caught(self):
        for body in ("In one install the mail phase skipped.",
                     "Seen in 4 of 4 replies.",
                     "Response rate was 43 %.",
                     "Direction only, n = 8.",
                     "9 applied → 4 responded → 1 offer",
                     "| hr | 3 | 2 | 1 |"):
            res = self.outbound(body + "\n")
            self.assertEqual(res.returncode, 1, body)
            self.assertIn("telemetry signature", res.stdout)

    def test_synthetic_block_permits_shape_not_real_values(self):
        ok = ("<!-- synthetic -->\n| seq | amount | date |\n| 3 | 250000 | 2030-01-15 |\n"
              "| 4 | 260000 | 2030-01-16 |\n<!-- /synthetic -->\n")
        res = self.outbound(ok)
        self.assertEqual(res.returncode, 0, res.stdout)
        bad = "<!-- synthetic -->\n| 3 | 61234 | 2030-01-15 |\n<!-- /synthetic -->\n"
        res = self.outbound(bad)
        self.assertEqual(res.returncode, 1)
        self.assertIn("real amount", res.stdout)

    def test_mechanism_only_body_passes(self):
        body = ("Target: `scripts/db.py:52` — `responded` has no offer state.\n"
                "Repro on the fixture: record an offer of 250000 on 2030-01-15.\n")
        res = self.outbound(body)
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_gh_hook_blocks_leaky_body_and_passes_clean(self):
        f = Path(self.tmp.name) / "issue.md"
        f.write_text("Evidence: 9 applied → 4 responded.\n")
        res = self.hook(f"gh issue create --title t --body-file {f}")
        self.assertEqual(res.returncode, 2)
        self.assertIn("outbound gate", res.stderr)
        f.write_text("Target: `scripts/db.py:52`.\n")
        self.assertEqual(self.hook(f"N=$(gh issue create -t t -F {f})").returncode, 0)

    def test_gh_hook_resolves_variables_and_fails_closed(self):
        d = Path(self.tmp.name)
        (d / "leak.md").write_text("Seen in one install.\n")
        res = self.hook(f"D={d} && gh issue create -t t --body-file $D/leak.md")
        self.assertEqual(res.returncode, 2)
        self.assertIn("telemetry signature", res.stderr)
        res = self.hook("gh issue create -t t --body-file $UNSET_DIR/x.md")
        self.assertEqual(res.returncode, 2)
        self.assertIn("not readable", res.stderr)

    def test_gh_hook_requires_scannable_body(self):
        self.assertEqual(self.hook("gh issue create --title t").returncode, 2)
        res = self.hook('gh issue comment 5 --body "seen in one install"')
        self.assertEqual(res.returncode, 2)

    def test_gh_hook_ignores_reads_mentions_and_heredocs(self):
        for cmd in ("gh issue list --state all", "gh issue view 25 --json body",
                    "gh api repos/o/r/issues", "git grep -n 'gh issue create' docs",
                    "python3 - <<'EOF'\nx = '$(gh issue create -t t -F {f})'\nEOF\necho ok",
                    "ls -la"):
            self.assertEqual(self.hook(cmd).returncode, 0, cmd)


if __name__ == "__main__":
    unittest.main()
