# Language Rules

How asset generation handles the JD's language (`jd_language` on the job row,
ISO 639-1: `en`, `it`, `de`, ...). Principle: **the candidate-facing content
speaks the JD's language; the structural skeleton stays canonical** so the
deterministic audit/ATS chain keeps working unchanged.

Two configuration sources drive this file:

- `config/languages.yaml` — which languages this install applies in, and the
  candidate's **declared proficiency** per language (CEFR).
- `packs/<pack>/locales/<code>.yaml` — per-market conventions: personal-details
  block, photo expectation, CV length norms, formality register, and the
  locale's ATS synonym bridges. A locale marked `verified: false` is a stub:
  it falls back to neutral behaviour and never invents a convention.

## Determining the language

1. `db.py get <job_id>` → `jd_language`.
2. If NULL: detect from `jd_texts/{job_id}.md` (the language of the verbatim
   Responsibilities/Requirements – ignore boilerplate), then record it:
   `python3 scripts/db.py set-field --job-id <id> jd_language <code>`.
3. Mixed-language postings (local-language intro, English requirements are
   common): use the language of the requirements section; mention the choice
   in notes.md.
4. If the detected language is not in `config/languages.yaml`, stop and ask
   the user — never generate an application in a language whose proficiency
   was not declared.

## What is written in the JD language

| Asset | Language |
|---|---|
| `cv_draft.md` summary + experience bullet text | JD language |
| CV headline | JD language only if a fact-checked equivalent exists; otherwise keep the positioning_library headline (many role titles, e.g. "Product Owner", are used untranslated across markets) |
| `cover_letter_draft.md` | JD language, entirely |
| `recruiter_message.md` | JD language |
| `follow_up.md` | language of the original application |
| `notes.md`, `gap_suggestions.md`, `jd_analysis.md`, `evidence_map.md` | English – internal artifacts |

## Register cap — never write above the candidate's proficiency

The candidate has to defend every line of the application in an interview.
Read the declared CEFR level from `config/languages.yaml` and cap the register:

- **C1+**: full professional register.
- **B2**: plain, concrete sentences the candidate would write themselves — no
  ornate constructions, no idioms they would not use.
- **B1 and below**: short declarative sentences only; prefer to flag in
  notes.md that interview prep must account for the language.

Flag in notes.md whenever an application is generated in a non-primary
language so interview prep accounts for it.

## Optional personal-details block (locale-driven)

Some markets conventionally include a personal-details block (date of birth,
residence/authorization status) on the CV; in others the same block is an
age-discrimination anti-pattern that screeners may down-rank. This is a
**locale decision, never a global one**:

- The active pack's `locales/<code>.yaml` declares `personal_details_block:
  conventional | anti_pattern | unknown` and which fields it covers.
- Append the block only when the locale says `conventional`, **and** the
  values exist in `applicant_profile.yaml`. Include only fields that are
  present; omit the whole block if none are.
- A stub locale (`verified: false`) or `unknown` → no block (neutral fallback).
- Format: `**Label:** value` lines, **never `- ` bullets** — `audit.py`
  requires a `<!-- src:ID -->` knowledge trace on every `- ` bullet, and
  personal data has no knowledge source; a `- ` bullet would fail the audit
  and a fabricated trace would breach truth guardrails. `parse_cv_skills` is
  scoped to `## Skills`, so `**Label:**` lines here are ignored by the skills
  check.
- Header stays canonical English (`## Personal Details`); values in the JD
  language. The block goes after `## Awards` (outside the name→Summary
  contact block, which audit requires to be exactly the 3-line header).

The shipped `it` locale records the block as conventional (with the reasoning);
Anglo-market locales record it as an anti-pattern. See `docs/languages.md` for
how to verify a stub.

## What stays canonical (NEVER localize)

- **Section headers**: `## Summary`, `## Experience`, `## Skills`,
  `## Education`, `## Awards` – audit.py and ats_score.py key on these, and
  English headers are standard ATS-safe practice in non-English tech CVs.
- **Dates**: `(Mon YYYY to Mon YYYY)` / `(Mon YYYY to Present)` with English
  month abbreviations (Jan…Dec). The range connector "to" and "Present" stay
  canonical English even in a non-English CV – never localize them
  (e.g. no `(mar 2021 al presente)`). The audit keys on this form.
- **Skills-section item names**: verbatim from `knowledge/skills_inventory.md`
  (they are industry-English terms; audit validates exact names).
- **Contact block** structure; employer names; technology names; all numbers.

## Truth guardrails apply to translation

Translating a bullet is a *paraphrase within fact boundaries*
(truth_guardrails § Allowed transformations): every number, technology,
employer, title, date, and mechanism stays identical – only the connective
language changes. Translation must never smuggle in a stronger claim
(rendering "supported" with a verb that means "led" is a violation). The
audit's numeric check works on translated bullets because numbers are
immutable.

## Evidence map & ATS scoring in non-English

- `jd_wording` stays near-verbatim from the JD – so for a non-English JD the
  keywords are in that language, and the CV (same language) matches them
  naturally.
- The pack locale's synonym bridges map common JD vocabulary in that language
  into the English taxonomy groups so the JD-vocabulary layer still extracts
  meaningfully. `/optimise` proposes new bridges when a language shows
  recurring unmatched vocabulary. A bridge maps **wording only** — the same
  evidenced skill, never a neighboring one.
- The LLM rubric pass judges the assets in the JD's language directly.
