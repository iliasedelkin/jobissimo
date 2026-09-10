# /refresh – verify open jobs are still live, mark dead ones missed

Check every job that is still in play but not yet applied, detect postings
that are no longer accepting applications, and mark those `missed` so the
dashboard reflects reality. Read-only on the web; all state changes via
`scripts/db.py`.

## Input

- **default (no input):** every job with `status` in
  `found | scored | shortlisted | generated | ready`
- a single `job_id` or a list of `job_id`s
- `links` – **manual mode**: output each job's check link and detected state,
  write nothing; the user verifies in the browser and reports back via
  `/track <id> missed` (or tells this command to apply its findings)

## Hard rules

- **db.py is the only write path.** If db.py refuses a transition to
  `missed`, surface the error – never `--force` on your own.
- **A portal mirror saying "closed" is not proof – and "the recorded URL is a
  portal" does not make the portal the source.** See Field notes below.
  Before classifying ANY portal-sourced job as closed, **web-search for the
  employer posting first** (`{company} careers {job title}`; check the
  employer careers page and known ATS hosts; titles may drift, e.g. Product
  Owner ↔ Product Manager). Only an explicit closed signal **on the employer
  source itself** justifies `missed`. Employer source unreachable, JS-walled,
  or not found → "needs manual check", never auto-marked. When a live
  employer posting is found, backfill `original_url` + `ats_platform` while
  you're there.
- Logged-out fetches can differ from logged-in views; when in doubt, put the
  job in the manual-check list instead of marking it.
- Never re-check `discarded` (permanent) or post-application statuses –
  outcome tracking belongs to `/track`.

## Field notes

Two dated observations from live operation of this pipeline — kept because
they are exactly the mistake this command exists to prevent:

- A job was found open on its employer's Ashby board while **both** portal
  mirrors said closed.
- Two jobs were marked missed off portal mirrors while live on their
  employer sites; the user caught it and the rows had to be reopened.

The portal mirror is a cache with its own expiry policy. The employer source
(careers page or ATS board API) is the only authority.

## Setup

```bash
RUN_ID="$(date +%Y%m%d_%H%M%S)_refresh"
python3 scripts/db.py log --run-id $RUN_ID --command refresh --action run_start \
  --detail '{"selection":"...","mode":"check|links"}'
python3 scripts/db.py list --status found --status scored --status shortlisted \
  --status generated --status ready
```

## Per job

1. Pick the check URL: `original_url`, else `url` (from `db.py get <id>`).
2. Fetch it (web fetch or browser). For known ATS platforms prefer the public
   posting API when it exists – it is authoritative and verbatim:
   - ashby: `https://api.ashbyhq.com/posting-api/job-board/{org}` (job id
     present in `jobs[]` = open)
   - greenhouse: `https://boards-api.greenhouse.io/v1/boards/{org}/jobs`
   - lever: `https://api.lever.co/v0/postings/{org}`
3. Classify:
   - **open** – posting text + application form present, or job listed in the
     ATS API
   - **closed** – the source page/API explicitly says so ("no longer
     accepting applications", a localized equivalent, "position
     filled/closed", job absent from the ATS API listing, HTTP 404/410)
   - **needs manual check** – login wall, 403, JS-only page, mirror-closed
     without reachable source, or any ambiguity
4. Act (default mode):
   - open → no change; log `--action job_checked --detail '{"state":"open"}'`
   - closed → `python3 scripts/db.py set-status --job-id <id> --status missed`
     + log `--action job_checked --detail '{"state":"closed","evidence":"..."}'`
   - needs manual check → no change; collect for the summary with its link
   In `links` mode: classify but write nothing; print every job with its
   link and detected state for the user's manual pass.
5. Bonus (no extra cost while checking): if the source page shows a fuller
   posting text than `jd_texts/{id}.md` § Raw text, replace Raw text verbatim
   per the /hunt § Re-extract rule.

## Wrap-up

```bash
python3 scripts/db.py log --run-id $RUN_ID --command refresh --action run_end \
  --detail '{"checked":N,"open":O,"marked_missed":M,"manual":K}'
python3 scripts/db.py dashboard
```

Write `runs/{RUN_ID}.md`: per-job state + evidence, every marked transition,
every manual-check item with its link.

## Stdout summary (always end with this)

```
Refresh complete: N jobs checked
  open: O   marked missed: M   needs manual check: K
Marked missed:
  {job_id}: {company} – {title}  (evidence: {closed marker / API absence})
Check manually (logged-out view was ambiguous):
  {job_id}: {company} – {title}
    {check link}
Run report: runs/{RUN_ID}.md
```
