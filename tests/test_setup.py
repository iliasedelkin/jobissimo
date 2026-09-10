"""Setup rehearsal — the deterministic spine of /setup, offline.

The LLM-driven extraction step (S2) is represented by the checked-in expected
output under fixtures/sam-rivera/expected/; these tests verify that the
deterministic scripts around it behave correctly and that the pipeline reaches
the first-result milestone (audit PASS + deterministic ATS >= 75) with no hand
editing beyond that expected output.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from helpers import (EN_APP, EXPECTED, FIXTURES, make_workspace, run_script)


class TestIntake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_intake_ingests_multiple_formats_and_detects_language(self):
        src = FIXTURES / "sam-rivera"
        res = run_script(
            "intake.py",
            str(src / "cv_2024.md"),
            str(src / "cv_2025.docx"),
            str(src / "old_cover_letter.txt"),
            str(src / "linkedin_export"),
            env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        manifest = Path(self.env["JOBISSIMO_HOME"]) / "_intake" / "manifest.yaml"
        self.assertTrue(manifest.exists())
        text = manifest.read_text()
        # the DOCX must have been extracted (pandoc/textutil/python docx path)
        self.assertIn("cv_2025.docx", text)
        # at least one source detected as English
        self.assertIn("language: en", text)

    def test_intake_list_roundtrips(self):
        src = FIXTURES / "sam-rivera"
        run_script("intake.py", str(src / "cv_2024.md"), env=self.env)
        res = run_script("intake.py", "--list", env=self.env)
        self.assertIn("cv_2024.md", res.stdout)


class TestCompetencyAndCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_competency_map_builds_tiers(self):
        res = run_script("competency_map.py", "--stdout", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("# Competency Map", res.stdout)
        # evidence-weighted tiers appear
        self.assertRegex(res.stdout, r"\bcore\b|\bsupporting\b|\bcontextual\b")

    def test_coverage_flags_unevidenced_and_contradiction(self):
        res = run_script("coverage.py", "--no-queue", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PROFILE STRENGTH", res.stdout)
        self.assertIn("Contradictions flagged: 1", res.stdout)
        # Figma is claimed-but-unevidenced -> reported as gap, never CV-eligible
        m = re.search(r"Skills evidenced:\s+(\d+)/(\d+)", res.stdout)
        self.assertIsNotNone(m)

    def test_coverage_builds_queue(self):
        res = run_script("coverage.py", env=self.env)
        self.assertEqual(res.returncode, 0, res.stderr)
        queue = Path(self.env["JOBISSIMO_HOME"]) / "knowledge" / "_queue.yaml"
        self.assertTrue(queue.exists())
        text = queue.read_text()
        # metric-rescue items for the two unquantified Fernwood bullets
        self.assertIn("metric-FERN-PM-003", text)
        self.assertIn("skill-figma", text)


class TestFirstResultMilestone(unittest.TestCase):
    """The acceptance gate of /setup: the bundled sample JD, prepared against
    the fixture profile, passes the audit and scores >= 75 first pass."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_milestone_audit_pass_and_ats_at_least_75(self):
        audit = run_script("audit.py", "--folder", f"applications/{EN_APP}", env=self.env)
        self.assertEqual(audit.returncode, 0, audit.stdout)
        self.assertIn("OVERALL: PASS", audit.stdout)
        ats = run_script("ats_score.py", "--folder", f"applications/{EN_APP}",
                         "--jd", "jd_texts/sample001.md", env=self.env)
        self.assertEqual(ats.returncode, 0, ats.stderr)
        m = re.search(r"^SCORE: (\d+)$", ats.stdout, re.MULTILINE)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 75)


class TestSetupCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_setup_check_runs_clean_on_fixture_config(self):
        res = run_script("setup_check.py", env=self.env)
        # warnings are allowed (e.g. no PDF engine on CI); errors are not
        self.assertEqual(res.returncode, 0, res.stdout)


if __name__ == "__main__":
    unittest.main()
