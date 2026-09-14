"""Setup rehearsal — the deterministic spine of /setup, offline.

The LLM-driven extraction step (S2) is represented by the checked-in expected
output under fixtures/sam-rivera/expected/; these tests verify that the
deterministic scripts around it behave correctly and that the pipeline reaches
the first-result milestone (audit PASS + deterministic ATS >= 75) with no hand
editing beyond that expected output.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import (EN_APP, EXPECTED, FIXTURES, REPO, make_workspace, run_script)

sys.path.insert(0, str(REPO / "scripts"))
import paths          # noqa: E402
import setup_check    # noqa: E402


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
    """The acceptance bar of /setup, exercised offline.

    /setup itself now reaches its first result against a real posting the user
    chose, not this fixture — a sample application costs the full generation
    chain and produces something unsendable. The bundled JD stays as the
    offline proxy for that bar (audit PASS + deterministic ATS >= 75), since a
    test suite cannot hunt a live job.
    """

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


class TestPreferenceValidation(unittest.TestCase):
    """geography.work_modes / employment.* must be validated, not merely stored.

    A typo is worse than an omission here: the value silently matches no
    posting, and the user believes they set a preference that the hunt is
    quietly ignoring.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "config"
        shutil.copytree(FIXTURES / "sam-rivera" / "config", self.cfg)
        self.env = make_workspace(Path(self.tmp.name), with_apps=False)
        self.env["JOBISSIMO_CONFIG"] = str(self.cfg)
        self.targets = self.cfg / "targets.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        return run_script("setup_check.py", env=self.env)

    def test_fixture_preferences_validate(self):
        res = self.check()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertNotIn("employment", res.stdout.split("WARN")[0])

    def test_unknown_employment_type_is_an_error(self):
        self.targets.write_text(
            self.targets.read_text().replace("types: [full-time]", "types: [fulltime]"))
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("unknown value `fulltime`", res.stdout)

    def test_unknown_work_mode_is_an_error(self):
        self.targets.write_text(
            self.targets.read_text().replace("work_modes: [remote, hybrid]",
                                             "work_modes: [remote, onsight]"))
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("unknown value `onsight`", res.stdout)

    def test_contradictory_employment_preference_is_an_error(self):
        self.targets.write_text(
            self.targets.read_text().replace("types: [full-time]",
                                             "types: [full-time, internship]"))
        res = self.check()
        self.assertEqual(res.returncode, 1)
        self.assertIn("cannot be both wanted and rejected", res.stdout)

    def test_absent_preferences_warn_rather_than_fail(self):
        text = self.targets.read_text()
        for line in ("  work_modes: [remote, hybrid]\n", "  max_commute_minutes: 45\n",
                     "employment:\n", "  types: [full-time]\n", "  exclude: [internship]\n"):
            text = text.replace(line, "")
        self.targets.write_text(text)
        res = self.check()
        self.assertEqual(res.returncode, 0, res.stdout)   # absence is not a failure
        self.assertIn("no geography.work_modes", res.stdout)
        self.assertIn("records no employment preference", res.stdout)


class TestWorkspaceGuard(unittest.TestCase):
    """The workspace must be the user's own git repo, outside the engine clone.

    The first external playtest ended with a full profile sitting unversioned
    inside the engine checkout: gitignored, so `git status` looked clean and
    nothing ever said it was one `git clean -xfd` from gone. These assert on
    the warning text, not just the exit code — a guard nobody reads is no guard.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._env = dict(os.environ)
        self._repo_root = paths.REPO_ROOT
        self._pointer = paths.POINTER_FILE
        paths.POINTER_FILE = self.root / "no-such-pointer"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        paths.REPO_ROOT = self._repo_root
        paths.POINTER_FILE = self._pointer
        self.tmp.cleanup()

    def warnings_for(self, home: Path) -> list:
        os.environ["JOBISSIMO_HOME"] = str(home)
        errors, warnings = [], []
        setup_check.check_workspace(errors, warnings)
        self.assertEqual(errors, [], "workspace placement is a warning, never an error")
        return warnings

    @staticmethod
    def git_init(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
        return path

    def test_unversioned_workspace_warns_and_names_sync_init(self):
        home = self.root / "profile"
        home.mkdir()
        warnings = self.warnings_for(home)
        self.assertTrue(any("not a git repo" in w for w in warnings), warnings)
        self.assertTrue(any("/sync init" in w for w in warnings), warnings)

    def test_relocated_git_workspace_is_silent(self):
        home = self.git_init(self.root / "elsewhere")
        self.assertEqual(self.warnings_for(home), [])

    def test_in_place_layout_names_the_git_clean_exposure(self):
        paths.REPO_ROOT = self.root / "engine"
        home = self.git_init(paths.REPO_ROOT / "profile")
        warnings = self.warnings_for(home)
        self.assertTrue(any("git clean -xfd" in w for w in warnings), warnings)
        self.assertTrue(any("inside the engine checkout" in w for w in warnings), warnings)

    def test_fresh_clone_default_says_no_workspace_exists(self):
        """No $JOBISSIMO_HOME, no pointer — exactly a first `git clone`."""
        paths.REPO_ROOT = self.root / "engine"
        (paths.REPO_ROOT / "profile").mkdir(parents=True)
        os.environ.pop("JOBISSIMO_HOME", None)
        _, source = paths.home_with_source()
        self.assertTrue(source.startswith("default"), source)
        errors, warnings = [], []
        setup_check.check_workspace(errors, warnings)
        self.assertEqual(errors, [])
        self.assertTrue(any("no workspace has been established" in w for w in warnings),
                        warnings)

    def test_warning_reaches_the_cli_output(self):
        """In-process coverage is worthless if /doctor never prints it."""
        home = self.root / "unversioned"
        home.mkdir()
        env = dict(self._env)
        env["JOBISSIMO_HOME"] = str(home)
        env["JOBISSIMO_CONFIG"] = str(FIXTURES / "sam-rivera" / "config")
        res = run_script("setup_check.py", env=env)
        self.assertEqual(res.returncode, 0, res.stdout)   # warning, not error
        self.assertIn("not a git repo", res.stdout)


if __name__ == "__main__":
    unittest.main()
