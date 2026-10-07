# Jobissimo

An agent-operated job-search pipeline: it finds postings, scores them for fit,
generates truth-audited ATS-optimized applications, tracks outcomes, and
improves itself from its own telemetry. Plain-markdown slash commands hold the
judgement; a handful of deterministic Python scripts hold anything that must be
exact — lifecycle state, truth auditing, ATS scoring, export. Runs in
[Claude Code](https://claude.com/claude-code) and
[Codex](https://developers.openai.com/codex) from the same files; runnable by
any capable LLM agent.

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
/cycle     the scheduled pass: reconcile → hunt → prepare → one report
/doctor    config health, value provenance, drift detection
```

**Lifecycle:** `found → scored → discarded | shortlisted → generated → ready →
applied → responded → [offered →] closed` (+ `on_hold`, `missed`, `skipped`).
Transitions are validated by `scripts/db.py`; `closed` carries an outcome
(no_response / rejected / interview / offer_accepted / offer_declined /
offer_withdrawn / withdrawn). Each interview round and offer figure is a row
in the stage ledger (`db.py stage`), so the funnel shows how deep each process
went.

## Requirements

- **Python 3** — standard library only for the core scripts; no pip install.
- **[pandoc](https://pandoc.org/)** for DOCX export; an optional PDF engine
  ([tectonic](https://tectonic-typesetting.github.io/), xelatex, or
  LibreOffice) for PDF. Neither is required to run the pipeline or the tests.
- **An LLM agent** to run the commands — Claude Code or Codex (see
  [Running with Codex](#running-with-codex)).
- **A browser is optional.** Discovery works through a logged-in browser, a
  headless one, plain HTTP fetch (company career pages + public ATS board
  APIs), or fully manual URL paste — whichever your session has.

## Install

New to all this? **[docs/getting-started.md](docs/getting-started.md)** walks
through everything, from installing Claude Code or Codex to connecting the
browser and mail to the first `/setup`. The short version, for an agent you
already have:

```sh
git clone https://github.com/iliasedelkin/jobissimo.git
cd jobissimo
python3 scripts/scrub_check.py --install-hook      # PII pre-commit gate
python3 -m unittest discover -s tests -p 'test_*.py'   # optional: verify offline
claude                                              # or: codex
```

Then, inside the agent:

```
/setup          # Claude Code
$setup          # Codex
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

Claude Code takes them as `/name`, Codex as `$name`. Arguments are the same
(`/prepare 0123` ≙ `$prepare 0123`).

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
| `/cycle` | The scheduled pass: reconcile, hunt, prepare, one report (daily or weekly) |
| `/doctor` | Config health, value provenance, drift detection |

## Running with Codex

Codex reads `AGENTS.md` (the operating contract; `CLAUDE.md` imports the same
file) and runs each command through a thin skill in `.agents/skills/<name>/`.
The skill points at the same `.claude/commands/<name>.md` that Claude Code
uses, so the pipeline logic, guardrails, and scripts are identical in both
agents. Full details: [docs/codex.md](docs/codex.md).

**1. Install, then open the repo root and trust the project**

```sh
npm install -g @openai/codex  # or: brew install --cask codex — or the ChatGPT desktop app
cd jobissimo
codex
```

Trusting the project also loads `.codex/rules/jobissimo.rules`, so the
pipeline scripts run without approval prompts, as in Claude Code.

**2. Give Codex your workspace and the network.** Codex's default sandbox
writes only inside the repo and blocks network access from the shell.
`$setup` creates your workspace as a sibling directory by default
(`python3 scripts/paths.py` prints it once it exists), and the public ATS-API
fetches and `/sync` need the network. Add this to your personal
`~/.codex/config.toml` before `$setup`, then restart Codex. Never commit it
here.

```toml
[sandbox_workspace_write]
writable_roots = ["/absolute/path/to/your/jobissimo-workspace"]
network_access = true
```

For a single session, `codex --add-dir /absolute/path/to/workspace` does
the same for writes.

**3. Optional: browser and mail**

- **Browser (ChatGPT desktop app only):** in **Computer Use**, install the
  ChatGPT browser extension, then @-mention the browser in chat
  (`$hunt @Chrome`). It drives your own logged-in Chrome (`codex-chrome`
  adapter). The Codex CLI has no browser integration; a headless Playwright
  MCP is the CLI option.
- **Mail:** install the **Gmail** plugin and connect the mailbox that gets
  your job alerts (read-only by contract). Otherwise use `imap` or nothing.

Neither is required: without a browser, discovery runs on public ATS APIs and
pasted URLs, and preparing applications is unaffected.

**4. Run it**

```
$setup                        # once: documents → knowledge → config → first result
$hunt                         # find and score postings
$prepare <job_id>             # tailored, truth-audited, ATS-scored CV + letter
$apply <job_id>               # assisted form-fill; you click submit
$track <what happened>        # "rejected by Acme", "interview with Nimbus Friday"
$cycle                        # or all of the above as one daily pass
$dashboard                    # where things stand
```

Unattended: run `codex exec --sandbox workspace-write '$cycle'` from the repo
root (see [docs/scheduling.md](docs/scheduling.md)). CLI runs have no browser,
so the hunt uses public ATS APIs and mail.

**Differences from Claude Code**

- Questions come as plain chat.
- The Chrome plugin asks before it types personal data into a form.
- Everything else, including the truth audit and the stop before submit,
  behaves the same.

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

Everything specific to you lives in your workspace (`$JOBISSIMO_HOME`):
identity, targets, languages, boards, and capabilities in `config/`, and
knowledge, positioning, and artefacts alongside them. **It is all gitignored by
this public repo**; the shipped `*.example.yaml` templates live in
`templates/config/`. `/doctor` explains where any config value came from —
which setup stage wrote it, from what evidence, when.

## Sync and backup

Because the workspace is gitignored, it is also unbacked-up by default. `/sync`
makes it **its own private git repo** with a private remote, entirely separate
from this public one, so you can version it and move it between machines
without any risk of personal data reaching the public repo. The pipeline
database is treated as a runtime artefact: `db.py export-csv` commits a
diff-friendly CSV record, `db.py import-csv` rebuilds the DB on the other
machine. Engine changes still flow here as ordinary commits. See
[docs/sync.md](docs/sync.md).

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
