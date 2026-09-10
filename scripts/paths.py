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


def home() -> Path:
    """The workspace root ($JOBISSIMO_HOME, default <repo>/profile)."""
    env = os.environ.get("JOBISSIMO_HOME")
    return Path(env).expanduser().resolve() if env else REPO_ROOT / "profile"


# --- engine side (committed) -------------------------------------------------

def config_dir() -> Path:
    """$JOBISSIMO_CONFIG overrides the repo config dir — used by the test
    suite and by parity runs against a copied workspace."""
    env = os.environ.get("JOBISSIMO_CONFIG")
    return Path(env).expanduser().resolve() if env else REPO_ROOT / "config"


def packs_dir() -> Path:
    return REPO_ROOT / "packs"


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
    print(f"repo:            {REPO_ROOT}")
    print(f"JOBISSIMO_HOME:  {home()}" + ("" if os.environ.get("JOBISSIMO_HOME") else "  (default)"))
    for name, fn in (("state db", state_db), ("knowledge", knowledge),
                     ("positioning", positioning), ("jd_texts", jd_texts),
                     ("applications", applications), ("runs", runs),
                     ("reports", reports), ("intake", intake)):
        p = fn()
        print(f"{name:<15} {p}  {'[exists]' if p.exists() else '[absent]'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
