"""audit.py — the truth audit passes on clean fixtures and FAILs on each
seeded violation (missing trace, recombined metric, unevidenced skill, bad
date format, em dash, broken contact block, no_evidence term in the CV)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import EN_APP, make_workspace, run_script


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))
        self.folder = f"applications/{EN_APP}"
        self.cv = Path(self.env["JOBISSIMO_HOME"]) / self.folder / "cv_draft.md"

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self):
        return run_script("audit.py", "--folder", self.folder, env=self.env)

    def test_clean_fixture_passes(self):
        res = self.audit()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("OVERALL: PASS", res.stdout)

    def test_missing_trace_fails(self):
        text = self.cv.read_text()
        # drop the src trace on the first experience bullet
        text = text.replace(" <!-- src:FERN-PM-001 -->", "", 1)
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("missing src trace", res.stdout)

    def test_recombined_metric_fails(self):
        text = self.cv.read_text()
        # inject a number into a bullet whose source block does not contain it
        text = text.replace(
            "connecting support tickets to the product backlog.",
            "connecting support tickets to the product backlog, cutting churn 37%.")
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("37", res.stdout)

    def test_unevidenced_skill_fails(self):
        text = self.cv.read_text()
        # Figma is in unevidenced.md — must never appear in the Skills section
        text = text.replace("**Product:** Product discovery",
                            "**Product:** Figma, Product discovery")
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertTrue("Figma" in res.stdout)

    def test_bad_date_format_fails(self):
        text = self.cv.read_text()
        text = text.replace("(Aug 2022 to Present)", "(2022 - Present)")
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("date range", res.stdout.lower())

    def test_em_dash_fails(self):
        text = self.cv.read_text()
        text = text.replace("saving 5 hours of manual work per week.",
                            "saving 5 hours of manual work per week — a big win.")
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("Em dash", res.stdout)

    def test_broken_contact_block_fails(self):
        text = self.cv.read_text()
        text = text.replace("# Sam Rivera", "# Samuel Rivera")  # != config identity.name
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("name header", res.stdout)

    def test_no_evidence_term_in_cv_fails(self):
        text = self.cv.read_text()
        # REQ-010 "analytics tooling rollout" is no_evidence
        text = text.replace(
            "## Skills",
            "Led an analytics tooling rollout to other teams. <!-- src:FERN-PM-001 -->\n\n## Skills")
        self.cv.write_text(text)
        res = self.audit()
        self.assertEqual(res.returncode, 1)
        self.assertIn("no_evidence term appears", res.stdout)

    def test_library_mode_on_clean_and_dirty(self):
        lib = Path(self.tmp.name) / "lib_clean.md"
        lib.write_text(
            "# Positioning\n\n## Summary variant A\n"
            "Product manager who lifted activation 18%. <!-- claims:FERN-PM-001 -->\n")
        ok = run_script("audit.py", "--library", str(lib), env=self.env)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        bad = Path(self.tmp.name) / "lib_bad.md"
        bad.write_text(
            "# Positioning\n\n## Summary variant B\n"
            "Product manager who lifted activation 50%. <!-- claims:FERN-PM-001 -->\n")
        res = run_script("audit.py", "--library", str(bad), env=self.env)
        self.assertEqual(res.returncode, 1)
        self.assertIn("50", res.stdout)


if __name__ == "__main__":
    unittest.main()
