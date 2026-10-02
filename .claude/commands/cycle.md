# /cycle – one turn of the pipeline: reconcile, hunt, advance, report

The scheduled pass. Reconcile what happened since the last run, hunt for new
postings, advance the one or two most perishable jobs, and put the unsent
`ready` queue in front of the user — in one report they can read in two
minutes.

**This command orchestrates; it does not duplicate.** Every phase delegates to
the command that owns that job (`/track`, `/refresh`, `/hunt`, `/prepare`).
`/cycle` owns exactly four things: the run id and lock, the clock, the report,
and the caps. If you find yourself writing scoring, mail or generation logic
here, it belongs in the delegated command instead.

Two rules, both learned the hard way:

**The report is the deliverable, not the hunt.** A partial report that arrives
on time beats a complete one that arrives mid-afternoon.

**Finding jobs is not the bottleneck; sending them is.** A run that generates
nothing because the queue is already full has done its job correctly.

## Input

- `--intensity daily | weekly` — the profile from `config/pipeline.yaml →
  cycle.intensities`. Default: `cycle.default_intensity` (`daily`).
- Individual overrides — `--hunt-target N`, `--prepare-count K`,
  `--time-budget N` — beat the profile. Use them for a one-off, not as a habit:
  the profile is what `/optimise` calibrates.

Resolve the profile in phase 0 and record it in `run_start`; every later phase
reads the resolved numbers, never the config again.

## Operating rules

1. **Write the report first, then grow it.** The skeleton is written in phase
   0 and every later phase *appends* to it or replaces one of its `_pending_`
   placeholders. Never hold results in your head waiting for a final write
   step — an interruption then loses the whole run.
2. **No phase failure aborts the run.** A failed phase appends one line to the
   Degradations section; the next phase proceeds.
3. **Time budget:** from the intensity profile. Check elapsed against the
   epoch recorded in phase 0 (never your impression of elapsed time) at the
   top of every phase; on overrun, cut the remaining work and finalise.
4. **`run_end` is mandatory**, including on abort — a run with no `run_end` is
   invisible to `/optimise`. `db.py` refuses a second one, so log it once.
5. **Bail out fast on a starved host.** If wall-clock elapsed is wildly out of
   proportion to work actually done, the host is suspending the session;
   finalise with STATUS `starved` and stop. Re-check at the top of every phase,
   not just once — a stall can begin after any single checkpoint.
6. **Read-only everywhere** except `scripts/db.py` writes and files under
   `applications/`, `jd_texts/`, `runs/` and `reports/`. Never send, reply,
   label, archive, trash or draft mail. Never submit anything.
7. **Never `--force`.** If `db.py` refuses a transition, that is the phase's
   answer: record it for the user and move on.

## 0. Skeleton first

In **one** bash call: set `RUN_ID="$(date +%Y%m%d_%H%M%S)_cycle"`, persist it
and the start epoch to `runs/.current_run_id` / `runs/.current_run_start`
(never keep the run id only in your own context — that is exactly what a stall
destroys), log `run_start` (`--command cycle --detail
'{"source":"cycle","intensity":"daily","hunt_target":10,"prepare_count":2}'`),
and write `runs/cycle_YYYY-MM-DD.md`:

```
# Cycle — {date}

STATUS: in progress (started {HH:MM}, {intensity}, budget {N} min)
Run ID: {RUN_ID}

## Headline
_pending_

## Act now
_pending_

## Degradations
_none so far_

## Reconciled
_pending_

## New jobs
_pending_

## Prepared
_pending_

## Pipeline dashboard
{db.py dashboard output}
```

Guards, all in the same call:

- **Same-day protection:** if today's report exists with `STATUS: complete`,
  log `run_end` (`reason: duplicate`) and exit without touching it. If it
  exists in any other state, archive it to `cycle_{date}_prior_{HHMMSS}.md` —
  never truncate an earlier run's findings — and carry its reconciled findings
  and ready-to-run lists into the new skeleton instead of redoing that work.
  Check for a legacy `morning_brief_{date}.md` too, and treat it the same way.
- **Single-run lock:** create `runs/.hunt_lock` (mkdir-style atomic) with this
  run's id + epoch. Held and fresh (<90 min) → another pass is live: log
  `run_end` (`reason: lock_held`) and exit. Stale → steal it, **preferring to
  overwrite the marker files rather than delete them** (sandboxed mounts often
  permit writes but not deletes; `rm -rf` on this lock has never once succeeded
  in the recorded runs). Release in phase 5 the same way.

## 1. Browser + mail probes — spend the failure cost up front

- **Browser probe first:** one cheap browse-adapter liveness call (for
  claude-in-chrome, `tabs_context_mcp`; for codex-chrome, list open tabs).
  Dead browsers historically cost 180 s to discover — spend it now, log a `browser_probe` event with the outcome so
  `/optimise` can count availability. Failure → note `BROWSER: unavailable` in
  Degradations; phase 2 runs mail-only, phase 3 is skipped, phase 4 still runs
  (generation needs no browser once a JD is on disk).
- **Mail account guard:** verify the connected mail account matches
  `config/pipeline.yaml → mail.account` (see the mail adapter). Mismatch or no
  mail tool → append `MAIL SKIPPED — <reason>` to Degradations and skip the
  mail half of phase 2. Do not block: the liveness half still runs.
- **Starvation check:** phases 0–1 are about a minute of real work; if elapsed
  is already ≥5 min, finalise now with `STATUS: starved`, log `run_end`
  (`reason: host_starvation`), release the lock, stop.

## 2. Reconcile — what happened while we were away

The time-sensitive phase, and the one that keeps the rest of the pipeline
honest. Two halves; run both, in this order.

**Order matters:** this phase must precede the hunt. `/track` maintains the
watchlist `in_flight` / `cooldown` states that `/hunt` Step 0c reads when
sweeping, so reconciling first is what stops the hunt sweeping a company whose
application just closed — or skipping one whose hold just expired.

**2a. Mail → lifecycle.** Follow `/track` § Mail reconciliation exactly: it
owns the auto-apply / propose split, the evidence bar, and the stage
vocabulary. Do not re-derive any of that here. Append every automatic write to
the Reconciled section as it happens, and every proposal as a ready-to-run
`/track` command.

**2b. Liveness → `missed`.** Pre-application rows go stale silently; this is
where that is caught. Select by the intensity profile's `liveness_sweep`:

- `stale_only` (daily) — rows in `shortlisted | generated | ready` whose
  `date_found` is older than `thresholds.stale_pre_application_days`.
- `all` (weekly) — `/refresh`'s full default selection.

Hand that job-id list to `/refresh` and follow it. Its employer-source-only
evidence rules are the whole point of delegating: **a portal mirror saying
"closed" is not proof.** Anything it classifies as needing a manual check goes
into the report with its link, never into a status change.

On a dead browser, run 2b in `links` mode: classify nothing, list the check
links for a manual pass.

## 3. Hunt — one pass

Follow `/hunt` §2 (Source loop) and §3a–3e (per qualifying posting) in
**orchestrated mode** — `/hunt` § Orchestrated mode says which of its own
bookkeeping steps to suppress, because this run already owns them.

Parameters: `target_count` = the profile's `hunt_target`, `max_age_days` 7,
tier order from `config/boards.yaml`. Mail-sourced finds count toward the
target. Skip the phase entirely if the browser probe failed — the phase-2b
link list is the fallback deliverable. Check the clock before each new board.

**Append each job to the New jobs section as it is recorded**, not in a batch
at the end.

## 4. Advance — prepare the most perishable

This is the phase `/brief` never had, and the reason this command exists.

**First, the WIP guard.** Count `status = ready`. If that count is at or above
`thresholds.ready_wip_cap`, **skip this phase entirely.** Write one line to
Degradations and to Act now:

```
Prepare skipped: ready queue at {N}/{cap}. Generating another asset is not
progress — {oldest} has been ready {D} days.
```

A full queue is not a failure of the run; it is the run telling the user what
the actual bottleneck is. Record it in `run_end` as
`"prepare_skipped_reason":"wip_cap"`.

**Otherwise, select and delegate.** Candidates: `db.py list --status
shortlisted`, filtered to `apply_recommendation = yes`, ordered by
**`date_found` ascending**, take `prepare_count`.

Oldest first, not best first. The fit gradient is flat across this install's
applications (see `config/targets.yaml → calibration`), while prepared work
lost to a closed posting is the pipeline's largest measured waste. Freshness is
what is actually perishable. If `calibration.ranking_signal` says otherwise,
follow the config — it is the calibrated value and this paragraph is the
default.

Hand those job ids to `/prepare --limit K` and follow it. It owns the evidence
map, the truth audit, ATS scoring and export; none of that is re-specified
here. An audit failure surfaces to the user as `/prepare` specifies — it is
never silently bypassed, and a `halt` ends this phase, not the run.

Append each finished job to the Prepared section with its audit verdict and
scores.

## 5. Finalise

One bash call: log `run_end` with the real numbers, then release the lock by
overwriting its markers.

```bash
python3 scripts/db.py log --run-id $RUN_ID --command cycle --action run_end \
  --detail '{"intensity":"daily","found":N,"shortlisted":M,
             "reconciled_auto":A,"reconciled_proposed":P,
             "liveness_checked":L,"marked_missed":X,
             "prepared":K,"prepare_skipped_reason":null,
             "boards_swept":B,"elapsed_min":E,"status":"complete"}'
```

Those numbers are the calibration record: they are what lets `/optimise`
propose an intensity profile that matches what a run actually costs. Report
what happened, not what was planned — a target of 10 and a find of 2 is the
useful signal.

Then fill the two written sections:

**`## Act now`** — the thing nothing else puts in front of the user. The
`ready` queue **oldest first** with ages and scores, the count of rows past
`thresholds.velocity_sla_days`, and any reply the user owes someone from phase
2. If the queue is empty, say so plainly; that is a good day.

**`## Headline`** — 2–3 sentences: what was reconciled, what was found, what
needs the user today.

Rewrite `STATUS:` to `complete` or `partial — <what failed>`, then write
`runs/{RUN_ID}.md` per `/hunt` §4 — durations from the events table, not
impressions.

## 6. If the run was not complete

Append an entry to `reports/pending_suggestions.md` per that file's contract
(symptom, checkable evidence, proposed target, `Status: pending`) — checking
first for an existing pending entry with the same target and symptom, which
gets a `Recurrence:` line instead of a duplicate. Then note in Degradations:
`Proposed improvements pending your approval: reports/pending_suggestions.md
(N entries) — run /optimise to triage`. Runs propose, `/optimise` reports, the
user approves.

## Stdout summary (always end with this)

```
Cycle: runs/cycle_{date}.md  [{STATUS}]  ({intensity}, {E} min)
Reconciled: A applied, P proposed for you   Marked missed: X
New jobs: F found, M shortlisted
Prepared: K  {or: skipped — ready queue at N/cap}
Act now: R ready to send (oldest {D}d)   Replies you owe: Q
Degradations: {count or none}
```
