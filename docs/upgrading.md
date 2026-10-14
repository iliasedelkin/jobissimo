# Upgrading

How an existing install takes a new engine. Your workspace — knowledge,
applications, config, the CSV record — is never touched by an upgrade except
through the scripts' own migrations, listed below per version.

## Every upgrade

1. **Finish or stop running work.** Quit the UI (*Quit* in the sidebar, or
   `python3 scripts/launcher.py stop`); a UI left open keeps the old code
   loaded.
2. **`/sync push`** — save this machine's state, exported by the engine that
   wrote it.
3. **`/sync pull`** — fast-forwards the engine, then the workspace, and
   rebuilds the database from the CSVs if they are newer. When the engine
   moved, it says whether these notes changed.
   - *"the branch … is gone from the remote"*: the checkout was on a feature
     branch that has since been merged and deleted. Switch to the default
     branch (`git checkout main`) and `/sync pull` again.
   - No private workspace remote yet? Update the engine alone:
     `git -C <engine> pull --ff-only`.
   - Installed with `install.sh`? Running it again does the same for the
     engine and leaves the workspace alone.
4. **Read the notes below** for every version between yours and the new
   one, and do their one-time steps. The version you are coming from is
   `schema_version` in your workspace's `state/backup/manifest.json` — read
   it before step 2's push rewrites it, or from that file's git history.
5. **Open it again** — the Jobissimo app, or `python3 scripts/ui.py`.

What happens by itself:

- **The database migrates on its first write** after the upgrade (new
  columns and tables are added in place; nothing is dropped).
- **Older CSV exports still import**: `db.py import-csv` accepts every schema
  version listed below, so a backup made before an upgrade restores after it.
- **The next `/sync push` after a schema change shows a one-time diff** —
  every row of the files that gained columns, plus any new files. Commit it
  once.

### Several machines

Upgrade the engine on every machine. `/sync pull` updates the engine before
it rebuilds the database, so the order takes care of itself; a machine whose
engine pull failed refuses CSVs newer than it understands (`import-csv`
names the schema version) rather than importing them wrongly. Fix the engine
pull, then pull again.

## Upgrade notes

Newest first. Each entry says what changes by itself and what, if anything,
you do once.

### Schema v3 — local UI, agent runs from the page, the app

By itself:

- Jobs gain `seniority_level`, `country`, `industry`; new tables `assets`
  (which bullets each CV cited) and `suggestions` (the optimiser's proposals
  as records). New CSVs: `assets.csv`, `suggestions.csv`.
- Commands mint run ids with `python3 scripts/db.py run-start`; nothing to
  change in your workspace.
- `config/local/` (UI state, run preferences, the UI log) is machine-local —
  already git-ignored by every workspace `.gitignore` written by `/sync init`.

Once, optional:

- Fingerprint past applications, so Knowledge and Analytics can show which
  bullets each CV used: `python3 scripts/db.py asset backfill`, then
  `/sync push`.
- Add the app: `python3 scripts/launcher.py install-app` (or *Settings → This
  computer*). Run it from a shell **without** `JOBISSIMO_HOME` exported, or
  the app keeps that workspace.
- On the *Settings* page, choose what agent runs may do without asking
  (job sites, web search, Chrome, reading Gmail).
- Don't run `install.sh` on an existing install: it creates a second engine
  and an empty workspace under `~/Jobissimo` unless `JOBISSIMO_WORKSPACE`
  points at yours.

### Schema v2 — the stage ledger

By itself:

- A `stages` table (`stages.csv`): one row per interview round, numbered with
  no upper limit, plus offer figures. Offer outcomes split into
  `offer_accepted` / `offer_declined` / `offer_withdrawn`; a legacy `offer`
  outcome imports as `offer_accepted`.
- Jobs without ledger rows keep the old text-derived funnel, so no history
  is lost.

Once, optional:

- Record past rounds through `/track` (or `db.py stage add --decided
  <date>`) for jobs whose rounds you want counted per round.

### Schema v1

The first CSV record. Imports into every later version.
