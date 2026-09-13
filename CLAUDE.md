# Jobissimo — Agent-Operated Job-Search Pipeline

Engine operating contract. An LLM agent (built for Claude Code, runnable by
any capable agent) finds postings, scores them for fit, generates
truth-audited ATS-optimized applications, tracks outcomes, and improves the
pipeline from its own telemetry. Plain-markdown slash commands hold the
judgement; a handful of deterministic Python scripts hold anything that must
be exact — lifecycle state, truth auditing, ATS scoring, export. The agent
never writes SQL; the scripts never make judgement calls.

All personal data and generated artefacts live under one gitignored workspace
root, `$JOBISSIMO_HOME` (default `./profile`, resolved by `scripts/paths.py`).
Nothing personal is ever committed.

## Pipeline map

```
/setup     documents first → extract knowledge → minimum config → first result
              ↓
/hunt      browse: extract JD → score → originate employer URL → record
              ↓ (status: shortlisted | discarded)
/prepare   evidence map → drafts → audit.py (hard gate) → ats_score.py +
           LLM rubric → targeted regeneration (max 2) → export.py → ready
              ↓
/apply     assisted browser form-fill from profile + finals (stretch;
           NEVER submits autonomously)
              ↓
/track     natural-language outcome updates → db.py → dashboard
              ↓
/optimise  events + funnel + run reports + gap_suggestions → evidence-backed
           improvement diffs to config/profile/pack (user approves per item)

/enrich    answer the highest-impact profile gaps in five minutes
/dashboard read-only views any time: dashboard | stats | list | get
/refresh   liveness check on pre-application jobs → closed postings marked
           missed (employer-source evidence only; `links` mode for manual pass)
/brief     the daily pass: mail scan → hunt → dashboard → one morning brief
/doctor    config health, value provenance, drift detection
```

Commands live in `.claude/commands/` (Claude Code slash commands) as plain
markdown — runnable by any LLM agent by reading the file. Each is
self-sufficient given this file + the referenced `engine/rules/` files, and
ends with a "Stdout summary" spec.

## Lifecycle status enum

`found → scored → discarded | shortlisted → generated → ready → applied →
responded → closed` (+ `on_hold`, `missed`, `skipped`). Transitions are
validated by db.py; `closed` takes an `outcome`
(no_response/rejected/interview/offer/withdrawn).

## Invariants (non-negotiable)

1. **Truth guardrails outrank everything** — including ATS score.
   `engine/rules/truth_guardrails.md` is strict mode: select/rephrase source
   bullets from `knowledge/`, never invent facts, never combine metrics across
   bullets, never claim unproven skills. A keyword whose evidence-map status
   is `no_evidence` is never inserted into the CV; it goes to
   `gap_suggestions.md`.
2. **`scripts/db.py` is the only write path to the pipeline DB.** Never write
   SQL, never edit the DB file, never bypass with ad-hoc scripts.
3. **`discarded` is permanent** — it is the dedupe/no-rework record. `/hunt`
   checks `db.py urls` (which includes discarded) before extracting anything.
4. **Audit failures surface to the user** for `fix / bypass / halt` — never
   silently fixed. Bypass is recorded in `audit_log.md` and stays a FAIL with
   override. Truth audit is a hard gate before ATS scoring and export.
5. **No autonomous submission.** `/apply` hard-stops before submit: filled-form
   screenshot + field-by-field summary + explicit user confirmation. Form
   answers come only from `applicant_profile.yaml` + final assets +
   `knowledge/`; anything else → ask the user.
6. **`/optimise` never touches the engine.** It proposes changes to `config/`,
   `profile/`, and pack overrides — never to `engine/`, `scripts/`, or
   `.claude/commands/` — and never applies anything without per-item approval.
   A run that ends `aborted` or `partial` does not fix itself either: it
   appends a proposal to `reports/pending_suggestions.md` (contract in that
   file's header) and `/optimise` triages it. Runs propose, `/optimise`
   reports, the user approves.
7. **Guardrails are engine, never config.** Nothing under `config/` may weaken
   the truth audit, make the audit non-blocking, turn a bypass into a pass, or
   enable autonomous submission.
8. Evidence-map discipline (`/prepare` step 1): REQ rows with
   explicit_match/implicit_match/no_evidence status, `<!-- src:ID -->` trace
   comments on every CV bullet, deterministic validation before finalization.
   `jd_wording` is the compact near-verbatim keyword, not the full sentence.
9. **Assets speak the JD's language** (`jd_language` on the job row; see
   `engine/rules/language_rules.md`): CV content, cover letter, and recruiter
   message in the posting's language; section headers, dates, and
   skills-inventory names stay canonical English; internal artifacts stay
   English. Translation never changes a fact, and never exceeds the register
   the user declared in `config/languages.yaml`.
10. **Workspace state travels as CSV; the database is a local artefact.**
    `state/pipeline.db` is never committed — `db.py export-csv` writes the
    diff-friendly CSV record (jobs/events/id_reservations/meta + manifest) that
    is, and `db.py import-csv` rebuilds the DB. `/sync` is the only thing that
    commits or moves the workspace; no pipeline command syncs on its own, and
    divergent pipeline state is never auto-merged (show both sides, user picks).

## The four-layer config model

Resolution order, last wins. A layer is only written by its owner.

| Layer | Holds | Written by | Committed |
|---|---|---|---|
| Engine | scripts, command files, `engine/rules/`, schemas | maintainers | yes |
| Pack | role clusters, ATS lexicons, board catalogue, locale conventions, evaluation rubric | community PR | yes |
| Config | this install's identity, targets, languages, boards, capabilities | `/setup`, `/optimise` (with approval) | **no** — user's private repo |
| Profile | knowledge, positioning, and every generated artefact | the user and the pipeline | **no** — user's private repo |

A pack is never edited in place; a user override lands in `config/`. Config and
Profile live in the workspace (`$JOBISSIMO_HOME`, which contains `config/`) and
are versioned via `/sync` in the user's own private repo, never this public one;
the shipped config templates live in `templates/config/` (see `docs/sync.md`).

## Directory map

| Path | What |
|---|---|
| `.claude/commands/` | The slash commands (the pipeline logic) |
| `engine/rules/` | truth_guardrails, style_and_ats_rules, tailoring_rules, cover_letter_playbook, language_rules, jd_analysis_schema, jd_template |
| `engine/adapters/` | browse (claude-in-chrome / playwright / webfetch / manual), mail (gmail-mcp / imap / none), export (pandoc) |
| `engine/schemas/` | JSON Schema for the config files |
| `packs/product/` | The reference domain pack (roles, evaluation, ATS lexicons, boards, en/it locales verified + de/fr/es/nl/pt stubs) |
| `packs/generic/` | Minimal fallback; taxonomy generated at setup |
| `scripts/` | db.py, audit.py, ats_score.py, export.py, paths.py, packs.py, sync.py, intake.py, competency_map.py, coverage.py, setup_check.py, scrub_check.py, migrate.py (all have `--help`) |
| `templates/` | ats_reference.docx (clean metadata), knowledge scaffolds, `config/*.example.yaml` (shipped config templates), `workspace.gitignore` (written by `/sync init`) |
| `config/` (workspace) | GITIGNORED ENTIRELY — identity, targets, languages, boards, capabilities; lives in `$JOBISSIMO_HOME`, resolved via `$JOBISSIMO_CONFIG` → `<workspace>/config` → legacy `<repo>/config` |
| `profile/` | GITIGNORED ENTIRELY — `$JOBISSIMO_HOME` (resolved via `$JOBISSIMO_HOME` → `.jobissimo` pointer → default): `config/`, `_intake/`, `knowledge/`, `positioning/`, `competency_map.md`, `applicant_profile.yaml`, `setup_state.yaml`, `jd_texts/`, `applications/`, `runs/`, `reports/`, `state/pipeline.db` (+ `state/backup/*.csv`, the committed record) |
| `fixtures/`, `tests/` | Synthetic candidate (Sam Rivera) + JDs; offline test suite |

## Scripts

- `python3 scripts/db.py <cmd>` — add-job, score, set-status, set-field,
  list, get, next-id, urls, log, dashboard, stats, export-csv. Validates
  enums and transitions; role clusters and location-fit values validate
  against pack ∪ config UNION values already in the DB, so imported
  historical rows never fail. Refuses bad input loudly.
- `python3 scripts/audit.py --folder <app_folder> [--write-log]` — truth
  audit: traces resolve, skills evidenced, no metric recombination,
  no_evidence terms absent, contact block + date formats. `--library <file>`
  audits a generated positioning file at birth. Exit 1 = FAIL.
- `python3 scripts/ats_score.py --folder <app_folder> --jd jd_texts/{id}.md`
  — deterministic 0–100: evidence-map requirement coverage (25+5) and
  JD-vocabulary extraction (hard 20 / soft 10) via the pack's `ats_keywords`
  + `ats_synonyms` (+ locale bridges); plus structure (10), dates (10),
  quantified bullets (10), title (5), length (3), contact (2). Scores
  `cv_draft.md`.
- `python3 scripts/export.py --folder <app_folder>` — runs audit, strips
  traces to finals, pandoc DOCX via `templates/ats_reference.docx` (+PDF).
- `paths.py` resolves `$JOBISSIMO_HOME`; `packs.py` loads packs + config;
  `intake.py` converts documents to text; `competency_map.py` / `coverage.py`
  build the map + strength ledger; `setup_check.py` validates config;
  `scrub_check.py` is the PII gate (and pre-commit hook); `migrate.py` imports
  a pre-OSS workspace (shipped, not run).

## Quality bar for changes

Every script keeps `--help`. Every command file ends with a stdout-summary
spec. No command requires the user to remember more than the command name and
a job_id. New ATS keywords/synonyms go through `/optimise` evidence or a pack
PR, and a synonym must bridge wording only — never claim a neighboring skill.
The offline test suite (`tests/`) must pass, and `scrub_check.py --all` must
report zero findings, before anything is committed.
