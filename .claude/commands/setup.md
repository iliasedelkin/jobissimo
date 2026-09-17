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

## S-1 · Say the plan out loud, then follow it

Setup takes 25–30 minutes and has no UI. The only thing that makes that
tolerable is knowing the shape of it in advance, so print this before the
first question and get a "go":

> **Setting up takes about 25–30 minutes.** Here is the whole path, and what
> you are holding at the end of it.
>
> | # | Stage | You do | ~min |
> |---|---|---|---|
> | 1 | Set up your private workspace | pick where it lives | 2 |
> | 2 | Check the tools on this machine | nothing | 1 |
> | 3 | Collect your documents | point me at files or a folder | 3 |
> | 4 | Extract your career into a knowledge base | nothing — I read | 5 |
> | 5 | Correct what I got wrong | confirm or fix, five at a time | 6 |
> | 6 | Identity and logistics | short answers | 2 |
> | 7 | Languages and markets | confirm a proposal | 2 |
> | 8 | What you want to do, and where | the real decisions | 5 |
> | 9 | Build and audit your positioning | nothing — generated | 2 |
> | 10 | Find one real job and prepare for it | pick from a shortlist | 5 |
>
> **At the end you will have:** one real, live posting you chose, and a CV
> plus cover letter tailored to it — audited line by line against your own
> documents, ATS-scored, ready to send today.
>
> Stop whenever you like. Everything is written to disk as we go, and
> `/setup --resume` picks up from the stage you left.

Then print one line at every stage boundary, and nothing more:

```
[5/10 · Correct what I got wrong · ~11 min elapsed · next: identity and logistics]
```

If a stage runs long, say so and offer the queue rather than pressing on:
*"we are 18 minutes in and this is stage 5 of 10 — I can defer the rest of
these corrections to `/enrich` and take you straight to your first real
application."* Deferring is a first-class outcome, not a failure; the queue
exists precisely so the first session ends with something real in hand.

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

**Export is the one exception: prove it, don't probe it.** Discovery and mail
degrade gracefully; a CV that cannot become a DOCX is not a degraded
deliverable, it is no deliverable. `which pandoc` is not proof either — a
present pandoc with an unreadable reference doc fails the same way. Convert
something:

```bash
printf '# Smoke test\n\nOne line.\n' > /tmp/jobissimo_smoke.md
pandoc /tmp/jobissimo_smoke.md --reference-doc templates/ats_reference.docx \
  -o /tmp/jobissimo_smoke.docx && echo "DOCX OK"
```

If it fails, give the platform's install line before continuing:

| Platform | DOCX | PDF (optional) |
|---|---|---|
| macOS | `brew install pandoc` | `brew install tectonic` |
| Debian/Ubuntu | `sudo apt install pandoc` | `sudo apt install texlive-xetex` |
| Windows | `winget install JohnMacFarlane.Pandoc` | `winget install tectonic` |

A missing **PDF engine** is genuinely a warning — DOCX is the primary format
and most ATS prefer it. A missing **pandoc** blocks the first-result
milestone: record `tools.pandoc: false` and say plainly that `/prepare` will
stop at audited markdown finals until it is installed.

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

### S5b · Name the roles from the evidence, not from the catalogue

**Pack availability must not influence which roles are proposed.** Exactly one
substantial pack ships today (`packs/product`), so a catalogue-first
conversation steers every developer, designer, and marketer toward product
management — and scoring their evidence against a PM competency set produces a
confident-looking fit percentage that means nothing. Derive the candidates
from the user's own evidence first; pack coverage is a property of a candidate,
not the source of the list.

1. From the extracted roles, titles, and competencies, name the 3–5 role
   families the evidence actually supports, and say where each came from:
   *"six years shipping React and Node, two of them leading — frontend
   engineering and full-stack engineering both fit; your last two titles say
   'Product Engineer', which reads either way."*
2. Ask what they want next. Their answer outranks the evidence ranking —
   evidence says what is credible, never what is wanted.
3. **Then**, and only then, check pack coverage, and say it plainly:

   > `packs/product` covers product and analyst roles. Nothing ships for
   > frontend engineering yet, so I will build that cluster's competency set
   > from your own evidence and run on the generic pack. Everything works —
   > scoring, auditing, ATS — but the competency set and keyword lexicon will
   > be yours alone rather than community-reviewed.

4. For a covered role: set `pack:` accordingly in `config/pipeline.yaml`.
   For an uncovered one: `pack: generic`, derive the competency set from the
   user's evidence, and **write it to `config/roles.yaml`** — the cluster id
   alone is not enough, because the competency set is what S6 scores evidence
   fit against:

   ```yaml
   clusters:
     Frontend:
       title: Frontend Engineer
       competencies: [react, typescript, component architecture, ...]
   ```

   `scripts/packs.py` layers that over the pack and unions the id into the
   values `db.py` accepts (`templates/config/roles.example.yaml` has the full
   shape; `docs/packs.md` explains the layering). The same file extends a
   cluster the pack *does* define, when the user's evidence adds to it.
   `extra_role_clusters` in `config/pipeline.yaml` still registers a bare id
   with no competencies — use it only when there is genuinely nothing to
   record. **Never bend an uncovered role into a covered cluster because the
   covered one has a ready-made competency list** — that is how a designer
   ends up scored as a product manager.
5. Offer the contribution path once, then drop it: *"if this works for you,
   the competency set and lexicon we just built are most of a pack —
   `CONTRIBUTING.md` has the shape, and it is the most useful thing you could
   send back upstream."*

### S6 · Targets, top one first

**Ask these four before ranking anything, and never infer them from a CV.**
Where intake suggests an answer, offer it as a default to confirm or overwrite
— a visible default is a proposal, an invisible one is an assumption.

1. **Where can you actually work?** Base city, and which of onsite / hybrid /
   remote you will take (`geography.work_modes`). If onsite or hybrid is in
   the list, ask how far is too far (`geography.max_commute_minutes`).
2. **Would you relocate, and where to?** "No" is a complete answer, and it
   narrows the hunt usefully.
3. **What kind of engagement?** Full-time, part-time, contract, freelance,
   internship — any combination (`employment.types`). Ask explicitly whether
   any of them is a hard no: those go to `employment.exclude` and are skipped
   at hunt time rather than scored down. A student wanting internships and a
   principal who would never take one both have to say so; the pipeline must
   not assume permanent full-time.
4. **Anything that rules a company out?** Sector, stage, size,
   return-to-office mandates (`company_preferences.avoid`).


Multiple ranked targets is the normal case, but only the top one is needed
for the first result. For each candidate target show three axes and let the
user rank:

- **Desire** — the user rates it 1–5. Theirs alone.
- **Evidence fit** — computed from the competency map against that cluster's
  canonical competency set in the pack's `roles.yaml`, or against the
  evidence-derived set written in S5b when no pack covers the cluster: a coverage
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

**One real job, applied-ready, before setup ends.** No sample, no dry run —
the thing the agenda promised. A fixture application costs the same full
generation chain and produces something the user cannot send anywhere.

```bash
/hunt --first-run --limit 5
```

`--first-run` is a bounded hunt: score candidates against `targets.yaml` until
five have been evaluated, then stop and show them ranked, with fit scores and
reasons. The user picks one; run `/prepare <job_id>` on it — the ordinary
chain, no special flag.

**If none of the five clears the bar** — and only on this first hunt, once —
offer the loosening explicitly, rather than silently widening the search or
leaving the user with nothing to show for half an hour:

> None of the five postings I scored clears your bar (fit ≥ {threshold}).
> On day one that usually means the targets are tight, not that the market is
> empty. For this first run only, I can relax {the specific axis: seniority
> band / geography / must-signals} to {value} so you finish with a real
> application in hand. Your saved criteria do not change — this affects this
> one hunt.

Name the axis and the value; never loosen silently, and never loosen twice.
Log it so `/optimise` can later see whether day-zero targets are
systematically too tight:

```bash
python3 scripts/db.py log --run-id $RUN_ID --command setup \
  --action first_run_criteria_loosened \
  --detail '{"axis":"seniority_band","from":"mid-senior","to":"mid"}'
```

If the user declines, end setup cleanly on *"profile ready, no match yet — run
`/hunt` tomorrow"*. Do **not** fall back to the fixture.

Then show them the CV, the cover letter, the audit verdict and the score.

**Acceptance: audit PASS and deterministic ATS ≥ 75 first pass** — the same
threshold `/prepare` uses to decide whether to regenerate. Below it, name
the stage to revisit: a low keyword score points at S2/S3 coverage; a low
structure score at S7; a low quantified-density score at the metric-rescue
queue.

Then hand over with the three things that actually happen next:

1. Send it. The DOCX and PDF are in the application folder; `/track` records
   what happens next.
2. Run `/hunt` tomorrow — discovery is a daily habit, not a one-off.
3. Run `/enrich` when you have ten minutes — here is your profile strength
   score and the answers that would raise it most. `/dashboard` any time.

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
