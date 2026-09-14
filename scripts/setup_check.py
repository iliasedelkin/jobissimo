#!/usr/bin/env python3
"""setup_check.py — config validator and drift detector (backs /doctor).

Validates that the install's configuration is coherent:
- config files parse (the supported YAML subset) and required keys exist
- the selected pack exists and has the required files
- every configured language has a pack locale file (or is flagged as falling
  back to neutral behaviour)
- every target references a cluster the pack defines
- capabilities.yaml reflects tools that actually resolve on this machine
- the workspace is the user's own git repo and not an unversioned
  directory inside the engine checkout

Drift detection: profile/setup_state.yaml records a content hash per setup
stage; if the inputs behind a stage changed (knowledge hand-edited, competency
map stale, positioning citing a bullet ID that no longer exists), the stage is
reported stale.

Exit 0 = OK (warnings allowed), 1 = errors found.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402


def content_hash(*files: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        if f.exists():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def check_configs(errors: list, warnings: list) -> None:
    cfg_dir = paths.config_dir()
    pipeline = packs.load_config("pipeline")
    if not (cfg_dir / "pipeline.yaml").exists():
        warnings.append("config/pipeline.yaml missing — running on shipped example "
                        "defaults; run /setup to configure this install.")
    identity = pipeline.get("identity") or {}
    if not identity.get("name"):
        warnings.append("identity.name is not set — audit.py cannot verify the CV "
                        "name header until it is.")
    pack_name = pipeline.get("pack") or "product"
    pdir = packs.pack_dir(str(pack_name))
    if not pdir.exists():
        errors.append(f"Selected pack `{pack_name}` not found at {pdir}.")
        return
    for required in ("pack.yaml", "ats_keywords.yaml", "ats_synonyms.yaml"):
        if not (pdir / required).exists():
            errors.append(f"Pack `{pack_name}` is missing {required}.")

    targets = packs.load_config("targets").get("targets") or []
    clusters = set(packs.role_clusters())
    if isinstance(targets, list):
        for t in targets:
            if isinstance(t, dict):
                cl = t.get("cluster")
                if cl and cl not in clusters:
                    errors.append(f"targets.yaml references unknown cluster `{cl}` "
                                  f"(pack defines: {', '.join(sorted(clusters)) or 'none'}).")
    elif targets:
        errors.append("targets.yaml `targets` must be a list.")

    for code in packs.configured_languages():
        if not re.fullmatch(r"[a-z]{2}", code):
            errors.append(f"languages.yaml has non-ISO code `{code}`.")
            continue
        locale = packs.pack_dir() / "locales" / f"{code}.yaml"
        if not locale.exists():
            warnings.append(f"No pack locale for `{code}` — falls back to neutral "
                            "behaviour (no market conventions, no synonym bridges).")
        else:
            conv = packs.load_yaml(locale)
            if conv.get("verified") is False:
                warnings.append(f"Locale `{code}` is an unverified stub — conventions "
                                "are neutral until a native contributor confirms them.")


def check_capabilities(errors: list, warnings: list) -> None:
    caps = packs.load_config("capabilities")
    detected = {
        "python3": True,
        "pandoc": bool(shutil.which("pandoc")),
        "pdf_engine": any(shutil.which(t) for t in
                          ("tectonic", "xelatex", "pdflatex", "soffice", "libreoffice")),
        "pdftotext": bool(shutil.which("pdftotext")),
    }
    for tool, present in detected.items():
        recorded = (caps.get("tools") or {}).get(tool)
        if recorded is not None and bool(recorded) != present:
            warnings.append(f"capabilities.yaml records {tool}={recorded} but this "
                            f"machine resolves {present} — re-run /setup --stage preflight.")
    if not detected["pandoc"]:
        warnings.append("pandoc not found — DOCX export unavailable (markdown finals still work).")
    if not detected["pdf_engine"]:
        warnings.append("no PDF engine found — PDF export unavailable (DOCX is the primary format).")


def check_workspace(errors: list, warnings: list) -> None:
    """The workspace must be the user's own git repo, outside the engine checkout.

    Personal data that sits un-versioned inside the clone is invisible to
    `git status` (it is gitignored), so nothing tells the user it is neither
    backed up nor safe from `git clean -xfd`.
    """
    home, source = paths.home_with_source()
    inside_repo = paths.REPO_ROOT in home.parents or home == paths.REPO_ROOT
    if not (home / ".git").exists():
        where = "inside the engine checkout" if inside_repo else str(home)
        warnings.append(
            f"workspace ({where}) is not a git repo — your knowledge, positioning "
            "and pipeline state are unversioned and unsynced. Run `/sync init`.")
    elif inside_repo:
        warnings.append(
            f"workspace {home} lives inside the engine checkout (the in-place "
            "layout). Safe day to day, but `git clean -xfd` here would delete it, "
            "`.git` included. `/sync init` can relocate it to a sibling directory.")
    if source.startswith("default") and not (home / ".git").exists():
        warnings.append(
            "no workspace has been established — `$JOBISSIMO_HOME` is unset and "
            "there is no `.jobissimo` pointer, so /setup would write personal data "
            "into the engine clone. Run `/sync init` before /setup.")


def check_drift(errors: list, warnings: list) -> None:
    state = packs.load_yaml(paths.setup_state())
    stages = state.get("stages") or {}
    if not stages:
        warnings.append("profile/setup_state.yaml absent — /setup has not run in this workspace.")
        return
    know = paths.knowledge()
    hash_inputs = {
        "extract": [know / "master_experience.md", know / "skills_inventory.md",
                    know / "education_credentials.md"],
        "positioning": [know / "master_experience.md",
                        paths.positioning() / "positioning_library.md"],
    }
    for stage, files in hash_inputs.items():
        rec = stages.get(stage)
        if isinstance(rec, dict) and rec.get("input_hash"):
            if rec["input_hash"] != content_hash(*files):
                warnings.append(f"Stage `{stage}` inputs changed since setup — "
                                f"artifacts may be stale (re-run /setup --stage {stage} "
                                "or /enrich to rebuild).")
    # positioning citing dead bullet IDs
    master = (know / "master_experience.md")
    lib = paths.positioning() / "positioning_library.md"
    if master.exists() and lib.exists():
        ids = set(re.findall(r"#### ([A-Z0-9-]+)", master.read_text(encoding="utf-8")))
        cited = set(re.findall(r"<!--\s*(?:claims|src):([^>]+)-->", lib.read_text(encoding="utf-8")))
        flat = {c.strip() for group in cited for c in group.split(",")}
        dead = {c for c in flat if c and not c.startswith("company:") and c not in ids
                and re.match(r"^[A-Z0-9-]+$", c)}
        if dead:
            errors.append("positioning_library.md cites bullet IDs that no longer exist: "
                          + ", ".join(sorted(dead)[:10]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="Only print problems.")
    args = parser.parse_args()

    errors, warnings = [], []
    check_workspace(errors, warnings)
    check_configs(errors, warnings)
    check_capabilities(errors, warnings)
    check_drift(errors, warnings)

    if not args.quiet:
        _home, _source = paths.home_with_source()
        print(f"Workspace: {_home}  ({_source})")
        print(f"Pack:      {packs.active_pack()}")
        print(f"Languages: {', '.join(packs.configured_languages()) or '(none configured)'}")
        print()
    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"WARN:  {w}")
    if not errors and not warnings:
        print("Setup check: all clear.")
    elif not errors:
        print(f"\nSetup check: OK with {len(warnings)} warning(s).")
    else:
        print(f"\nSetup check: {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
