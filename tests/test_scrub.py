"""scrub_check.py — the PII gate catches planted personal strings and passes
the clean repo. This test enforces the same thing the pre-commit hook does."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import REPO, run_script


class TestScrub(unittest.TestCase):
    def scan(self, *paths):
        return run_script("scrub_check.py", *[str(p) for p in paths])

    def test_clean_tree_passes(self):
        # scan the committed, non-profile parts of the repo
        for d in ("scripts", "engine", "packs", "fixtures", ".claude", "templates", "docs"):
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


if __name__ == "__main__":
    unittest.main()
