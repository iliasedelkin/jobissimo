# Configuration

Everything specific to an install lives in the gitignored workspace
(`$JOBISSIMO_HOME`, default `./profile`): `config/` (this install's settings)
and the knowledge base and every generated artefact alongside it. None of it is
committed to this public repo; the shipped config templates live in
`templates/config/`, and the workspace is versioned in the user's own private
repo via `/sync` (see [sync.md](sync.md)).

`/setup` writes all of these; you can also edit them by hand. `/doctor`
validates them and explains where any value came from.

## config/ files

| File | Schema | Holds |
|---|---|---|
| `pipeline.yaml` | `engine/schemas/pipeline.schema.json` | identity (name, years), pack selection, mail account, thresholds (ATS min, shortlist cap, velocity SLA) |
| `targets.yaml` | `engine/schemas/targets.schema.json` | geography, seniority baseline, company preferences, ranked targets with per-language queries, the `/optimise`-owned calibration block |
| `languages.yaml` | `engine/schemas/languages.schema.json` | application languages + declared CEFR proficiency (the register cap) |
| `boards.yaml` | `engine/schemas/boards.schema.json` | this install's tiered board list + ROI ledger |
| `capabilities.yaml` | — | detected tools + chosen adapters (browse/mail/export) |

Copy a shipped template into your workspace config dir, or run `/setup`:

```sh
cp templates/config/pipeline.example.yaml "$JOBISSIMO_HOME/config/pipeline.yaml"  # then edit, or let /setup fill it
```

## $JOBISSIMO_HOME (the workspace)

Default `./profile`. Override to run against a copy (e.g. for the migration
parity check) without touching live data:

```sh
JOBISSIMO_HOME=/tmp/parity-copy python3 scripts/audit.py --folder applications/...
```

Layout: `_intake/` (raw documents + extracted text + manifest), `knowledge/`
(master_experience, skills_inventory, education_credentials, unevidenced,
`_queue.yaml`), `positioning/` (candidate_profile, role_fit_map,
positioning_library, motivations, role_order, company_watchlist),
`competency_map.md`, `applicant_profile.yaml`, `setup_state.yaml`,
`jd_texts/`, `applications/`, `runs/`, `reports/`, `state/pipeline.db`.

## Who may write what

- **`/setup`** writes config and profile.
- **`/enrich`** and `/prepare`/`/hunt`/`/track` write profile.
- **`/optimise`** proposes changes to config, profile, and pack overrides —
  never the engine — and applies only what you approve, per item.
- **You** may edit anything. If you hand-edit `knowledge/`, `/doctor` will
  notice the competency map is stale and tell you to re-run
  `scripts/competency_map.py`.

## Provenance

Every extracted fact carries a `<!-- from:{src_id}#{locator} -->` comment
back to a source document (indexed in `_intake/manifest.yaml`). Every config
value's origin is recorded in `setup_state.yaml` (which stage wrote it, when,
from what inputs). Ask `/doctor` "where did `<value>` come from?" and it
answers from those records.
