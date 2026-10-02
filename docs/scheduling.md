# Scheduling the cycle

`/cycle` is built to run unattended on a schedule and deliver one report:
reconcile what happened, hunt, advance the most perishable jobs, and say what
needs you today. It writes `runs/cycle_YYYY-MM-DD.md`. How you trigger it
depends on your agent host (Claude Code's scheduled tasks, cron invoking your
agent CLI — e.g. `codex exec --sandbox workspace-write '$cycle'` from the repo
root, see `docs/codex.md` — etc.) — this doc is about making a scheduled run *survive* and
*stay worth running*, which is where the hard lessons are.

## The two rules

**The report is the deliverable, not the hunt.** A partial report that arrives
on time beats a complete one that arrives mid-afternoon. The skeleton is
written first and every phase appends to it, so an interruption at any point
still leaves something real to deliver.

**Finding jobs is not the bottleneck; sending them is.** This is the rule that
shaped `/cycle` and retired its predecessor. `/brief` scanned mail, hunted, and
printed the dashboard — two phases that *added* to the pipeline and none that
advanced anything through it. Measured over one install's first four months
that produced a queue of prepared applications decaying faster than it drained:
assets generated at roughly twice the rate they were sent, and a substantial
body of fully prepared, ATS-scored work lost to postings that closed first.

So `/cycle` reconciles and advances as well as hunts, and it refuses to
generate into a full queue. **A run that prepares nothing because
`ready_wip_cap` is hit has done its job correctly** — it has told you the
bottleneck is the sending, not the finding.

## Cadence

One command, two profiles, in `config/pipeline.yaml → cycle.intensities`. Run
it daily while you are hunting hard, weekly when you are not; `--intensity`
picks the profile and individual flags override it for a one-off.

```yaml
cycle:
  default_intensity: daily
  intensities:
    daily:  {hunt_target: 10, prepare_count: 2, time_budget_min: 75,  liveness_sweep: stale_only}
    weekly: {hunt_target: 20, prepare_count: 4, time_budget_min: 120, liveness_sweep: all}
```

Start with the shipped numbers. Every run records what it actually cost
against them — found vs target, prepared vs cap, boards swept, elapsed — in its
`run_end` detail, so after a handful of runs `/optimise` can propose a profile
calibrated to your real yield rather than a guess. Runs propose, `/optimise`
reports, you approve.

## Failure modes worth designing around

These were all observed running an earlier version of this pipeline on a
laptop, and `/cycle` is shaped to handle them. If you script your own
scheduler, account for them:

- **A sleeping host drip-feeds the session.** On battery, a laptop may grant
  only short maintenance wakes, so a 75-minute browser run executes in
  ~45-second slices and never finishes. `/cycle` checks elapsed wall-clock
  (against a persisted start epoch, not its impression of time) at the top of
  every phase and bails out fast with `STATUS: starved` rather than burning the
  morning. Prefer scheduling for a time the machine is actually awake.
- **Same-day re-runs must not clobber a finished report.** `/cycle` archives an
  existing report before writing a new skeleton and refuses to overwrite one
  already marked `complete`. It checks for a legacy `morning_brief_{date}.md`
  too.
- **Concurrent runs race on job-id allocation.** `db.py next-id` is atomic (a
  persisted reservation counter under a write lock), and `/cycle` takes a
  single-run lock. On sandboxed mounts where files cannot be deleted, the lock
  is released by *overwriting* its marker, not removing it — `rm -rf` on that
  lock has never once succeeded in the recorded runs.
- **A dead browser costs up to 180 s to discover.** `/cycle` probes the browser
  first, while the time budget is untouched, and logs a `browser_probe` event
  so `/optimise` can count availability. If it is down, the reconcile phase
  runs mail-only, the hunt is skipped, and the liveness sweep degrades to a
  list of check links for a manual pass — but the prepare phase still runs,
  since generation needs no browser once a JD is on disk.
- **A domain the browser is not permitted to open is not a dead board.** The
  extension grants site access per domain and refuses navigation before the
  fetch. That is recorded as `permission_denied`, never as "barren", and never
  counts toward demoting a board. See
  `engine/adapters/browse/claude-in-chrome.md` § Failure modes.
- **`run_end` is mandatory**, including on abort — a run with no `run_end` is
  invisible to `/optimise`. `db.py log` refuses a *second* one for the same run
  id, so a resumed agent re-running its own wrap-up cannot double-count the run.

## What a scheduled run may and may not do

`/cycle` writes lifecycle state, which its predecessor did not. The boundary is
deliberate and lives in `/track` § Mail reconciliation:

- **Auto-applied:** only machine-unambiguous signals matching exactly one job —
  an explicit rejection, or a first reply on a job still `applied`. Every such
  write is echoed in the report, line by line.
- **Proposed, never applied:** offers, interview scheduling, stage
  progressions, anything matching more than one job, anything needing
  `--force`. These arrive as ready-to-run `/track` commands.

It never sends, replies to, labels, archives or drafts mail, and it never
submits an application — `/apply`'s hard stop is untouched. A scheduled run
changes *records of what happened*, never *what happens*.

## A degraded run still reports

Any phase failure appends one line to the report's Degradations section and the
next phase proceeds. If the run ends anything other than `complete`, it appends
a proposal to `reports/pending_suggestions.md` (runs propose, `/optimise`
triages, you approve) and surfaces the count in the report.
