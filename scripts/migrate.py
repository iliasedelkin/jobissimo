#!/usr/bin/env python3
"""migrate.py — import a workspace from the pre-OSS private layout.

The private layout scattered personal data across top-level directories
(knowledge/, positioning/, profile/, jd_texts/, applications/, runs/,
reports/, state/) and hardcoded identity, targets, and board tiers inside its
rules and command files. This script performs the mechanical half of the
migration into a $JOBISSIMO_HOME workspace:

- knowledge/ and positioning/ move (copy) unchanged
- jd_texts/, applications/, runs/, reports/ copy unchanged
- profile/applicant_profile.yaml copies to <home>/applicant_profile.yaml
- state/pipeline.db copies byte-for-byte — the schema is identical; only
  enum validation became dynamic, and db.py validates against config UNION
  values already present in the DB, so historical rows never fail
- a skeleton config/pipeline.yaml is derived from the applicant profile
  (identity name); everything judgement-shaped (targets, boards, languages,
  evaluation thresholds) is listed as TODO output for /setup to complete,
  because those values live in prose files this script does not parse

**This script is shipped, not run, by the OSS build.** Cutover from a live
private install is a separate, owner-triggered step gated on the parity suite
described in docs/migration.md: the new engine must reproduce identical audit
verdicts and identical ATS scores across every recorded application folder
before the migrated workspace is trusted.

Usage:
  JOBISSIMO_HOME=/path/to/new/workspace \\
      python3 scripts/migrate.py --source ~/path/to/private-repo [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

COPY_DIRS = ["knowledge", "positioning", "jd_texts", "applications", "runs", "reports"]


def copy_tree(src: Path, dst: Path, dry: bool) -> int:
    count = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.name == ".DS_Store":
            continue
        rel = f.relative_to(src)
        target = dst / rel
        count += 1
        if dry:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="Path to the private repo root.")
    parser.add_argument("--dry-run", action="store_true", help="Report without copying.")
    args = parser.parse_args()

    src = Path(args.source).expanduser().resolve()
    home = paths.home()
    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 1
    if home.resolve() == src:
        print("ERROR: JOBISSIMO_HOME must not be the source repo.", file=sys.stderr)
        return 1
    db_target = paths.state_db()
    if db_target.exists():
        print(f"ERROR: {db_target} already exists — refusing to overwrite a live "
              "workspace. Point JOBISSIMO_HOME at an empty directory.", file=sys.stderr)
        return 1

    mode = "DRY RUN — " if args.dry_run else ""
    print(f"{mode}migrating {src} -> {home}\n")

    for d in COPY_DIRS:
        sdir = src / d
        if sdir.exists():
            n = copy_tree(sdir, home / d, args.dry_run)
            print(f"  {d + '/':<16} {n} file(s)")
        else:
            print(f"  {d + '/':<16} absent in source — skipped")

    prof = src / "profile" / "applicant_profile.yaml"
    if prof.exists():
        if not args.dry_run:
            home.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prof, home / "applicant_profile.yaml")
        print(f"  {'profile':<16} applicant_profile.yaml")

    db = src / "state" / "pipeline.db"
    if db.exists():
        if not args.dry_run:
            db_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db, db_target)
        print(f"  {'state':<16} pipeline.db ({db.stat().st_size} bytes, byte-for-byte)")
    else:
        print(f"  {'state':<16} pipeline.db absent — nothing to migrate")

    # Derive the mechanical part of config; leave judgement to /setup.
    name = None
    if prof.exists():
        m = re.search(r"^\s*full_name:\s*(.+)$", prof.read_text(encoding="utf-8"),
                      re.MULTILINE)
        if m:
            name = m.group(1).strip().strip('"')
    cfg = paths.config_dir() / "pipeline.yaml"
    if name and not cfg.exists():
        if not args.dry_run:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(
                "# Derived by scripts/migrate.py — complete with /setup.\n"
                "pack: product\n"
                "identity:\n"
                f"  name: {name}\n", encoding="utf-8")
        print(f"  {'config':<16} pipeline.yaml (identity.name derived)")

    print("""
Still to do (judgement values this script does not parse — run /setup):
  - config/targets.yaml    from the old hunt.md target-profile block and
                           job_evaluation_rules.md thresholds/geography
  - config/languages.yaml  declared languages + proficiency
  - config/boards.yaml     from the old hunt.md portal tier tables
  - /doctor                to verify the result

Then run the parity gate in docs/migration.md BEFORE trusting the migrated
workspace: identical audit verdicts and ATS scores on every recorded
application folder. Any divergence is a porting bug, not an improvement.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
