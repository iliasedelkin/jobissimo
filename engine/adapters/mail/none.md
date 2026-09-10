# Mail adapter: none

No mail capability in the session. This is a supported configuration, not an
error:

- `/hunt` and `/brief` skip their mail phases and say so in the run report
  (`MAIL SKIPPED — no mail tool in session`), then continue with the portal
  sweep / watchlist / manual URLs.
- Job-alert digests can still feed the pipeline manually: the user forwards
  or pastes alert links into the chat and they are processed as user-supplied
  URLs (dedupe first).
- Recruiter replies are tracked by the user via `/track` in natural language,
  which is the write path for outcomes in every mail configuration anyway.

Nothing downstream of discovery is affected.
