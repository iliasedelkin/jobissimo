"""export.py — trace stripping, the audit gate, and the pandoc failure mode.

export.py had no tests, which is how an unguarded `subprocess.run(["pandoc"...])`
shipped: a machine without pandoc got a bare FileNotFoundError traceback at the
last step of /prepare, after the whole generation chain had been paid for.
The missing-pandoc test below runs everywhere (it strips PATH), so the
regression is caught on CI whether or not the runner has pandoc installed.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import EN_APP, make_workspace, run_script

HAVE_PANDOC = shutil.which("pandoc") is not None


class TestExport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))
        self.folder = Path(self.env["JOBISSIMO_HOME"]) / "applications" / EN_APP
        self.cv = self.folder / "cv_draft.md"

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, *args, env=None):
        return run_script("export.py", "--folder", f"applications/{EN_APP}",
                          *args, env=env or self.env)

    def test_finals_strip_traces_and_leave_the_draft_alone(self):
        before = self.cv.read_text()
        self.assertIn("<!-- src:", before)  # guard: the fixture carries traces
        self.export("--skip-pdf")
        final = self.folder / "cv_final.md"
        self.assertTrue(final.exists(), "cv_final.md was not written")
        text = final.read_text()
        self.assertNotIn("<!-- src:", text)
        self.assertNotIn("<!--", text)
        self.assertIn("Fernwood", text)  # content survived the strip
        self.assertEqual(self.cv.read_text(), before, "the draft was mutated")

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed on this machine")
    def test_docx_is_produced_and_next_step_is_printed(self):
        res = self.export("--skip-pdf")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.folder / "cv.docx").exists())
        self.assertIn("Next:", res.stdout)

    def test_missing_pandoc_reports_install_rather_than_a_traceback(self):
        env = dict(self.env)
        env["PATH"] = str(Path(self.tmp.name) / "empty-path")  # no pandoc anywhere
        res = self.export("--skip-pdf", env=env)

        # a sentence the user can act on, not a stack trace
        self.assertNotIn("Traceback", res.stderr)
        self.assertIn("pandoc not found", res.stderr)
        self.assertIn("brew install pandoc", res.stderr)

        # the audited markdown finals are still written — nothing needs redoing
        final = self.folder / "cv_final.md"
        self.assertTrue(final.exists())
        self.assertNotIn("<!-- src:", final.read_text())

        # but the export is incomplete, so /prepare must not mark the job ready
        self.assertEqual(res.returncode, 1)
        self.assertFalse((self.folder / "cv.docx").exists())
        self.assertNotIn("Next:", res.stdout)

    def test_audit_failure_blocks_export(self):
        # Figma is in unevidenced.md — a hard truth-guardrail failure
        self.cv.write_text(self.cv.read_text().replace(
            "**Product:** Product discovery", "**Product:** Figma, Product discovery"))
        res = self.export("--skip-pdf")
        self.assertEqual(res.returncode, 1)
        self.assertIn("audit FAIL", res.stderr)
        self.assertFalse((self.folder / "cv_final.md").exists(),
                         "finals were written despite an audit FAIL")

    def test_skip_audit_bypasses_the_gate(self):
        self.cv.write_text(self.cv.read_text().replace(
            "**Product:** Product discovery", "**Product:** Figma, Product discovery"))
        self.export("--skip-audit", "--skip-pdf")
        self.assertTrue((self.folder / "cv_final.md").exists())


if __name__ == "__main__":
    unittest.main()
