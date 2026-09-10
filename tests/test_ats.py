"""ats_score.py — the deterministic scorer produces stable, expected results
on the fixtures, and the per-dimension breakdown is exact where it must be."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from helpers import EN_APP, IT_APP, make_workspace, run_script


def score_of(stdout: str) -> int:
    m = re.search(r"^SCORE: (\d+)$", stdout, re.MULTILINE)
    assert m, f"no SCORE line in:\n{stdout}"
    return int(m.group(1))


def dimension(stdout: str, name: str):
    m = re.search(rf"\| {re.escape(name)} \| ([\d.]+) \| (\d+) \|", stdout)
    assert m, f"dimension {name!r} not found"
    return float(m.group(1)), int(m.group(2))


class TestAts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_score(self, app, jd):
        return run_script("ats_score.py", "--folder", f"applications/{app}",
                          "--jd", f"jd_texts/{jd}", env=self.env)

    def test_en_fixture_scores_above_bar(self):
        res = self.run_score(EN_APP, "sample001.md")
        self.assertEqual(res.returncode, 0, res.stderr)
        s = score_of(res.stdout)
        self.assertGreaterEqual(s, 75, f"EN fixture must clear the bar, got {s}")
        # deterministic per-dimension expectations
        self.assertEqual(dimension(res.stdout, "Must-have requirement coverage"), (25.0, 25))
        self.assertEqual(dimension(res.stdout, "Section structure"), (10.0, 10))
        self.assertEqual(dimension(res.stdout, "Date-format compliance"), (10.0, 10))

    def test_it_fixture_scores_above_bar_via_locale_bridges(self):
        res = self.run_score(IT_APP, "sample002.md")
        self.assertEqual(res.returncode, 0, res.stderr)
        s = score_of(res.stdout)
        self.assertGreaterEqual(s, 75, f"IT fixture must clear the bar, got {s}")
        # the Italian requirement rows are covered only because the it.yaml
        # locale bridges map the CV's Italian wording to the taxonomy
        self.assertEqual(dimension(res.stdout, "Must-have requirement coverage"), (25.0, 25))

    def test_score_is_deterministic(self):
        a = score_of(self.run_score(EN_APP, "sample001.md").stdout)
        b = score_of(self.run_score(EN_APP, "sample001.md").stdout)
        self.assertEqual(a, b)

    def test_no_evidence_row_is_blocked_not_inserted(self):
        res = self.run_score(EN_APP, "sample001.md")
        self.assertIn("BLOCKED", res.stdout)
        self.assertIn("analytics tooling rollout", res.stdout)

    def test_condensed_jd_warns(self):
        stub = Path(self.env["JOBISSIMO_HOME"]) / "jd_texts" / "stub.md"
        stub.write_text("# JD\n\n## Raw text\ntoo short\n")
        res = self.run_score(EN_APP, "stub.md")
        self.assertIn("raw text", res.stderr.lower())


if __name__ == "__main__":
    unittest.main()
