# /sync – version and sync the workspace across machines, safely

The workspace ($JOBISSIMO_HOME) is your **own private git repo**, separate from
this public engine repo. `/sync` is the ONLY thing that moves either to a
remote — no pipeline command ever syncs on its own. Backing helper:
`scripts/sync.py` (four verbs). See `docs/sync.md` for the full model.

The database is a runtime artefact: `db.py export-csv` writes the CSVs that are
the record of record, the `.db` is gitignored, and `db.py import-csv` rebuilds
it on the other machine. Never merge divergent pipeline state — show both
sides and let the user choose.

`/sync` with no verb runs `status`.

## status

```bash
python3 scripts/sync.py status
```

Read-only: uncommitted changes in each repo, whether the DB and CSVs agree,
whether either remote is ahead/behind, and which machine wrote last. No side
effects. Relay it; suggest `pull`/`push` as appropriate.

## init (one-time, idempotent)

Reach the user's placement decision first, stating the trade-off plainly:

- **Relocated (recommended)** — the workspace lives in a sibling directory
  (e.g. `../jobissimo-workspace`) with a `.jobissimo` pointer in this repo.
  Nothing personal lives inside the engine checkout.
- **In place** — `<repo>/profile` becomes its own git repo. One folder to
  open, and safe day to day since `/profile/` is gitignored — **but a
  `git clean -xfd` in the engine repo would delete the whole workspace,
  including its `.git`.** Say this out loud before choosing it.

Then:

```bash
python3 scripts/sync.py init --dry-run           # preview the first commit
python3 scripts/sync.py init [--remote <PRIVATE_URL>]
```

`init` writes the workspace `.gitignore` (from `templates/workspace.gitignore`),
runs `git init`, writes the `.jobissimo` pointer when relocated, exports the
CSVs, shows a per-directory count and total size, and makes the first commit.

**Private remote.** With `gh` authenticated, create a PRIVATE repo and push:

```bash
gh repo create <name> --private --source="$JOBISSIMO_HOME" --remote=origin --push
```

Never create or fall back to a public repository. Confirm the repo is private
from the API response. If `gh` is missing/unauthenticated, print the manual
steps (create a private repo in the browser, `git remote add origin`, push) and
stop — do not improvise.

## pull (start of session)

```bash
python3 scripts/sync.py pull
```

Fast-forward-pulls both repos, reports what changed, and rebuilds the DB with
`import-csv` if the CSVs are newer. If this machine has un-exported writes AND
the remote CSVs also moved, it **stops and shows both sides** — never merges,
never picks a winner. Relay the three choices it prints and let the user pick.

## push (end of session)

```bash
python3 scripts/sync.py push
```

In order: `export-csv` → `verify-csv` (abort on mismatch) → scrub gate over the
engine tree + history (abort, naming file:line, on any finding) → commit the
workspace with a message derived from the run's events → report engine changes
separately → push both. Engine changes are code, not a sync artefact: review
and commit them with a conventional message yourself before pushing.

## Second machine

See `docs/sync.md` § Second machine — clone both repos, drop the `.jobissimo`
pointer, `db.py import-csv`, then `/doctor` to re-detect capabilities. Nothing
from `/setup` is re-answered.

## Stdout summary (always end with this)

```
Sync: {verb}
Workspace: {branch} — {clean | N changes}, {ahead A / behind B | no remote}
Engine:    {branch} — {clean | N changes}, {ahead A / behind B}
DB vs CSVs: {in sync | rebuilt | OUT OF SYNC | divergence — user choice needed}
{action taken or awaited: commit hashes pushed, or the choice presented}
```
