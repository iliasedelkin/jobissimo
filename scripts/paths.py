#!/usr/bin/env python3
"""paths.py — single place that resolves where things live.

The engine (this repo) is separated from the workspace (all personal data and
generated artefacts). The workspace root is `$JOBISSIMO_HOME`, defaulting to
`<repo>/profile`. Every script and command file resolves paths through this
module — nothing else hardcodes a data path. That makes the personal-data rule
mechanical (one gitignored root) and makes multiple workspaces free: point
`JOBISSIMO_HOME` at a copy to rehearse or migrate without touching live data.

Run `python3 scripts/paths.py` to print the resolved layout.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# A desktop-launched agent session does not reliably inherit a shell profile's
# exports, so the workspace location cannot depend on $JOBISSIMO_HOME surviving
# into every shell. This gitignored one-line pointer file, written by
# `/sync init`, records the absolute workspace path for those sessions. A
# workspace that silently resolved back to an empty <repo>/profile is how
# someone starts a second, divergent pipeline without noticing.
POINTER_FILE = REPO_ROOT / ".jobissimo"


def _read_pointer() -> Path | None:
    if not POINTER_FILE.exists():
        return None
    for line in POINTER_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return Path(line).expanduser().resolve()
    return None


def home_with_source() -> tuple[Path, str]:
    """Resolve the workspace root and report which rule won:
    $JOBISSIMO_HOME (highest) → .jobissimo pointer → <repo>/profile (default)."""
    env = os.environ.get("JOBISSIMO_HOME")
    if env:
        return Path(env).expanduser().resolve(), "JOBISSIMO_HOME env"
    ptr = _read_pointer()
    if ptr is not None:
        return ptr, ".jobissimo pointer"
    return REPO_ROOT / "profile", "default <repo>/profile"


def home() -> Path:
    """The workspace root: $JOBISSIMO_HOME, else the .jobissimo pointer, else
    <repo>/profile."""
    return home_with_source()[0]


# --- engine side (committed) -------------------------------------------------

def config_dir_with_source() -> tuple[Path, str]:
    """Resolve the config dir and report which rule won. Config is per-install
    personal data and travels with the workspace, so the workspace copy wins
    over the legacy repo dir:
    $JOBISSIMO_CONFIG (highest) → <workspace>/config → <repo>/config (legacy)."""
    env = os.environ.get("JOBISSIMO_CONFIG")
    if env:
        return Path(env).expanduser().resolve(), "JOBISSIMO_CONFIG env"
    ws = home() / "config"
    if ws.exists():
        return ws, "workspace/config"
    return REPO_ROOT / "config", "legacy <repo>/config"


def config_dir() -> Path:
    """$JOBISSIMO_CONFIG, else <workspace>/config when present, else the legacy
    <repo>/config. Config is personal data and travels with the workspace."""
    return config_dir_with_source()[0]


def packs_dir() -> Path:
    """Where the engine's shipped, community-maintained packs live."""
    return REPO_ROOT / "packs"


def workspace_packs_dir() -> Path:
    """Where an install's own packs live. Inside the workspace, so a personal
    pack travels with /sync, survives a `git clean -xfd` in the engine
    checkout, and is never a commit on a repo the user does not own."""
    return home() / "packs"


def engine_rules() -> Path:
    return REPO_ROOT / "engine" / "rules"


def templates_dir() -> Path:
    return REPO_ROOT / "templates"


def reference_docx() -> Path:
    return templates_dir() / "ats_reference.docx"


# --- workspace side (gitignored) ---------------------------------------------

def state_db() -> Path:
    return home() / "state" / "pipeline.db"


def knowledge() -> Path:
    return home() / "knowledge"


def positioning() -> Path:
    return home() / "positioning"


def jd_texts() -> Path:
    return home() / "jd_texts"


def applications() -> Path:
    return home() / "applications"


def runs() -> Path:
    return home() / "runs"


def reports() -> Path:
    return home() / "reports"


def intake() -> Path:
    return home() / "_intake"


def applicant_profile() -> Path:
    return home() / "applicant_profile.yaml"


def setup_state() -> Path:
    return home() / "setup_state.yaml"


def resolve_folder(value: str) -> Path:
    """Resolve a user-supplied folder argument: absolute, workspace-relative
    (`applications/...`), or repo-relative — first match that exists wins,
    else workspace-relative."""
    p = Path(value)
    if p.is_absolute():
        return p
    for base in (home(), REPO_ROOT):
        if (base / p).exists():
            return base / p
    return home() / p


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    ws, ws_src = home_with_source()
    cfg, cfg_src = config_dir_with_source()
    print(f"repo:            {REPO_ROOT}")
    print(f"workspace:       {ws}  (from {ws_src})")
    print(f"config:          {cfg}  (from {cfg_src})")
    for name, fn in (("state db", state_db), ("knowledge", knowledge),
                     ("positioning", positioning), ("jd_texts", jd_texts),
                     ("applications", applications), ("runs", runs),
                     ("reports", reports), ("intake", intake)):
        p = fn()
        print(f"{name:<15} {p}  {'[exists]' if p.exists() else '[absent]'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
