# Browse adapter: claude-in-chrome (Claude in Chrome MCP)

The richest browse adapter: a real, logged-in Chrome driven by the agent
through the `mcp__claude-in-chrome__*` tools. This means **the user's own
session** — the user is present or has explicitly scheduled the run; this is
not a scraper. All the boundaries in `engine/adapters/README.md` apply: no
captcha/interstitial bypass, respect rate limits, read-only forms.

Capabilities: `listings.search` (portal search pages), `jd.fetch` (full
verbatim postings, including login-walled boards), `form.inspect` (read-only
question capture on application forms).

Probe at session start: one `tabs_context_mcp` call, **before** any other
work. The MCP being dead costs up to 180 s to discover — spend that while the
time budget is untouched, and record the outcome as a `browser_probe` event so
`/optimise` can count availability. On failure, degrade: mail + manual URLs
still work; write surviving candidate URLs into the run report as a
ready-to-run list.

## Field notes: LinkedIn extraction

**These notes are dated (layout observed mid-2026). Page layouts change;
verify before relying on them, and update this file when they drift.**

- `linkedin.com/jobs/view/{id}` no longer renders the description into the
  DOM: the body is ~1,500 chars, the usual description containers are absent,
  and `DOMParser` is neutered on the LinkedIn origin. Do not burn calls
  hunting for a "see more" button — there isn't one.
- Instead, **render the guest posting endpoint as a page and read it** — do
  not `fetch` it from `javascript_tool`, whose return truncates at ~1,000
  chars. Point the tab at the endpoint and call `get_page_text`, which
  returns the entire posting — description, salary, hiring process, criteria
  block — in one call:

  ```
  navigate → https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}
  get_page_text
  ```

  Wrap the two in `browser_batch` so it is a single round trip: **2 calls per
  job**.
- The guest response carries no `<h1>`; the rendered page's first line is the
  title. If missing, recover it from the search-results listing or the alert
  line you already have — do not rely on a regex.
- `posted` ("1 day ago" / "3 weeks ago") on the rendered page is the
  authoritative age check — apply it **before** writing any file.
- Search-result cards are virtualised — only the ~7 above the fold carry
  text, and scrolling to force rendering can freeze the renderer (45 s CDP
  timeout observed). Harvest **ids only** from the list
  (`[...document.querySelectorAll('li[data-occludable-job-id]')].map(...)`),
  then run a batched guest-endpoint triage loop (id → title, company,
  location, posted) — never scroll the virtualised list. Working regexes
  against the guest HTML (dated):
  `topcard__title[^>]*>\s*([^<]{2,120})`,
  `topcard__org-name-link[^>]*>\s*([^<]{2,60})`,
  `topcard__flavor--bullet[^>]*>\s*([^<]{2,60})`, and
  `>\s*(\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago)\s*<` for age.
- Keep a JS batch loop only for the cheap triage pass (~300 ms pause per id,
  return `{id, company, location, posted, len}`) — there the 1,000-char cap
  is not binding, and only survivors get the full 2-call extraction.
- **Never return raw `href` or `location.href` from `javascript_tool`** — the
  browser tool blocks any result containing query-string data. Project links
  to `hostname + pathname` first
  (`const u = new URL(a.href); u.hostname + u.pathname`) and rebuild the full
  URL from the id afterwards.

## Alert-digest mining

Job-alert email bodies can run 90k–350k chars. If the mail tool spills them to
a temp file, grep it with `-o` and a bounded pattern (window under ~200 chars)
rather than reading linearly — the file is one line. If the mail tool returns
bodies **inline** (some sandboxes), do not open digests at all: triage from
`search_threads` subjects/snippets and drive discovery from the live portal
sweep instead. Canonicalise every extracted LinkedIn id to
`https://www.linkedin.com/jobs/view/{id}` and dedupe on that.
