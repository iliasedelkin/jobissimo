# /dashboard – pipeline stats and views (read-only)

Show pipeline state. Translate the user's request into the right read-only
`scripts/db.py` calls and relay the output. This command never mutates
anything – status *changes* belong to `/track`.

## The three views

| User wants | Run |
|---|---|
| Actionable overview (default, no arguments) | `python3 scripts/db.py dashboard` – funnel + shortlisted-to-prepare + ready-to-apply + overdue follow-ups |
| Aggregate stats / conversion / ROI | `python3 scripts/db.py stats [filters]` – funnel %, applications→responses→interviews, per-source ROI, fit/ATS score averages, outcomes, overdue follow-ups |
| A concrete list of jobs | `python3 scripts/db.py list [filters]` – sortable table (priority → fit → date) |
| Everything about one job | `python3 scripts/db.py get <job_id>` |

## Filters

`stats` and `list` accept, in any combination:

- `--since YYYY-MM-DD` – only jobs found on/after that date (resolve phrases
  like "this month", "last two weeks" to a real date from today)
- `--source <slug>` – e.g. `linkedin`, or any slug from `config/boards.yaml`
- `--status <s>` – repeatable, e.g. `--status applied --status responded`
- `--priority high|medium|low`
- `list` only: `--recommendation yes|maybe|no`

## Translation examples

| User says | Run |
|---|---|
| "/dashboard" | `db.py dashboard` |
| "show me stats" / "how's the funnel" | `db.py stats` |
| "stats for linkedin since mid-May" | `db.py stats --source linkedin --since <YYYY-05-15>` |
| "what did I apply to?" | `db.py list --status applied --status responded --status closed` |
| "high-priority stuff still waiting" | `db.py list --status shortlisted --status ready --priority high` |
| "response rate by board" | `db.py stats` → read the Per source table |
| "why was X discarded?" | `db.py get <job_id>` → `rejection_reason` |
| "what's overdue?" | `db.py stats` → Overdue follow-ups section (or dashboard) |

Resolve company names to job_ids via `db.py list` output. If a request mixes
viewing with an update ("show stats and mark X applied"), do the update via
the `/track` procedure first, then show the view.

## Stdout summary (always end with this)

Relay the db.py output verbatim (it is already formatted markdown). **Keep
every `https://` URL line intact — do not summarize them away.** Terminal
emulators typically only make literal `https://` URLs clickable (not
embedded/markdown links), so those lines are the user's click-through to each
posting. Then one line:

```
View: dashboard|stats|list|get  Filters: {filters or none}  Jobs in scope: N
```
