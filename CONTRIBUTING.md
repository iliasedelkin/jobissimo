# Contributing to Jobissimo

Two contribution paths are genuinely valuable and easy to get right. Start
with one of these.

## New domain packs (highest value)

The `product` pack targets product/analyst roles. Most other role families —
data engineering, design, marketing, sales, finance, ops — need their own
pack. A pack lives under `packs/<name>/` and is pure config; you do not touch
the engine.

Files (schema: `engine/schemas/pack.schema.json`):

- **`pack.yaml`** — manifest: name, description, and `figure_nouns` (nouns
  that make a number a "figure" for the audit's repeated-figure check, e.g.
  `months`, `deploys`, `campaigns`).
- **`roles.yaml`** — role clusters. Each cluster has an id (the value
  `db.py` accepts for `role_cluster`), a title, a **canonical competency
  set** (what `/setup` scores a candidate's evidence fit against), and
  adjacent clusters.
- **`evaluation.md`** — the fit rubric. Keep the candidate's own numbers out
  of it: baseline years and geography belong in a user's `config/targets.yaml`,
  not the pack.
- **`ats_keywords.yaml`** — the hard/soft skill lexicon. Remember the scorer
  extracts keywords from each JD itself; this file only *classifies* extracted
  terms and boosts known ones. Keep `soft_skills` accurate.
- **`ats_synonyms.yaml`** — wording bridges. **A synonym bridges wording
  only, never a neighbouring skill.** `product management` ↔ `product manager`
  is a bridge; `SQL` ↔ `Python` is a truth violation. This rule is not
  negotiable — a bad synonym silently defeats the truth guardrails.
- **`boards.yaml`** — a board catalogue with factual access notes and neutral
  yield guidance (company-direct above aggregators; new aggregators on
  probation). Do not encode your own outcome numbers — those are a user's
  private telemetry.
- **`locales/<code>.yaml`** — see below.

## Locale conventions (small, well-scoped, high-impact)

The pipeline generates applications in the posting's language, and market
conventions differ: a date-of-birth block on a CV is conventional in some
markets and an age-discrimination anti-pattern in others. The `product` pack
ships `en` and `it` **verified**; `de`, `fr`, `es`, `nl`, `pt` ship as
**stubs** (`verified: false`) that fall back to neutral behaviour.

Verifying a stub for a market you know is a great first contribution:

1. In `packs/<pack>/locales/<code>.yaml`, set `verified: true` and fill
   `personal_details_block` (`conventional` | `anti_pattern` | `unknown`),
   `photo`, `cv_length_norm`, `formality`.
2. Add `synonyms:` bridges for common JD vocabulary in that language →
   English taxonomy groups (wording only).
3. State *why* a convention holds — a one-line rationale ("conventional in
   {market}; an anti-pattern in Anglo markets") is what makes the file
   trustworthy. See `locales/it.yaml`.

## Other contributions

- **Adapters** (`engine/adapters/`) — new browse/mail/export backends, same
  capability contracts.
- **Engine changes** — welcome, with the parity requirement: a change to
  `audit.py` or `ats_score.py` **must ship updated fixture expectations** in
  `tests/` and say why the score/verdict moved. An unexplained score change is
  a regression, not an improvement.
- **Docs.**

## Public change, private evidence

Your workspace is a separate private repo (`/sync`, see `docs/sync.md`); only
engine and pack changes belong in a public PR. The subtle case is a pack
improvement *learned from* private data — e.g. an `/optimise` run noticing that
Italian postings keep using a term the lexicon lacks. **The change is public;
the evidence is not.** Contribute the pack diff with aggregate justification
only ("14 postings across 3 months, 0 matched the lexicon"); the full evidence,
with company names and job ids, stays in your workspace's `reports/`. Never put
a company name tied to an outcome, a job id, or any personal token in a public
diff or commit message.

## Ground rules

- **No personal data in PRs — including in test fixtures.** Fixtures are
  clearly fictional (see `fixtures/`). Run `python3 scripts/scrub_check.py --all`
  before opening a PR; CI enforces it over the tree and full history.
- Run the offline suite before opening a PR:
  `python3 -m unittest discover -s tests -p 'test_*.py'`.
- A behaviour change needs a fixture test.
- Conventional-commit subjects; no personal data in commit messages.

## Not accepted

- Anything that weakens the truth guardrails (a non-blocking audit, a bypass
  that becomes a pass, a synonym that claims a neighbouring skill).
- Anything that automates form submission or removes the `/apply` hard stop.
- Anything that bypasses site protections (captcha/interstitial solving,
  agent-rotation, disguised fetching), or ignores `robots.txt` / rate limits.
- Telemetry, analytics, or any network call the user did not initiate.
