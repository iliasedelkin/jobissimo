# Architecture

Jobissimo splits cleanly into two halves: **judgement** (plain-markdown slash
commands an LLM agent executes) and **exactness** (deterministic Python
scripts). The agent never writes SQL or invents facts; the scripts never make
a judgement call. Everything a human would want to be provably correct —
lifecycle state, the truth audit, the ATS score, export — is a script. The
score sits between them: `ats_score.py` is deterministic, and a separate
in-chat LLM rubric pass grades semantic fit.

## The four-layer config model

Resolution order, last wins. A layer is only written by its owner.

| Layer | Holds | Written by | Committed |
|---|---|---|---|
| **Engine** | `scripts/`, `.claude/commands/`, `engine/rules/`, `engine/schemas/` | maintainers | yes |
| **Pack** | `packs/<name>/` — role clusters, ATS lexicons, board catalogue, locale conventions, evaluation rubric | community PR | yes |
| **Config** | `config/` — this install's identity, targets, languages, boards, capabilities | `/setup`, `/optimise` (approved) | **no** |
| **Profile** | `$JOBISSIMO_HOME` — knowledge, positioning, every generated artefact | the user and the pipeline | **no** |

Why it matters: the personal-data rule becomes mechanical. Everything private
lives under two gitignored roots (`config/` and `profile/`), and
`scripts/paths.py` resolves `$JOBISSIMO_HOME` (default `./profile`) so every
script and command goes through one place. Multiple workspaces become free,
which is how the migration parity check runs against a copy of a real
workspace without touching live data (`$JOBISSIMO_HOME=/copy …`).

`scripts/packs.py` implements the layering: it reads the active pack plus the
config overrides, using a small stdlib YAML subset parser (no PyYAML
dependency). `db.py` validates role clusters and location-fit values against
**pack ∪ config UNION values already present in the DB**, so a workspace
imported from another install never fails validation on a historical value.

## The scripts

| Script | Role |
|---|---|
| `paths.py` | Resolves `$JOBISSIMO_HOME` / `$JOBISSIMO_CONFIG`; every path goes through it |
| `packs.py` | Pack loader + config layering (the mini-YAML reader) |
| `db.py` | The only write path to `state/pipeline.db`; enums + transition matrix |
| `audit.py` | The truth audit (hard gate); also `--library` mode for positioning at birth |
| `ats_score.py` | Deterministic 0–100 hybrid scorer |
| `export.py` | Trace-strip → pandoc DOCX/PDF (audits first) |
| `intake.py` | Document → text + provenance manifest |
| `competency_map.py` | Deterministic competency map from knowledge/ |
| `coverage.py` | Completeness ledger + profile strength score + enrichment queue |
| `setup_check.py` | Config validator + drift detector (backs `/doctor`) |
| `scrub_check.py` | PII gate + pre-commit hook |
| `migrate.py` | Import a pre-OSS workspace (shipped, not run) |

## The ATS scorer, in one paragraph

Two keyword layers. The **requirement layer** is the evidence-map REQ rows —
what the JD demands, matched against the CV. The **JD-vocabulary layer**
extracts salient uni/bigrams from the JD text itself (frequency ≥ 2,
boilerplate removed), classifies them hard/soft via the pack's
`ats_keywords.yaml`, and matches them against the CV with light stemming plus
the pack's `ats_synonyms.yaml` (and per-language locale bridges). Extracting
from the JD — rather than intersecting a curated list with the JD — is
deliberate: a curated list understates the domain vocabulary a candidate
lacks and inflates coverage toward 100%. A `no_evidence` keyword still counts
against coverage but is flagged BLOCKED and never inserted: truth outranks the
score.

## Data flow for one prepared application

```
jd_texts/{id}.md ─┐
db.py get {id} ───┼─► jd_analysis.md ─► evidence_map.md ─┐
knowledge/ ───────┘                                       ├─► cv_draft.md
positioning/ ─────────────────────────────────────────────┘   cover_letter_draft.md
                                                                      │
                          audit.py (hard gate) ◄────────────────────┘
                                │ PASS
                          ats_score.py + LLM rubric ─► (regenerate ≤2×)
                                │
                          export.py ─► cv.docx/pdf, cover_letter.docx/pdf
                                │
                          db.py set-status ready
```
