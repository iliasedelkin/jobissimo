# Migration from a pre-OSS workspace

`scripts/migrate.py` imports a workspace from the private, pre-OSS layout
(personal data scattered across top-level `knowledge/`, `positioning/`,
`profile/`, `jd_texts/`, `applications/`, `runs/`, `reports/`, `state/`, with
identity and board tiers hardcoded in rules and command files) into a clean
`$JOBISSIMO_HOME` workspace.

**This script is shipped, not run, by the OSS build.** Cutover from a live
install is a separate, owner-triggered step, gated on the parity suite below.
The script refuses to overwrite an existing DB, and it never touches the
source repo.

## What migrate.py does (the mechanical half)

- Copies `knowledge/` and `positioning/` unchanged.
- Copies `jd_texts/`, `applications/`, `runs/`, `reports/` unchanged.
- Copies `profile/applicant_profile.yaml` → `<home>/applicant_profile.yaml`.
- Copies `state/pipeline.db` **byte-for-byte** — the schema is identical;
  only enum validation became dynamic, and `db.py` validates against config
  UNION values already in the DB, so every historical row survives.
- Derives `config/pipeline.yaml` identity.name from the applicant profile.

## What it leaves to /setup (the judgement half)

The values that lived in prose (target-profile block, portal tier tables,
evaluation thresholds and geography) are not machine-parsed. After migrating,
run `/setup` to write `config/targets.yaml`, `config/languages.yaml`, and
`config/boards.yaml`, then `/doctor` to validate.

```sh
JOBISSIMO_HOME=/path/to/new/workspace \
  python3 scripts/migrate.py --source ~/path/to/private-repo --dry-run
# review, then drop --dry-run
```

## The parity gate (run before trusting the migrated workspace)

De-personalisation and migration are inverses, so the migrated engine must
reproduce the private engine's outputs exactly. Because every recorded
application folder carries an `ats_report.md` and `audit_log.md`, this is
checkable:

1. Point `$JOBISSIMO_HOME` at the migrated workspace (a copy — never live
   data).
2. For every folder under `applications/`, re-run
   `python3 scripts/audit.py --folder <folder>` and
   `python3 scripts/ats_score.py --folder <folder> --jd jd_texts/<id>.md`.
3. Require **identical audit verdicts and identical ATS scores** against the
   recorded reports across all folders.

Any divergence is a porting bug, not an improvement — investigate it before
cutover. Do not execute the migration against live data or trust the result
until parity is green.
