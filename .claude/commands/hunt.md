# /hunt – scrape + score + originate in one pass

Find new job postings, extract each into `jd_texts/`, score it immediately,
originate the employer-site URL for keepers, and record everything in the
pipeline DB via `scripts/db.py`. One pass per job – no intermediate CSVs, no
separate scoring run.

Discovery uses whichever browse adapter `config/capabilities.yaml` records
(see `engine/adapters/`): a logged-in browser is richest; webfetch covers
company-direct pages and ATS board APIs; with the `manual` adapter the user
supplies URLs and everything below still applies. All paths below are
workspace-relative (`$JOBISSIMO_HOME`, default `./profile` — see
`scripts/paths.py`).

## Parameters (defaults)

- `target_count` – qualifying postings to collect (default **10**)
- `max_age_days` – skip postings older than this (default **7**; compute the
  cutoff date from today's date at run time – never hardcode a date)
- `boards` – optional subset of the tiers in `config/boards.yaml`
- `time_budget_min` – wall-clock ceiling for the whole run (default **45**;
  a scheduled `/brief` run may set its own). On reaching the budget, stop the
  source loop where it is, finish the job currently in flight, and go
  straight to §4 Wrap-up with whatever has been collected. A short run that
  reports is worth more than a complete run that misses the window.

## Hard rules

- **db.py is the only write path to state.** Never edit the DB file
  directly, never write SQL.
- A URL already known to the DB (including `discarded` jobs) is never
  re-extracted. Discarded is permanent.
- JD files capture the **full posting text verbatim** – downstream keyword
  matching and ATS scoring depend on exact wording. The `## Raw text` section
  must contain the complete, unedited posting (expand every "see more" /
  truncation on the portal page first). Acceptance check before moving on:
  the Raw text section is at least as long as the structured sections
  combined, and ≥200 words unless the posting is genuinely shorter – if it
  fails, re-extract; never substitute a summary.

## 1. Setup

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)_hunt"
python3 scripts/db.py urls            # load ALL known URLs into memory (dedupe set)
python3 scripts/db.py dashboard       # read current inventory before setting the bar
python3 scripts/db.py log --run-id $RUN_ID --command hunt --action run_start \
  --detail '{"target_count": N, "max_age_days": M}'
```

Read once per run: `config/targets.yaml` (the target profile and per-language
queries), `config/boards.yaml` (the tier tables), the active pack's
`evaluation.md`, `positioning/role_fit_map.md`,
`positioning/candidate_profile.md`.

**Adaptive intake:** if shortlisted + ready exceeds the configured cap
(`config/pipeline.yaml → thresholds.shortlist_depth_cap`, default **25**),
this run shortlists only fit ≥ the adaptive bar (default **4.0**; score and
record everything else as usual — below the bar → `no`) and halves
`target_count`. Finding jobs is not the bottleneck; applying is.

## 2. Source loop

Use the target profile in `config/targets.yaml` (ranked targets, title
synonyms, per-language queries, must/reject signals, hunt-slot shares) and
the skip rules below. Work boards in tier order from `config/boards.yaml`;
within each board process newest-first; stop at `target_count`.

**Step 0 – current browser tab first.** If the currently open tab shows a job
board, search results, or a listing, harvest qualifying postings there before
navigating anywhere.

**Step 0b – mail hunt inbox.** Pipeline mail account:
**`config/pipeline.yaml → mail.account` only.** Before touching mail, verify
the connected account per the mail adapter's account guard – if a different
account is connected, skip this step entirely and tell the user which account
was found. If a mail tool is available, search recent mail (last 14 days) for
(a) messages whose **subject contains "hunt" or "/hunt"** (job-alert emails
the user forwards or labels for the pipeline) and (b) job-alert mail from the
sender domains in the pack's `boards.yaml → alert_sender_domains`. For each
match: extract every job-posting link from the body, then process each link
as a user-supplied URL per §3 (dedupe against `db.py urls` first; source slug
from the destination board, or a company slug for direct career pages).
These count toward `target_count`. Read-only: never send, reply, label, or
delete mail. No mail tool available → skip silently and continue.

Digest handling (huge bodies, spilled vs inline, grep patterns, id
canonicalisation) is documented in
`engine/adapters/browse/claude-in-chrome.md` § Alert-digest mining and the
mail adapter files. **Triage before extracting** – a forwarded digest can
carry 80+ ids, most stale or out-of-region; filter on the
title/company/location line first, then batch-check `posted`, and only then
extract.

**Step 0c – company watchlist sweep (cap ~10 min).** Read
`positioning/company_watchlist.md`. For each `open` company, open its careers
URL and scan titles against the target profile. Process qualifying new
postings per §3 with a company source slug (company-direct finds are the
highest-converting source class). Skip `in_flight` and `cooldown` rows — if a
qualifying role is seen at an `in_flight` company, log `job_skipped` with
`{"reason":"company_hold","company":"<name>"}` and list it in the run report.
`/track` flips watchlist states on apply/close/rejection.

**Batch-shaped dedupe.** Harvest ids → `db.py urls --check` **every id in the
batch** → `db.py list --company` on the survivors → only then extract. Re-run
the check for every new harvest; a batch that was not checked as a batch has
not been deduped. Do not write `jd_texts/{id}.md` until `add-job` for that id
has succeeded.

**Board diversity floor (a target, not a gate):** aim for ≥2 of every 10
qualifying jobs from non-primary sources. Make **one** pass at the
non-primary tier-1 sources; if it yields nothing qualifying, record the
reason in the run report and proceed – do not burn the time budget forcing
the floor. Company-direct career pages are the highest-yield non-portal
source; prioritise them after the primary portal. Generic aggregators start
on probation (see `config/boards.yaml` tier notes).

**Tier 2 (probe rotation):** each run, probe at most ONE tier-2 board,
rotating; log the probe in the run report even when barren. Two consecutive
barren probes move the board to tier 3 (via a `/optimise`-proposed edit to
`config/boards.yaml`). The rotation keeps new-source discovery alive at a
fixed cost.

### Skip a posting if

- URL already in the `db.py urls` output (this includes discarded jobs).
  **Dedupe on the destination URL, not the aggregator's.** Aggregators and
  link-wrapped newsletters point at an ATS URL that may already be in the DB
  under a different job_id. Resolve the redirect to its final URL and check
  *that* before writing a JD file. Check both the portal URL and the
  destination – either being known is a skip.
  `python3 scripts/db.py urls --check <url> [<url> ...]` does this in one call.
- **Company check before extracting.** Portals re-post with fresh ids, so URL
  dedupe misses them. If the company already has rows
  (`python3 scripts/db.py list --company "<name>"`), apply the repost policy
  for same/near-same titles:
  - prior `discarded` → skip, log `{"reason":"repost_of_discarded","prior":"<id>"}`
  - prior `applied`/`responded`/`closed` → skip, log
    `{"reason":"repost_of_applied","prior":"<id>"}` — a repost never restarts
    an application already made
  - prior `shortlisted`/`ready` → skip; append the new URL to the prior row's
    notes (`set-field notes`) — the pipeline already has this job
  - prior `missed` → the posting is live again: flag it in the stdout summary
    for the user to reopen via /track; do not create a duplicate row
  A genuinely NEW role at a known company is extracted and scored normally —
  then the same-company concurrency rule in §3b applies.
- Older than `max_age_days`
- Internship/stage, or executive (VP, C-level, Head of – unless
  small-startup scope fits mid-senior). Junior roles at otherwise strong-fit
  companies are NOT auto-skipped – score them per the pack's evaluation
  rubric (`stretch_down` experiment, small tranche)
- Matches a reject signal in `config/targets.yaml` (company class, sector,
  org shape)
- Login-walled / broken / JD hidden behind an application – log as failed, move on

## 3. Per qualifying posting – do all of this immediately, one job at a time

### 3a. Assign job_id and write the JD file

Extraction technique per board lives in the browse adapter docs
(`engine/adapters/browse/`) — for LinkedIn use the guest-endpoint recipe in
`claude-in-chrome.md` (2 calls per job; ids-only harvest from virtualised
search lists; `posted` read off the rendered page is the authoritative age
check, applied **before** writing any file). The Raw-text acceptance check
above always applies.

```bash
python3 scripts/db.py next-id <source_slug>    # e.g. the sample slug -> sample053
```

Source slugs come from `config/boards.yaml` (each board's `slug`), or a
company slug for direct career-page finds.

Write `jd_texts/{job_id}.md` using the structure of
`engine/rules/jd_template.md` (Meta / Company context / Role with
**verbatim** Responsibilities and Requirements split into must-have vs
nice-to-have / Reporting & team / Benefits & logistics / Raw text). Record
the posting's language in Meta (`Language: en|it|...` – judge from the
requirements section; mixed postings take the requirements' language).

### 3b. Score in the same breath

Apply the active pack's `evaluation.md` + `positioning/role_fit_map.md` +
`positioning/candidate_profile.md` + `config/targets.yaml` (read once per
run, then apply per job):

- `fit_score` 1–5 weighted across the evaluation dimensions
- `role_cluster` from the pack's roles.yaml; `seniority_match`;
  `location_fit` — judge `seniority_match` from the **JD body**
  (responsibilities, years, reporting line), never a portal's seniority tag,
  which is frequently wrong in both directions.
- **Region-string guard:** when the portal location is a region ("European
  Union", "EEA", "EMEA", "Anywhere"), do not record `location_fit: match`
  until the employer posting's eligible-country list is read (originate
  first, or record `remote_ok` pending origination) — region strings on
  aggregators are marketing copy.
- `must_have_match` / `missing_keywords` (semicolon-separated)
- `company_stage`, `company_signals`, `red_flags`
- Decision: fit ≥ 4 + no red flags + location ≠ reject → `yes`;
  fit ≥ 3.5 + minor flags or stretch seniority → `maybe`;
  fit < 3.5 or any reject signal → `no` (+ one-sentence `rejection_reason`
  citing the rule section; for the 3.0–3.4 band cite "below capacity bar").
  Exception: referral or direct-recruiter-contact jobs enter regardless of fit.
- Priority: `high` if fit ≥ 4.5, location match, and recommendation `yes`;
  `low` if fit < 3.5; else `medium`. A `maybe` recommendation caps priority
  at `medium`; a `stretch_up` seniority also caps at `medium`.
- **Same-company concurrency (conversion policy):** at most ONE in-flight
  application (`applied`/`responded`) per company. A new `yes`/`maybe` role at
  a company with one in flight is scored and recorded normally, then put on
  hold (`set-status --status on_hold`, note `held: <in-flight job_id>`) — it
  re-enters the shortlist when the in-flight application closes. Multiple
  shortlisted roles at one company → keep the best fit, hold the rest. A
  rejection from the company within the last 90 days → cap recommendation at
  `maybe` and record the prior rejection in `red_flags`.

### 3c. Record

```bash
python3 scripts/db.py add-job --job-id <id> --source <slug> --company "..." \
  --title "..." --url "..." --date-found YYYY-MM-DD --jd-path jd_texts/<id>.md \
  --jd-language en|it|... --location "..." --remote-flag remote|hybrid|onsite|unclear \
  [--salary "..."] [--employment-type "..."]

python3 scripts/db.py score --job-id <id> --fit-score X.X --role-cluster PO \
  --seniority-match yes --location-fit match --apply-recommendation yes \
  --priority high --must-have-match "...;..." --missing-keywords "...;..." \
  --company-stage scaleup --company-signals "...;..." [--red-flags "...;..."] \
  [--rejection-reason "..."]
```

`score` sets status automatically: `no` → `discarded` (recorded, never
revisited), `yes`/`maybe` → `shortlisted`.

### 3d. Originate (only for `yes`/`maybe`)

Find the posting on the employer's own site: careers page, or the underlying
greenhouse/lever/ashby/workable/smartrecruiters URL the portal redirects to.
Use web search and/or the browser. Then:

```bash
python3 scripts/db.py set-field --job-id <id> original_url "https://..."
python3 scripts/db.py set-field --job-id <id> ats_platform greenhouse|lever|ashby|workable|smartrecruiters|other|unknown
```

If no employer-site posting exists: set `original_url` to the portal URL and
`applied_via` hint to `portal_only`:

```bash
python3 scripts/db.py set-field --job-id <id> original_url "<portal url>"
python3 scripts/db.py set-field --job-id <id> applied_via portal_only
```

**Re-extract from the employer page (same visit).** While on the employer
posting for origination, compare its text with the Raw text captured in §3a.
If the employer version is longer or differs, replace the JD file's
`## Raw text` section with the employer-site text verbatim and note
`(verbatim – employer site, <url>, captured <date>)` in the section header.
The employer/ATS page is the canonical wording that downstream keyword
matching and the employer's own ATS both parse.

### 3e. Capture application questions (read-only, while on the original URL)

Many application forms gate submission behind open-ended questions ("Why do
you want to work here?", scenario prompts, salary expectation text boxes).
While already on the employer application page for origination, check
whether the form shows free-text questions **without entering anything**:

- **Strictly read-only.** Never fill a field, never click Apply/Next/Submit,
  never create an account. If the questions only appear after starting an
  application, do not start one – mark them `unknown`.
- Questions visible → write `jd_texts/{job_id}_questions.md`: one `## Q<n>`
  section per question, **verbatim wording**, noting required/optional and
  any character limit the form states. Answers are drafted later by
  `/prepare` (step 2c), never here.
- Form reachable but no free-text questions → no file; note `none visible`.
- Form not inspectable (login wall, portal-only, apply-gated) → no file;
  note `unknown`.

Add the result to the per-job log detail (`"questions":N`, `"questions":0`,
or `"questions":"unknown"`).

Log one event per job:

```bash
python3 scripts/db.py log --run-id $RUN_ID --command hunt --job-id <id> \
  --action job_processed --detail '{"portal":"<slug>","recommendation":"yes","originated":true,"questions":2,"duration_s":40}'
```

Failures (page broke, login wall, origination failed) are logged too:
`--action job_failed --detail '{"url":"...","error":"..."}'`. A captcha or
security interstitial is logged and skipped — never bypassed (project
policy).

## 4. Wrap-up

```bash
python3 scripts/db.py dashboard
python3 scripts/db.py log --run-id $RUN_ID --command hunt --action run_end \
  --detail '{"found":N,"discarded":K,"shortlisted":M,"skipped":S,"failed":F}'
```

**`run_end` is not optional.** Log it even when the run is aborting – on time
budget, on a dead browser, on an unrecoverable error – and add the reason:

```bash
python3 scripts/db.py log --run-id $RUN_ID --command hunt --action run_end \
  --detail '{"found":3,"discarded":1,"shortlisted":2,"skipped":0,"failed":1,"status":"aborted","reason":"time_budget"}'
```

A run with no `run_end` is indistinguishable from a crash and is invisible to
`/optimise`. If you can still make one bash call, you can still log this.

If the run ended `aborted` or `partial`, or the same failure occurred twice,
append an entry to `reports/pending_suggestions.md` per the contract in
CLAUDE.md. That is the only sanctioned way for a failed run to change the
pipeline: it proposes, `/optimise` triages, the user approves per item.

Write `runs/{RUN_ID}.md`: parameters used, counts per board, every skip with
its reason, every failure with error text, rough durations (from the events
table, not your impression of elapsed time).

## Stdout summary (always end with this)

```
Hunt complete: N new jobs
  shortlisted: M (high: H, medium: Md, low: L)
  discarded:   K
  skipped (duplicate / too old / no fit / inaccessible): S
  failures: F (see runs/{RUN_ID}.md)
Shortlist by priority (open each link to check the application form):
  {job_id}: {company} – {title} [{priority}] [{fit_score}]
    apply: {original_url or url}   questions: {N captured | none visible | unknown – check manually}
Questions to check manually: {job_ids with `unknown`, or "none"}
  If a form asks open-ended questions hunt couldn't see, paste them here –
  they'll be saved verbatim to jd_texts/{job_id}_questions.md and answered
  in /prepare (application_answers.md).
Run report: runs/{RUN_ID}.md
```
