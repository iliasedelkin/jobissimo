"""Shared test helpers: temp workspaces built from the Sam Rivera fixtures,
and subprocess runners for the scripts (run as CLIs so each test gets a clean
environment — the scripts resolve $JOBISSIMO_HOME / $JOBISSIMO_CONFIG at
call time)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"
EXPECTED = FIXTURES / "sam-rivera" / "expected"
FIXTURE_CONFIG = FIXTURES / "sam-rivera" / "config"

EN_APP = "sample001_nimbus-metrics_product-manager"
IT_APP = "sample002_velatech_product-owner"
MISMATCH_APP = "sample003_corvid-robotics_firmware"


def make_workspace(tmpdir: Path, with_apps: bool = True) -> dict:
    """Build a workspace under tmpdir from the expected fixture output and
    return the env for running scripts against it."""
    home = Path(tmpdir) / "profile"
    (home / "knowledge").mkdir(parents=True)
    (home / "jd_texts").mkdir()
    (home / "applications").mkdir()
    for f in (EXPECTED / "knowledge").iterdir():
        shutil.copy2(f, home / "knowledge" / f.name)
    shutil.copy2(EXPECTED / "applicant_profile.yaml", home / "applicant_profile.yaml")
    for f in (FIXTURES / "jds").glob("*.md"):
        shutil.copy2(f, home / "jd_texts" / f.name)
    if with_apps:
        for app in (EXPECTED / "applications").iterdir():
            shutil.copytree(app, home / "applications" / app.name)
    env = dict(os.environ)
    env["JOBISSIMO_HOME"] = str(home)
    env["JOBISSIMO_CONFIG"] = str(FIXTURE_CONFIG)
    return env


def run_script(name: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / name), *args],
        capture_output=True, text=True, env=env, cwd=REPO)
