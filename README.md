# Jobissimo

An agent-operated job-search pipeline: it finds postings, scores them for fit,
generates truth-audited ATS-optimized applications, tracks outcomes, and
improves itself from its own telemetry. Plain-markdown slash commands hold the
judgement; a handful of deterministic Python scripts hold anything that must be
exact — lifecycle state, truth auditing, ATS scoring, export. Built for
[Claude Code](https://claude.com/claude-code); runnable by any capable LLM
agent.

## The principle

> **Truth guardrails outrank ATS score.** The system is a librarian, not an
> author: it selects and rephrases real bullets from your own knowledge base.
> It never invents a fact, never combines metrics across two bullets, never
> claims an unproven skill. A keyword with no evidence goes to a gaps file,
> never into the CV — even when it costs points.

Everything else in this project exists to serve that line. It is enforced
mechanically by `scripts/audit.py`, which is a hard gate before scoring and
export, and it is not configurable.

## Pipeline

```
/setup     documents first → extract knowledge → minimum config → first result
              ↓
/hunt      browse: extract JD → score → find employer URL → record
              ↓ (shortlisted | discarded)
/prepare   evidence map → drafts → truth audit (hard gate) → ATS score →
           targeted regeneration → export to DOCX/PDF → ready
              ↓
/apply     assisted browser form-fill (stretch; NEVER submits autonomously)
              ↓
/track     natural-language outcome updates → dashboard
              ↓
/optimise  funnel + run telemetry → evidence-backed improvement diffs
           (to config/profile/pack — never the engine; user approves each)

/enrich    answer the highest-impact profile gaps in five minutes
/dashboard read-only pipeline views any time
/refresh   liveness check on open postings; mark dead ones missed
/brief     the daily pass: mail scan → hunt → dashboard → one morning brief
/doctor    config health, value provenance, drift detection
```

**Lifecycle:** `found → scored → discarded | shortlisted → generated → ready →
applied → responded → closed` (+ `on_hold`, `missed`, `skipped`). Transitions
are validated by `scripts/db.py`; `closed` carries an outcome
(no_response / rejected / interview / offer / withdrawn).

## Requirements

- **Python 3** — standard library only for the core scripts; no pip install.
- **[pandoc](https://pandoc.org/)** for DOCX export; an optional PDF engine
  ([tectonic](https://tectonic-typesetting.github.io/), xelatex, or
  LibreOffice) for PDF. Neither is required to run the pipeline or the tests.
- **An LLM agent** to run the commands — designed for Claude Code.
- **A browser is optional.** Discovery works through a logged-in browser, a
  headless one, plain HTTP fetch (company career pages + public ATS board
  APIs), or fully manual URL paste — whichever your session has.

## Install

```sh
git clone https://github.com/iliasedelkin/jobissimo.git
cd jobissimo
python3 scripts/scrub_check.py --install-hook      # PII pre-commit gate
python3 -m unittest discover -s tests -p 'test_*.py'   # optional: verify offline
claude                                              # or your agent of choice
```

Then, inside the agent:

```
/setup
```

## First run

`/setup` asks for **documents before questions**. Drop in every CV you have
(any format, any language), a LinkedIn export, old cover letters, project
READMEs, and job descriptions of roles you want — the more the better,
because the differences between CV versions are signal. It extracts
everything it can, shows you a completeness ledger, and asks you only to
**correct** what it got wrong rather than compose from scratch. Then it
generates a real, truth-audited, ATS-scored CV and cover letter against a
sample posting so you see a result in the first session.

Target: about fifteen minutes from `/setup` to a scored draft when you supply
one decent CV. Everything not needed for that first result is deferred to a
queue that `/enrich` and the dashboard keep surfacing later.

```
$ /setup
Setup: 8/8 (deferred: targets 2-3, metric rescue, watchlist)
Ingested: 3 documents (en, it) → 3 roles, 9 bullets, 8 skills (6 evidenced)
Profile strength: 71/100
First result: audit PASS, ATS 93/100 (≥75 ✓)
  applications/2026-01-15_sample001_nimbus-metrics_product-manager/
Next: /hunt · /enrich · /dashboard
```

## Commands

| Command | What it does |
|---|---|
| `/setup` | Configure the pipeline from your own documents; reach a first result |
| `/enrich` | Answer the highest-impact profile gaps in five minutes |
| `/hunt` | Find, score, and record postings in one pass; originate employer URLs |
| `/prepare` | Evidence map → drafts → truth audit → ATS score → export |
| `/apply` | Assisted form-fill; hard stop before submit (never autonomous) |
| `/track` | Natural-language outcome updates → dashboard |
| `/optimise` | Analyze telemetry; propose approved-per-item improvements |
| `/dashboard` | Read-only funnel, stats, lists, single-job views |
| `/refresh` | Verify open postings are still live; mark dead ones missed |
| `/brief` | The daily pass: mail scan → hunt → dashboard → one brief |
| `/doctor` | Config health, value provenance, drift detection |

## How it works

Four config layers resolve last-wins: **engine** (scripts, command files,
rules — maintained here), **pack** (a domain's role clusters, ATS lexicons,
board catalogue, locale conventions — community-contributed), **config** (this
install's identity, targets, languages, boards — written by `/setup`), and
**profile** (your knowledge base and every generated artefact). A pack is
never edited in place; a user override lands in `config/`. `/optimise` only
ever proposes changes to config, profile, and pack overrides — never the
engine — and never applies anything without your approval. See
[docs/architecture.md](docs/architecture.md).

## Configuration

Everything specific to you lives in `config/` (identity, targets, languages,
boards, capabilities) and `profile/` (knowledge, positioning, artefacts).
**Both are gitignored**; only the `*.example.yaml` templates are committed.
`/doctor` explains where any config value came from — which setup stage wrote
it, from what evidence, when.

## Languages

The pipeline generates each application in the **posting's language**, while
section headers, dates, and skills-inventory names stay canonical English so
the deterministic audit/ATS chain keeps working. It never writes above the
proficiency you declared — you have to defend every line in an interview.
Market conventions (does a CV carry a date-of-birth block here? a photo?) are
per-locale: `en` and `it` ship verified, `de/fr/es/nl/pt` ship as neutral
stubs. Adding or verifying a locale is a small, high-impact contribution —
see [docs/languages.md](docs/languages.md).

## Packs

A **domain pack** is the role family the pipeline targets: its role clusters
and canonical competencies, ATS keyword/synonym lexicons, board catalogue,
evaluation rubric, and locale conventions. `product` (product/analyst roles)
ships as the reference pack; `generic` is a minimal fallback. Building a pack
for your domain is the highest-value contribution — see
[docs/packs.md](docs/packs.md).

## Privacy

All personal data lives under `config/` and `profile/`, both gitignored.
Nothing is uploaded anywhere — the pipeline talks only to the job boards and
mailbox you point it at, and only reads (never sends) mail. A `scrub_check.py`
pre-commit hook blocks personal strings (emails, phone numbers, profile
handles, job-ids) from ever entering a commit, and CI re-runs it over the
whole tree and full history.

## Limits and ethics

- **No autonomous submission, ever.** `/apply` stops before submit with a
  screenshot and a field-by-field summary naming each value's source; a human
  clicks submit. This is a project boundary, not a setting.
- **No captcha or interstitial bypass.** A Cloudflare challenge is logged and
  skipped, never worked around.
- Respect each board's terms of service and rate limits. A browser adapter
  means *you, driving your own logged-in session* — not a scraper.
- Single-user, personal use.
- **The truth guardrails are not configurable.** A fork that weakens the
  audit, automates submission, or bypasses site protections is a different
  project.

## Contributing

The two highest-value paths are **new domain packs** and **verifying a locale
stub**. See [CONTRIBUTING.md](CONTRIBUTING.md). No personal data in PRs, ever;
run `tests/` and `scrub_check.py` before opening one.

## License

MIT — see [LICENSE](LICENSE).
