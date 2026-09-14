# /setup – configure the pipeline from the user's own documents

Build this install's knowledge base, config, and positioning — documents
first, questions second — and reach a **first result** (a generated,
truth-audited, ATS-scored CV + cover letter the user can read) in the first
session. Target: ~15 minutes from `/setup` to a scored draft when the user
supplies one decent CV.

## The UX contract (priority order)

1. **Documents first, questions second.** Ask for files before asking
   anything else; extract everything extractable before the first question.
   The user should feel the system did the work and is now checking its own
   homework — not that it is interviewing them from zero.
2. **A real result in the first session.** Everything not strictly required
   to reach the first-result milestone is deferred to the queue, not skipped.
3. **Continuous, prompted enrichment.** Deferred items go onto
   `knowledge/_queue.yaml` with impact estimates; `/enrich`, `/prepare`, and
   the dashboard keep surfacing them at the moment they become relevant.
4. **Transparent and resumable.** Show what you are about to write before
   writing it. Every extracted fact carries provenance
   (`<!-- from:{src_id}#{locator} -->`). Checkpoint every stage in
   `profile/setup_state.yaml` (status pending/done/deferred, timestamp,
   content hash of its inputs). `/setup --resume` continues from the first
   non-done stage; `/setup --stage <name>` redoes one stage.

Truth guardrails apply from the first minute: extraction never invents,
never merges facts across sources into one bullet, never rounds a number.

---

## Phase A — Ingest (no questions but one)

### S-0 · Workspace first — before anything is written

Your career data and this engine repo are two different things, and setup is
where they get separated. The engine stays a clean checkout the user can
`git pull` and open pull requests from; everything about them lives in their
own private repo. Nothing personal may be written until that exists.

```bash
python3 scripts/paths.py        # resolved workspace + which rule resolved it
```

If the reported source is `default <repo>/profile` and that directory is not
already a git repo, **no workspace has been established — stop and run
`/sync init`.** It owns the placement decision (relocated sibling directory,
recommended, vs in place) and the `git clean -xfd` warning that goes with the
in-place choice. Relay that decision to the user; do not choose for them.

Say why, in one sentence, before asking: *"Everything I learn about you goes
into your own private repo, separate from this one — so you can update the
engine and contribute back without your CV ever being part of it."*

Do not continue until `paths.py` reports a `.jobissimo pointer` or
`JOBISSIMO_HOME env` source, or the in-place workspace is a git repo.

At the end of setup, verify the separation actually held:

```bash
git -C "$(git rev-parse --show-toplevel)" status --porcelain
```

Empty is the expected result. Anything listed means setup wrote into the
engine checkout — name those files to the user rather than letting them
discover it at their next `git pull`.

### S0 · Preflight

Probe before asking anything: `python3 scripts/setup_check.py` plus direct
checks — `python3 --version`, `pandoc -v`, a PDF engine
(tectonic/xelatex/libreoffice), `pdftotext`, and which agent capabilities
exist in this session (a browser MCP, a mail tool, web fetch, OCR). Write
`config/capabilities.yaml`:

```yaml
tools: {pandoc: true, pdf_engine: false, pdftotext: true}
adapters: {browse: claude-in-chrome | playwright | webfetch | manual, mail: gmail-mcp | imap | none}
```

Show an honest degradation table — e.g. *"no browser adapter found: discovery
will run on email alerts and public ATS job-board APIs; everything downstream
is unaffected"* — and move on. **Never block on a missing capability.**

### S1 · Bring everything you have

One prompt, deliberately wide:

> Drop in anything that says something about your career. Multiple CVs are
> better than one — different versions emphasise different things, and the
> differences are signal. Any format, any language.
>
> Useful: CVs and résumés (PDF, DOCX, ODT, RTF, MD, TXT, HTML, or a
> photo/scan), a LinkedIn data export (the ZIP or just `Positions.csv` /
> `Profile.csv` / `Skills.csv`), old cover letters, performance reviews,
> project READMEs, a portfolio or personal site URL, a GitHub profile,
> certificates, and job descriptions of roles you wanted — those tell me
> what to aim at.
>
> Point me at a folder and I will take everything in it.

Run `python3 scripts/intake.py <paths...>` on whatever arrives (folder, file
list, pasted text via `--text`, URLs fetched then piped in). Each source gets
a stable `src_id` in `profile/_intake/manifest.yaml` with format, detected
language, word count and SHA. Scanned documents go through OCR when
available; when not, say so and ask for a text version rather than guessing.

Nothing is interpreted at this stage. Its only job is to give every fact an
address to point at later.

### S2 · Extract everything extractable

Build the knowledge base in the schema of `templates/knowledge/` (read those
scaffolds for the exact shape):

- One `ROLE_ID` per role in `knowledge/master_experience.md`; bullets as
  `{ROLE_ID}-NNN`, each with **Tags** (competencies), **Facts** (atomic,
  immutable claims), **Phrasings** (1–3 pre-approved wordings), and a
  provenance comment `<!-- from:{src_id}#{locator} -->`.
- **Never merge facts from two sources into one bullet.** That is precisely
  the metric-recombination failure the auditor exists to catch; creating it
  at intake poisons everything downstream. Same fact in two sources → one
  bullet, both provenance refs. Different facts → different bullets.
- Capture every number verbatim with its unit and scope. Rounding at
  extraction becomes a truth violation later.
- Vague content — "improved efficiency", "worked with stakeholders" — is not
  a fact. It becomes a queued question, not a bullet.
- Titles get a canonical form plus explicitly approved alternates, because
  `tailoring_rules` §10 may only choose among alternates that exist here.
- Skills claimed anywhere are collected in `knowledge/skills_inventory.md`
  but **not yet CV-eligible**: a skill becomes eligible only when it cites at
  least one bullet ID. Unevidenced ones go to `knowledge/unevidenced.md`,
  permanently CV-ineligible until evidenced.
- Education, credentials, awards → `knowledge/education_credentials.md` with
  `EDU-*` ids.
- Deduplicate across CV versions: same role, different wording → merge the
  wordings into `Phrasings`, keep the union of facts; flag contradictions
  (different dates, different figures for the same claim) with a
  `CONTRADICTION:` note for S3.

Then run `python3 scripts/coverage.py` and show the **completeness ledger**:
roles, bullets, % carrying a metric, skills evidenced vs claimed, identity
fields, contradictions, and the **profile strength score**. Every gap lands
in `knowledge/_queue.yaml` with an impact estimate and estimated time to
answer.

---

## Phase B — Minimum viable config (target: ten minutes)

Ask only what generation cannot proceed without.

### S3 · Confirm and correct

Show what was extracted, grouped by role, and ask the user to **correct
rather than compose** — correcting a wrong extraction is far cheaper than
answering an open question. Lead with the contradictions found in S2.
Batches of five items at a time; **write to disk after every batch**, never
accumulate for one write at the end — setup gets interrupted, and a lost
round is a round the user redoes.

### S4 · Identity and logistics

Only what the contact block and `/apply` need: name, contact, links, work
authorisation, notice period, salary floor, relocation stance. Write
`profile/applicant_profile.yaml` (see `templates/knowledge/` for the shape)
and `config/pipeline.yaml` (identity.name, years_experience, pack, mail
account if a mail adapter exists). Anything the user cannot confirm is
written with `confirm: true` so `/apply` asks before ever using it. Anything
not needed for the first result is deferred to the queue.

### S5 · Languages and markets

Do not ask a monolingual user to configure a language matrix.

1. **Propose, don't interrogate.** From the intake manifest's detected
   languages, the user's declared languages, and the target geography,
   propose the set: *"Your CVs are in English and Italian and you are
   targeting Italy and remote-EU — shall I set up applications in English
   and Italian?"*
2. **Per language, capture proficiency (CEFR)**, and apply this rule:
   **never generate an application in a register above the user's actual
   proficiency in that language** — they have to defend every line of it in
   an interview. B2 means plain, concrete sentences the user would write
   themselves. Record the level; the CV and cover-letter generators read it.
3. **Per language, load market conventions** from
   `packs/<pack>/locales/<code>.yaml`: personal-details block, photo
   expectation, length norms, formality. A stub (`verified: false`) falls
   back to neutral behaviour and never invents a convention — tell the user
   so, and point at CONTRIBUTING.md if they can verify it.
4. **Preserve the canonical/localised split exactly** as
   `engine/rules/language_rules.md` defines it (headers, dates,
   skills-inventory names canonical; candidate-facing content localised;
   internal artifacts English).
5. **Wire the ATS layer**: each configured language pulls its synonym
   bridges from the pack locale automatically (scripts/packs.py).
6. Write `config/languages.yaml`. One language configured → the pipeline
   never raises the topic again; `/doctor --languages` reopens it.

### S6 · Targets, top one first

Multiple ranked targets is the normal case, but only the top one is needed
for the first result. For each candidate target show three axes and let the
user rank:

- **Desire** — the user rates it 1–5. Theirs alone.
- **Evidence fit** — computed from the competency map against that cluster's
  canonical competency set in the pack's `roles.yaml`: a coverage
  percentage, the specific gaps, and a verdict of *credible now* /
  *credible with framing* / *stretch*.
- **Market volume** — one live probe per target through the configured
  browse adapter: how many matching postings exist in the target geography
  in the last 30 days. A beloved target with four postings a month is worth
  knowing on day one. Skip silently if no adapter can probe.

Write `config/targets.yaml` (schema: `engine/schemas/targets.schema.json`):
geography, seniority baseline, company preferences, and ordered targets —
each with cluster id, rank, share of hunt slots, seniority band and stretch
policy, title synonyms and per-language search queries, must-signals,
reject-signals, positioning cluster, and optional `experiment: true` with a
tranche cap (below-level applications are a controlled experiment with a
declared cap, not a habit).

Targets 2..n can be deferred; say so explicitly and queue them.

### S7 · Auto-generate positioning for the top target (no questions)

- `python3 scripts/competency_map.py` — deterministic map: per competency,
  declared level, recency, evidence count and bullet IDs, metric-bearing
  evidence, and a derived tier (*core* = 3+ evidenced bullets, at least one
  metric-bearing, used within two years; then *supporting*, *contextual*,
  *gap*). Tiers come from evidence weight, not self-assessment.
- Generate `positioning/candidate_profile.md` from the map.
- Generate a `positioning/positioning_library.md` section for the top
  target: headline variants, two or three summary variants at different
  emphases, and a proof-point priority list naming bullet IDs.
- Generate `positioning/role_order.md`: role ordering decisions (dual-role
  periods, education-vs-experience calls, early-career collapse) and the
  § Always include credential list — the per-candidate decisions
  `tailoring_rules` §3/§7 read.
- **Audit the library at birth.** Every generated line carries
  `<!-- claims:IDs -->`; run
  `python3 scripts/audit.py --library <tmp file>` **before the file reaches
  its final path**. A positioning library that fails its own audit poisons
  every application downstream, so it never lands unaudited.

### S8 · Boards, defaulted

Take the pack's `boards.yaml` filtered by `targets.yaml` (languages,
geography) and `capabilities.yaml` (drop boards the available adapters
cannot reach), write a working `config/boards.yaml`, and move on. Live
probing and re-tiering are Phase C — the user does not need a tuned board
list to see their first generated CV.

---

## ✦ First result milestone

Run `/prepare --fixture`: the full generation chain — evidence map → drafts
→ truth audit → ATS score → export — against the bundled sample JD matched
to the top target (`fixtures/`), using the user's real profile. Show them
the CV, the cover letter, the audit verdict and the score.

**Acceptance: audit PASS and deterministic ATS ≥ 75 first pass** — the same
threshold `/prepare` uses to decide whether to regenerate. Below it, name
the stage to revisit: a low keyword score points at S2/S3 coverage; a low
structure score at S7; a low quantified-density score at the metric-rescue
queue.

Then hand over with the three things that actually happen next:

1. Run `/hunt` — discovery starts now.
2. Run `/enrich` when you have ten minutes — here is your profile strength
   score and the answers that would raise it most.
3. `/dashboard` any time.

---

## Phase C — Depth, on the user's schedule (never blocking)

Each item is a `knowledge/_queue.yaml` entry with an impact estimate:

| What | Why deferred | Surfaced by |
|---|---|---|
| Remaining targets | Only the top one is needed to start | `/enrich`, and `/hunt` when a good posting matches an unconfigured target |
| Metric rescue | One question per unquantified bullet: what changed, and by how much? "No number exists" is a valid answer and marks the bullet qualitative | `/enrich`; `/prepare` when quantified-density costs points |
| Skills evidence audit | Most CVs lose 20–30% of claimed skills here — high value, but not blocking | `/enrich`; `/prepare` when a JD wants a skill sitting in `unevidenced.md` |
| Proficiency calibration | Challenge inconsistencies aloud: *"advanced SQL, but no bullet mentions a query — which role was that?"* A challenged claim gains evidence or loses its level | `/enrich` |
| Motivations | The cover-letter human centre. **User-authored only** — the one file the pipeline is forbidden to populate. Until it exists, letters fall back to a role-or-problem centre grounded in a real fact about the company | `/prepare` before the first letter for a company the user cares about |
| Company watchlist | The highest-converting source class | `/enrich`; `/hunt` after a company appears twice |
| Board probing and tiering | Score each candidate board on role × region × language × access cost × date visibility, probe the top ones, record measured yield. Tier discipline once running: tier 1 every run; tier 2 one rotating probe per run logged even when barren; two consecutive barren probes demote to tier 3; company-direct above aggregators; diversity a target, not a gate | `/optimise` after ~20 jobs of telemetry |

## Setup state

`profile/setup_state.yaml` records per-stage
`{status: pending|done|deferred, at: <timestamp>, input_hash: <hash>}` so
`/doctor` can detect drift — knowledge hand-edited, competency map now
stale, positioning citing a bullet ID that no longer exists.

## Stdout summary (always end with this)

```
Setup: {stages done}/{stages total} (deferred: {list or none})
Ingested: N documents ({languages}) → {roles} roles, {bullets} bullets, {skills} skills ({evidenced} evidenced)
Profile strength: {score}/100
First result: audit {PASS|FAIL}, ATS {score}/100 {(≥75 ✓)|(below bar — revisit {stage})}
  {application folder path}
Queue: {K} items, top impact: {one-line prompt}
Next: /hunt · /enrich · /dashboard
```
