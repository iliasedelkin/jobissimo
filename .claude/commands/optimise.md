# /optimise – analyze outcomes + run logs, propose improvements

Read the pipeline's own telemetry and outcomes, then propose evidence-backed
improvements as ready-to-apply diffs. **Targets: `config/`, `profile/`
(positioning, watchlist, knowledge-gap lists), and pack overrides — NEVER the
engine** (`engine/`, `scripts/`, `.claude/commands/`; engine changes go
upstream as PRs). **Never auto-apply anything** – the user approves per item;
apply only the approved ones.

## Inputs (read all)

- the full `events` table: `python3 scripts/db.py export-csv --out profile/state/backup`
  then read `events.csv` (and `jobs.csv` for the funnel)
- `python3 scripts/db.py dashboard` (current funnel)
- every `runs/*.md` run report
- every previous `reports/optimiser_*.md` (don't re-propose rejected ideas;
  check whether previously applied changes moved the numbers)
- `reports/pending_suggestions.md` – improvement proposals queued by runs that
  aborted or degraded. Treat each `pending` entry as a first-class candidate:
  verify its evidence against `events`, then either fold it into this report as
  a numbered suggestion or dismiss it. Set the entry's `Status:` to
  `promoted → Suggestion N (optimiser_{date}.md)` or `dismissed – {reason}` so
  it is not re-read next run. An entry with `Recurrence:` lines has fired more
  than once – weight it accordingly.
- every `applications/*/gap_suggestions.md`
- current `config/boards.yaml` tiers + ROI ledger, `config/targets.yaml`
  thresholds and calibration block, the active pack's `ats_synonyms.yaml` +
  locale bridges, `positioning/positioning_library.md`

## Setup

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)_optimise"
python3 scripts/db.py log --run-id $RUN_ID --command optimise --action run_start
```

## Analysis – three lenses

### 1. Funnel + calibration

- Conversion at each stage: found → scored → shortlisted → generated → ready
  → applied → responded → interview/offer.
- Scoring calibration:
  - scored-yes-but-user-skipped (status `skipped`/`missed` with rec `yes`)
  - low-priority-but-applied
  - response rate vs `fit_score` band and vs `ats_score_det` / `ats_score_llm`
- Board ROI: per `source`, jobs found vs shortlisted vs applied vs responses.
- → propose concrete edits to the tier assignments and ROI ledger in
  `config/boards.yaml` and to the thresholds/geography in
  `config/targets.yaml` (including its `/optimise`-owned calibration block —
  this is where observed response evidence lives).

### 2. Asset effectiveness

- Response rate vs ATS score band (det and LLM grade).
- Recurring missing keywords across `ats_report.md`s and evidence maps.
- Aggregate `gap_suggestions.md` items: which no-evidence requirements recur?
- → propose: additions to `positioning/positioning_library.md`, new synonym
  entries as a **pack override in config** or an upstream pack PR (wording
  bridges only – never a synonym that would claim an unproven skill), and a
  list of knowledge-gap items the user could evidence and then add to
  `knowledge/` (with what evidence each needs) — queue them in
  `knowledge/_queue.yaml` so /enrich surfaces them.

### 3. Pipeline friction

- From `events` and run reports: error patterns, retries, failed boards,
  long durations, repeated forced transitions, audit-failure hotspots.
- → for config-side friction, propose config diffs. For engine-side friction
  (command file wording, script behaviour), write the finding up as a
  candidate upstream issue/PR in the report — never edit the engine locally.

## Output – `reports/optimiser_{YYYY-MM-DD}.md`

Structure every suggestion like this, grouped by target file:

```
### Suggestion N – {one-line title}
Target: {file path — config/, profile/, or "upstream: <engine path>"}
Evidence: {the numbers/rows/events that justify it}
Change (ready to apply):
```diff
- old line
+ new line
```
(or exact replacement text for additions)
Decision: [ ] approve  [ ] reject
```

End the report with a short "previously applied changes – did they work?"
section comparing against the prior report's metrics where possible.

## Apply phase (only after user approval)

Walk the user through suggestions (AskUserQuestion or plain chat), apply the
approved diffs exactly, and log each:

```bash
python3 scripts/db.py log --run-id $RUN_ID --command optimise \
  --action suggestion_applied --detail '{"target":"config/...","suggestion":N}'
```

Rejected suggestions get `--action suggestion_rejected` so future runs don't
re-propose them.

## Stdout summary (always end with this)

```
Optimiser report: reports/optimiser_{date}.md
Suggestions: N (funnel: A, assets: B, friction: C)
Applied: X  Rejected: Y  Pending: Z
Key metric snapshot: applied={..} response_rate={..}% best_board={..}
```
