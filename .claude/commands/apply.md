# /apply <job_id> – assisted browser application (stretch)

Fill the employer's application form with the user watching, from verified
sources only, and **never submit autonomously**. This is a stated project
boundary, not a preference — see README § Limits and ethics.

## Preconditions (check all; refuse loudly if any fails)

```bash
python3 scripts/db.py get <job_id>
```

- `status = ready`
- `audit_status = pass` (a bypassed audit needs explicit user re-confirmation)
- `cv.docx` (and `cover_letter.docx` if requested) exist in `application_folder`
- `original_url` set – if NULL, originate it first (see /hunt § Originate)
- a browser adapter with a logged-in session is available
  (`config/capabilities.yaml`); without one, /apply cannot run — the user
  applies manually from the exported finals

## Allowed answer sources – nothing else

1. `applicant_profile.yaml` in the workspace (fields marked `confirm: true`
   must be confirmed with the user before first use)
2. The job's final assets (`cv_final.md`, `cover_letter_final.md`, notes,
   `application_answers.md`)
3. `knowledge/` files

**Any form question not answerable from those sources → pause, ask the user,
record the answer.** Never improvise, never guess, never leave a fabricated
answer in a field. If the user wants the answer reused in future, add it to
`applicant_profile.yaml` (with their confirmation).

## Procedure

1. Navigate to `original_url` (never the aggregator). Confirm the posting is
   still open; if gone, tell the user and suggest `/track` (`missed` or
   `skipped`).
2. Detect the ATS platform from the URL/page (greenhouse / lever / ashby /
   workable / smartrecruiters / other) and
   `python3 scripts/db.py set-field --job-id <id> ats_platform <value>` if it
   differs from the recorded one.
3. Fill the form field by field from the allowed sources. Upload `cv.docx`
   and `cover_letter.docx` from the application folder; where upload is not
   available, paste the contents of the corresponding `*_final.md`.
4. EEO/diversity questions: per `applicant_profile.yaml` § eeo (default
   "prefer not to say") unless the user instructs otherwise.
5. **HARD STOP before submission – no exceptions:**
   - take a screenshot of the filled form
   - print a field-by-field summary (field → value → source)
   - wait for explicit user confirmation
   - the user clicks submit, or explicitly instructs the agent to click it.
6. On confirmed submission:

```bash
python3 scripts/db.py set-status --job-id <id> --status applied --applied-via employer_site
python3 scripts/db.py log --run-id $RUN_ID --command apply --job-id <id> \
  --action application_submitted \
  --detail '{"platform":"greenhouse","fields":{"field":"value-source pairs"},"submitted_by":"user"}'
```

(`RUN_ID="$(date +%Y%m%d_%H%M%S)_apply"`; also log `run_start`, any
`question_escalated` events with the question + user's answer, and `run_end`.)

7. If the user declines at the hard stop: leave status `ready`, log
   `application_aborted` with the reason.

## Stdout summary (always end with this)

```
Apply: {job_id} – {company}
  platform: {ats_platform}
  fields filled: N (M escalated to user)
  uploads: cv.docx [, cover_letter.docx]
  outcome: submitted | aborted ({reason})
  status: {final status}
```
