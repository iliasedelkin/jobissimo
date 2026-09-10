# /track – lifecycle updates + dashboard

The user's single touchpoint for outcomes. Translate natural language into
the correct `scripts/db.py` calls, **always echo exactly what changed**, then
show the dashboard. Be forgiving of phrasing; be strict about state.

## Hard rules

- Every mutation goes through `python3 scripts/db.py ...` – never SQL, never
  direct DB edits.
- Status transitions are validated by db.py. If it refuses a transition,
  show the error to the user and ask – don't reach for `--force` on your own.
- If the user's phrasing is ambiguous (which job? which status?), resolve via
  `db.py list` / `db.py get` and confirm before writing.

## Translation guide

| User says | Do |
|---|---|
| "mark sample028 applied today via employer site" | `db.py set-status --job-id sample028 --status applied --applied-via employer_site` (date_applied auto-set to today; follow_up_date auto-set to +7d only for warm channels). `applied_via` is **required** – if not stated, ask before writing. Valid values: `linkedin_easy_apply`, `linkedin`, `employer_site`, `referral`, `email`, `other`. |
| "I applied to X on Tuesday" | same with `--date YYYY-MM-DD` (resolve the weekday to a real date) |
| "{Company} rejected" | find the job (`db.py list` + company match) → `set-status --status closed --outcome rejected`. Set `response_date` via `set-field` if known. Then append rejection stage to `interview_stage` using the stage prefix vocabulary (see Stage progression): e.g. `"..existing..; rejected at screen: YYYY-MM-DD"`. If stage unknown, write `"rejected at unknown stage"` – never leave blank. |
| "interview with {Company} on Tuesday" | `set-status --status responded` (if not already) + append to `interview_stage` (see Stage progression below) + `set-field response_date ...` if first response |
| "got a response from Y" | `set-status --status responded` |
| "skip sample031" / "not applying" | `set-status --status skipped` |
| "put X on hold" | `set-status --status on_hold` |
| "X offered!" | `set-status --status closed --outcome offer` (congratulate them) |
| "never heard back from X, close it" | `set-status --status closed --outcome no_response` |
| "recruiter for X is Jane, linkedin.com/in/jane-example" | `set-field recruiter_name "Jane"` + `set-field recruiter_url ...` |
| "note on X: ..." | `set-field notes "..."` (append to existing notes, don't overwrite) |
| "watch Acme https://acme.example.com/careers" | append a row to `positioning/company_watchlist.md` with state `open` (create nothing else — /hunt Step 0c does the sweeping) |
| "stop watching Acme" / "pause Acme" | set that row's State to `paused` (or delete the row if the user says remove) |
| "what's my pipeline look like" | just `db.py dashboard` |

Company names map to job_ids via `python3 scripts/db.py list` (search output
for the company). If several jobs match one company, list them and ask which.

## Stage progression

`interview_stage` is a running log, not a current-state field. **Always
append** – never replace – using `"; "` as separator with a date stamp on
every entry. Read the current value with `db.py get <id>` first, then write
the full accumulated string back.

Standard prefixes:

| Prefix | Meaning |
|---|---|
| `screen:` | recruiter email / residency / availability check |
| `test:` | async online test (invited or completed) |
| `hr:` | HR video/phone screen |
| `hm:` | hiring manager call |
| `tech:` | technical interview |
| `panel:` | panel / loop |
| `final:` | final round |
| `offer:` | verbal offer (before written) |

Example of a full arc:
`screen: availability 2026-07-01; test: invited 2026-07-05; test: completed 2026-07-08; hr: call scheduled 2026-07-15`

On rejection: always append `"; rejected at <prefix>: YYYY-MM-DD"` – or
`"; rejected at unknown stage"` if stage is unclear. Never leave blank.

## Follow-ups

Follow-ups are **warm-channel only**: db.py sets `follow_up_date` on apply
only for `referral`/`email` applies or when `recruiter_name` is set. Cold
portal applies get none. The dashboard hides follow-ups >14 days past due.

**Batch mode — `/track follow-ups`** (plural, no id): collect every job whose
`follow_up_date` has passed, draft ALL of them per the steps below into one
file `reports/followups_{YYYY-MM-DD}.md` (one section per job), and show it.
The user sends manually and confirms in one message ("sent all", or "sent 1
and 3"); then do step 4 for each confirmed job in one pass.

Single-job trigger: `/track follow up <job_id>`, or the user asks about due
follow-ups (the dashboard lists them). For each job:

1. `python3 scripts/db.py get <job_id>` – confirm status is `applied` and
   `follow_up_date` has passed; note `applied_via` (that channel is where the
   follow-up goes: portal message, or email).
2. Draft a 3–5 sentence follow-up from the application folder's final cover
   letter + `jd_texts/{job_id}.md`: restate interest in the specific role,
   one strongest proof point, ask about timeline. Write it in the
   application's language (`jd_language`). Truth guardrails apply – no new
   claims beyond the final assets.
3. Show the draft. **The user sends it manually – never send autonomously.**
4. Once the user confirms it was sent:
   `db.py set-field <job_id> follow_up_date <today+7 as YYYY-MM-DD>` and log
   `--action follow_up_sent`.

## After every change

0. If the job's company is on `positioning/company_watchlist.md`, update its
   State: → `applied`/`responded` ⇒ `in_flight (<job_id>)`; → `closed`
   rejected ⇒ `cooldown <today+90d>`; → `closed` otherwise ⇒ `open`. When a
   company's in-flight application closes, remind the user of any `on_hold`
   jobs at that company (`db.py list --company "<name>" --status on_hold`).
1. Echo a one-line confirmation per change:
   `sample028: ready → applied (date_applied=2026-06-11, follow_up=2026-06-18, via employer_site)` –
   db.py already prints this; relay it.
2. Log it:
   ```bash
   python3 scripts/db.py log --run-id "$(date +%Y%m%d_%H%M%S)_track" --command track \
     --job-id <id> --action user_update --detail '{"said":"...","change":"..."}'
   ```
3. Show the dashboard:
   ```bash
   python3 scripts/db.py dashboard
   ```

## Stdout summary (always end with this)

```
Changed: N row(s)
  {job_id}: {old_status} -> {new_status} ({fields changed})
[dashboard follows]
```
