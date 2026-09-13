# /prepare – generate + audit + ATS-score + export

Turn shortlisted jobs into audited, ATS-scored, export-ready application
folders: evidence map → drafts → truth audit (hard gate) → hybrid ATS scoring
→ targeted regeneration → export. All paths are workspace-relative
(`$JOBISSIMO_HOME`; see `scripts/paths.py`).

## Input

One of:
- a single `job_id`
- a list of `job_id`s
- filters, e.g. `--priority high --recommendation yes`
- `--fixture` – run the chain against a bundled sample JD (used by /setup's
  first-result milestone; uses the top target's matching JD from `fixtures/`)
- **default (no input):** every job with `status = shortlisted`

Find candidates with `python3 scripts/db.py list --status shortlisted [...filters]`.

The user may also paste open-ended application-form questions for a job
(found manually on the employer's form – see /hunt's shortlist summary).
Before anything else, save them **verbatim** to
`jd_texts/{job_id}_questions.md` (one `## Q<n>` per question, noting any
stated character limit). They are answered in step 2c.

**Driving factors (motivation input).** The candidate may supply a genuine
reason this specific company/problem/role matters to them – the "human centre"
of the cover letter (see `engine/rules/cover_letter_playbook.md` § Driving
factors). Two entry points, both persist the motivation to
`jd_texts/{job_id}_motivation.md` so it is woven into the whole prep for that
job (cover-letter P1 + notes.md § Why this role) and reused by any later
regeneration:
- **With the prep request** (or a pre-existing `jd_texts/{job_id}_motivation.md`):
  build cover-letter paragraph 1 around it from the start.
- **After assets are already prepared** – the common case: the user hands you
  a driving factor in chat and asks to regenerate. First write it verbatim to
  `jd_texts/{job_id}_motivation.md`, then regenerate `cover_letter_draft.md`
  only (re-run audit → export; CV and other assets unchanged unless asked),
  and refresh notes.md § Why this role. This is a targeted regeneration, not a
  full re-prepare.
It is user-authored truth (opinion/preference); never invent a motivation the
candidate has not expressed.

## Hard rules (truth guardrails outrank everything)

- Follow `engine/rules/truth_guardrails.md` absolutely: select/rephrase source
  bullets from `knowledge/`, never invent facts, never combine metrics across
  bullets, never claim unproven skills.
- A keyword whose evidence_map status is `no_evidence` is **never** inserted
  into the CV – even if it costs ATS points. Record it in
  `gap_suggestions.md` instead.
- Audit failures surface to the user for `fix / bypass / halt` – never
  silently fixed. Truth audit is a hard gate before ATS scoring.
- All state changes via `scripts/db.py`. Never edit the DB directly.

## Setup

**Sync freshness (warn only, never block).** Run `python3 scripts/sync.py
status` once at the start; if the DB and CSVs are out of sync, a remote is
ahead, or the last write came from another machine, surface a one-line warning
and suggest `/sync pull`, then proceed. `/prepare` never pulls, pushes, or
blocks on sync state — only `/sync` touches a remote.

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)_prepare"
python3 scripts/db.py log --run-id $RUN_ID --command prepare --action run_start \
  --detail '{"selection":"..."}'
```

Read once per run: `knowledge/master_experience.md`,
`knowledge/skills_inventory.md`, `knowledge/education_credentials.md`,
`positioning/positioning_library.md`, `positioning/candidate_profile.md`,
`positioning/role_order.md`, `engine/rules/truth_guardrails.md`,
`engine/rules/tailoring_rules.md`, `engine/rules/style_and_ats_rules.md`,
`engine/rules/cover_letter_playbook.md`, `engine/rules/jd_analysis_schema.md`,
`engine/rules/language_rules.md`, `config/languages.yaml`.

## Per job

Create the folder `applications/YYYY-MM-DD_{job_id}_{company_slug}_{role_slug}/`
(today's date; slugs lowercase-hyphenated, max 30 chars). Record it:

```bash
python3 scripts/db.py set-field --job-id <id> application_folder "applications/<folder>"
```

If `original_url` is NULL and the job is still active, backfill it now
(employer-site URL + ats_platform) the same way `/hunt` § Originate does.

**JD verbatim pre-flight:** check `jd_texts/{job_id}.md` § Raw text. If the
section is missing or suspiciously short (<200 words and shorter than the
structured sections), the JD is condensed and every downstream score would be
computed against incomplete text. Before generating anything: re-fetch the
posting from `original_url` (browser/web) and replace Raw text verbatim; if
the posting is unreachable (expired, login-walled), tell the user and ask them
to paste the full text – generation proceeds against the old extract only if
the user explicitly says so, and the run report records it.

**Language:** read `jd_language` from `db.py get <job_id>`. If NULL, detect it
from `jd_texts/{job_id}.md` and record it
(`db.py set-field --job-id <id> jd_language <code>`). ALL candidate-facing
assets (CV content, cover letter, recruiter message, later follow_up.md) are
written in that language per `engine/rules/language_rules.md` – section
headers, dates, and skills-inventory item names stay canonical English;
internal artifacts (jd_analysis, evidence_map, notes, gap_suggestions) stay
English. Translation is paraphrase within fact boundaries: numbers,
technologies, employers, titles, and dates are immutable. Cap the register at
the declared proficiency in `config/languages.yaml`. When the active pack's
locale for that language declares a conventional personal-details block,
append it per language_rules (populated from `applicant_profile.yaml`;
`**Label:**` lines, never `- ` bullets; never in locales where it is an
anti-pattern).

### 1. Evidence map first

- Write `jd_analysis.md` from `jd_texts/{job_id}.md` + the job's scored row
  (`db.py get <job_id>`), conforming exactly to
  `engine/rules/jd_analysis_schema.md`. If DECISION: REJECT → log, skip job,
  continue.
- Write `evidence_map.md`: one `| REQ-NNN | jd_wording | kind | priority |
  status | evidence_refs | cv_action |` row for every explicit JD requirement,
  skill, tool, methodology, and high-value keyword.
  - `status` ∈ explicit_match | implicit_match | no_evidence
  - `priority` ∈ must | preferred | nice | context
  - `cv_action` ∈ use_summary | use_experience | use_skills |
    cover_letter_only | gap_only | omit
  - `no_evidence` terms can never enter the CV.
  - `jd_wording` is the compact near-verbatim keyword/term, not the full
    requirement sentence.

### 2. Generate drafts

Per the rules files read at setup:

- `cv_draft.md` – `<!-- src:BULLET_ID -->` on every bullet, exactly one ID
  each; summary carries `<!-- claims:IDs -->`. Mandatory pre-audit checks:
  three-line contact block (`# {identity.full_name}` / headline / contact
  line) then `## Summary`; all dates `(Mon YYYY to Mon YYYY)` or
  `(Mon YYYY to Present)`; no `--` in role headers; no ASCII hyphen year
  ranges; **no em dashes (—)** in any generated content — use en dash (–)
  with a space on each side as the content separator; hyphens (-) remain
  correct for compound words.
- `cover_letter_draft.md` – `<!-- claims:IDs -->` per factual claim, per
  `engine/rules/cover_letter_playbook.md` (150–220 words, 3 paragraphs, human
  centre first). If `jd_texts/{job_id}_motivation.md` exists, build paragraph
  1 around it verbatim as the human centre; otherwise fall back per the
  playbook. Do not raise gaps in the letter (playbook § Handling gaps).
- `recruiter_message.md` – 80–120 words: who+role / strongest proof point
  (with `<!-- claims:ID -->`) / low-friction ask.
- `notes.md` – 50–100 words: **Why this role / Emphasize if contacted
  (2–3 bullet IDs) / Watch points**.
- `gap_suggestions.md` – whenever the evidence map has `no_evidence` rows:
  no-evidence JD requirements, knowledge-database candidates, development
  suggestions. Advisory only; never merged into the CV unless evidence is
  first added to `knowledge/`. Recurring gaps also feed the enrichment queue
  (`knowledge/_queue.yaml`) so /enrich surfaces them.

### 2b. Pre-score jd_wording verbatim check

Before auditing, for every **must-have** REQ row in `evidence_map.md`, verify
the `jd_wording` phrase appears verbatim (case-insensitive) in `cv_draft.md`.
If a phrase does not appear:
- Either insert it naturally into the summary or a bullet (within fact
  boundaries), OR
- Simplify the `jd_wording` to a shorter phrase that does appear.

This prevents the most common cause of sub-75 first-pass ATS scores and
avoids the discover-only-after-scoring iteration cycle.

### 2c. Application-form answers (only if questions exist)

If `jd_texts/{job_id}_questions.md` exists (captured by /hunt §3e or pasted
by the user), write `application_answers.md` in the application folder:
question verbatim, then the drafted answer, for every question.

**Voice – it should read like the candidate typed it into the form, not
like marketing copy:**

- Brief: 60–120 words per answer, or the form's stated limit if smaller.
- Plain first person, conversational register; contractions are fine; vary
  sentence length; one concrete detail beats three adjectives.
- **No em-dashes (—) and no `--`**; use en dash (–) with spaces, commas, or full stops.
- No AI-polish stock phrases ("I'm thrilled", "deeply resonates",
  "leverage my skill set", "align with your mission"). Slightly imperfect
  and direct is the goal; do not sand every edge.
- Written in `jd_language`, same as the other candidate-facing assets.

**Truth boundary (guardrails outrank voice):** every factual claim –
employers, roles, dates, numbers, tools, skills – comes only from
`knowledge/`, `applicant_profile.yaml`, and `positioning/`. The allowed
"tiny bit of imagination" covers **opinions, motivations, preferences, and
connective phrasing only** – never new facts, never metric recombination,
never unproven skills. If a question cannot be answered truthfully from the
sources (e.g. asks for experience the candidate lacks), write
`[NEEDS USER INPUT: ...]` instead of inventing.

audit.py does not scan this file: after drafting, do a manual truth
self-check of every claim against the evidence map and note
`self-check: pass` (or the open issues) in the file header, together with
"draft – review and submit manually". The user sends these answers
themselves; /apply may reuse them at form-fill time but never invents
beyond them.

### 3. Truth audit (hard gate)

```bash
python3 scripts/audit.py --folder applications/<folder> --write-log
```

- PASS → continue to ATS scoring.
- FAIL → present **each** failed item to the user and wait for a disposition:
  - `fix` → minimal correction, rerun audit
  - `bypass` → record the explicit user override in `audit_log.md` (check
    stays FAIL with override, never becomes PASS)
  - `halt` → stop this job, set `db.py log ... --action halted`
- Record the result: `python3 scripts/db.py set-field --job-id <id> audit_status pass|fail|bypassed`

### 4. ATS score (hybrid)

Deterministic:

```bash
python3 scripts/ats_score.py --folder applications/<folder> --jd jd_texts/{job_id}.md
```

→ 0–100 + per-dimension breakdown + `ats_report.md`. Two keyword layers:
(1) requirement coverage from the evidence-map REQ rows, and (2) JD-vocabulary
coverage – hard/soft skill terms extracted from the JD text, classified via
the active pack's `ats_keywords.yaml` and matched with stemming + the pack's
synonym tables (base + locale bridges). The report lists every missing term:
REQ rows with their id, taxonomy terms flagged BLOCKED when their
evidence-map status is no_evidence. It scores `cv_draft.md` (the live
iteration artifact), not a previously exported final.

LLM rubric pass (in-chat, no script): judge (a) semantic relevance of the
summary to the JD's top priorities, (b) evidence strength vs those
priorities, (c) narrative coherence. Output a grade **A–D** and a targeted
fix list in the form "REQ-007 unmet; bullet E12 covers it, swap into
Experience".

### 4b. Evidenceable-keyword incorporation (truth-gated)

Before the regeneration loop, read `ats_report.md`'s "Missing JD-vocabulary
terms" table. For each non-BLOCKED term:
- If the competency is evidenced in `skills_inventory.md` or a matched
  `evidence_map.md` REQ row → weave the **literal term** into the summary or a
  bullet within fact boundaries (use `positioning/positioning_library.md`
  § Canonical ATS phrasings). Skills-section items must match an exact
  `skills_inventory.md` name (audit hard rule, `audit.py`).
- If `no_evidence` / domain-specific → add to `gap_suggestions.md`, never the CV.

This closes the gap between internal coverage and external ATS without touching
truth guardrails: only already-evidenced vocabulary is surfaced. No metric
recombination, no new facts. Re-run `audit.py` after incorporation.

### 5. Targeted regeneration loop (max 2 iterations)

If det score < the configured threshold
(`config/pipeline.yaml → thresholds.ats_min_score`, default **75**) **or**
grade < B:

- Apply only the targeted fixes – edit flagged sections/bullets, never
  whole-CV rewrites.
- Rerun `audit.py` (hard gate again), then `ats_score.py`.
- `no_evidence` keywords stay out no matter the score – gap_suggestions.md.

Store results:

```bash
python3 scripts/db.py set-field --job-id <id> ats_score_det <N>
python3 scripts/db.py set-field --job-id <id> ats_score_llm "B"
python3 scripts/db.py set-field --job-id <id> ats_iterations <0|1|2>
```

### 6. Export + status

```bash
python3 scripts/export.py --folder applications/<folder>      # finals + DOCX (+PDF)
python3 scripts/db.py set-status --job-id <id> --status generated --run-id $RUN_ID
python3 scripts/db.py set-status --job-id <id> --status ready --run-id $RUN_ID
```

Log per-job event: `--action job_prepared --detail
'{"audit":"pass","ats_det":82,"ats_llm":"B","iterations":1,"duration_s":300}'`.

## Overdue follow-up sweep (always, at the end)

For every job where `status = applied`, `follow_up_date <= today`, and no
`follow_up.md` exists in its `application_folder`: generate `follow_up.md`
(60–100 words: reference role + date applied; one fit sentence from
notes.md § Emphasize if contacted; polite close). Log
`--action follow_up_generated`.

Find them: `python3 scripts/db.py list --status applied` then check
`follow_up_date` via `db.py get`. The dashboard's "overdue follow-ups"
section lists them directly.

## Wrap-up

Write `runs/{RUN_ID}.md` (jobs processed, audit outcomes, scores, iterations,
fix/bypass decisions, durations, errors). Then `python3 scripts/db.py dashboard`.

## Stdout summary (always end with this)

```
Prepared: N applications
| job_id | lang | audit | det score | grade | iterations | folder |
|---|---|---|---|---|---|---|
...
Pending user decisions: K (listed above, fix/bypass/halt)
Application answers drafted: Q (application_answers.md – review before sending)
Follow-ups generated: Z
Skipped (REJECT at evaluation): W
Run report: runs/{RUN_ID}.md
```
