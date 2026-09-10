# Scheduling the daily brief

`/brief` is built to run unattended on a schedule and deliver one morning
brief: a mail scan for recruiter replies, a hunt, and the dashboard, written
to `runs/morning_brief_YYYY-MM-DD.md`. How you trigger it depends on your
agent host (Claude Code's scheduled tasks, cron invoking your agent CLI, etc.)
— this doc is about making a scheduled run *survive*, which is where the hard
lessons are.

## The one rule

**The brief is the deliverable, not the hunt.** A partial brief that arrives
on time beats a complete one that arrives mid-afternoon. Every design choice
in `/brief` follows from this: the skeleton is written first and every phase
appends to it, so an interruption at any point still leaves something real to
deliver.

## Failure modes worth designing around

These were all observed running an earlier version of this pipeline on a
laptop, and `/brief` is shaped to handle them. If you script your own
scheduler, account for them:

- **A sleeping host drip-feeds the session.** On battery, a laptop may grant
  only short maintenance wakes, so a 75-minute browser run executes in
  ~45-second slices and never finishes. `/brief` checks elapsed wall-clock
  (against a persisted start epoch, not its impression of time) at the top of
  every phase and bails out fast with `STATUS: starved` rather than burning
  the morning. Prefer scheduling for a time the machine is actually awake.
- **Same-day re-runs must not clobber a finished brief.** `/brief` archives an
  existing brief before writing a new skeleton and refuses to overwrite one
  already marked `complete`.
- **Concurrent runs race on job-id allocation.** `db.py next-id` is atomic
  (a persisted reservation counter under a write lock), and `/brief` takes a
  single-hunt lock. On sandboxed mounts where files cannot be deleted, the
  lock is released by *overwriting* its marker, not removing it.
- **A dead browser costs up to 180 s to discover.** `/brief` probes the
  browser first, while the time budget is untouched, and logs a
  `browser_probe` event so `/optimise` can count availability. If it is down,
  phases run mail-only and the surviving candidate URLs are written as a
  ready-to-run list.
- **`run_end` is mandatory**, including on abort — a run with no `run_end` is
  invisible to `/optimise`.

## A degraded run still reports

Any phase failure appends one line to the brief's Degradations section and the
next phase proceeds. If the run ends anything other than `complete`, it
appends a proposal to `reports/pending_suggestions.md` (runs propose,
`/optimise` triages, you approve) and surfaces the count in the brief.
