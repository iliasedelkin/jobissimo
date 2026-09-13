# Syncing the workspace across machines

Everything personal lives in the **workspace** (`$JOBISSIMO_HOME`), which is
gitignored by the public engine repo. That protects it from publication — and,
by the same rule, from being backed up, versioned, or moved to a second
machine. `/sync` resolves that: the workspace becomes **its own private git
repo**, with its own private remote, entirely separate from the public engine.

## The two-repository model

| Repo | Holds | Remote | Committed by |
|---|---|---|---|
| **Engine** (this checkout) | scripts, packs, commands, docs, schemas | **public** GitHub | ordinary engine/pack commits |
| **Workspace** (`$JOBISSIMO_HOME`) | knowledge, positioning, config, applications, runs, reports, the CSV export of the pipeline DB | **private** | `/sync` only |

They are two independent repositories that happen to sit near each other on
disk. The workspace is **not** a branch of the engine and **not** a submodule
(see *Rejected alternatives*). Engine improvements you make while working flow
to the public repo as normal commits; personal data never leaves the private
one.

## The database is a runtime artefact

`state/pipeline.db` is binary, changes every run, and two machines that both
run the pipeline before syncing produce a git conflict that cannot be
resolved. So the workspace **does not commit the database**. Instead:

- `db.py export-csv` writes `state/backup/{jobs,events,id_reservations,meta}.csv`
  plus a `manifest.json` (schema version, row counts, SHA-256 per table, and
  the events AUTOINCREMENT high-water mark). These CSVs are the **record of
  record** and are committed.
- The `.db` and its journals are gitignored.
- `db.py import-csv` rebuilds the database from the CSVs on the other machine,
  restoring every column, NULL, the id-reservation counters, and the events
  sequence exactly.
- `db.py verify-csv` compares the live DB to the CSVs (row counts + hashes) and
  exits non-zero on any drift. `/sync push` runs it before committing.

The CSVs are plain text and diff cleanly; everything else in the workspace is
markdown or YAML and merges fine.

> **Never** put the live SQLite database in Dropbox, iCloud, or Syncthing.
> Concurrent access to a file-synced SQLite database is a known corruption
> source. Sync the CSVs through git; rebuild the DB locally.

## Placement: relocated vs in place

`/sync init` offers two layouts:

- **Relocated (recommended)** — the workspace is a sibling directory (e.g.
  `~/Documents/Job/jobissimo-workspace`) and the engine repo holds a one-line
  gitignored `.jobissimo` pointer to it. Nothing personal lives inside the
  engine checkout.
- **In place** — `<repo>/profile` becomes its own git repo. One folder to open,
  and safe day to day because `/profile/` is gitignored. **The hazard:** a
  `git clean -xfd` in the engine repo deletes ignored directories wholesale —
  which would erase the entire in-place workspace *including its `.git`*, in one
  command. Relocating removes that class of accident.

`.jobissimo` and `$JOBISSIMO_HOME` both point at the workspace; the pointer
exists because a desktop-launched agent session does not reliably inherit a
shell profile's exports. Resolution order is env → pointer → default; run
`python3 scripts/paths.py` to see which rule won.

`config/capabilities.yaml` is deliberately **per-machine** (the laptop has a
browser adapter; a server may not) and is gitignored inside the workspace;
`/doctor` rewrites it on each machine.

## The four verbs

- **`/sync status`** — uncommitted changes in each repo, whether the DB and
  CSVs agree, whether either remote is ahead, and which machine wrote last. No
  side effects.
- **`/sync init`** — one-time, idempotent: writes the workspace `.gitignore`,
  `git init`, first commit (after showing a per-directory count and total
  size), and — with `gh` authenticated — a **private** remote. It never creates
  or falls back to a public repository.
- **`/sync pull`** — start of session: fast-forward-pull both repos; rebuild the
  DB from CSVs if they are newer; **stop and show both sides** if pipeline state
  has diverged (never auto-merge, never pick a winner).
- **`/sync push`** — end of session: `export-csv` → `verify-csv` (abort on
  mismatch) → scrub gate over the engine tree and history (abort on any
  finding) → commit the workspace with a message derived from the run's events
  → push. Engine changes are committed separately, as reviewed code.

No pipeline command syncs on its own. `/hunt` and `/prepare` only *warn* if the
workspace looks stale; they never pull or push.

## Second machine

```
git clone https://github.com/iliasedelkin/jobissimo.git  ~/dev/jobissimo
git clone <PRIVATE-WORKSPACE-REMOTE>                      ~/dev/jobissimo-workspace
echo ~/dev/jobissimo-workspace > ~/dev/jobissimo/.jobissimo
cd ~/dev/jobissimo && python3 scripts/db.py import-csv
claude          # then: /doctor
```

`import-csv` rebuilds `state/pipeline.db` from the committed CSVs; `/doctor`
re-detects this machine's capabilities and writes a fresh
`config/capabilities.yaml`. Nothing from `/setup` is re-answered. Confirm the
new machine's `/dashboard` shows the same funnel as the first.

Day to day: `/sync pull` when you sit down, `/sync push` when you finish.

## Rejected alternatives (and why)

- **One repo, two remotes, branch discipline** — one mistyped `git push --all`
  publishes everything, permanently. Safety by care, not by construction.
- **Workspace as a submodule** — `.gitmodules` publishes the private remote's
  URL and breaks `git clone` for everyone else.
- **A private fork that also pushes engine commits upstream** — one wrong
  refspec is irreversible; public git history cannot be un-published.
- **Committing the workspace encrypted to the public repo** — leaks file names,
  sizes, and commit cadence; a key mistake is catastrophic and permanent; and
  it turns a diffable text workspace into opaque blobs. Encryption on a
  *private* remote is a reasonable optional extra, where the disclosure risk is
  already bounded — that choice is left to you.
