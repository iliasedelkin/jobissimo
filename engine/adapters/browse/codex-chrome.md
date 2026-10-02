# Browse adapter: codex-chrome (Codex Chrome / Browser plugin)

The Codex counterpart of `claude-in-chrome`: a real, logged-in Chrome driven
by the agent through the ChatGPT/Codex browser extension (the bundled
**Chrome** / **Browser** plugins in the Codex app). This means **the user's
own session** — the user is present or has explicitly scheduled the run; this
is not a scraper. All the boundaries in `engine/adapters/README.md` apply: no
captcha/interstitial bypass, respect rate limits, read-only forms.

**Desktop app only.** The integration exists in Codex inside the ChatGPT
desktop app, not in the Codex CLI or IDE extension, so a `codex exec` run never
has it — its browser probe fails fast and the run degrades as below. The user
selects the browser by @-mentioning it in the chat (e.g. `@Chrome`); if no
browser was mentioned and none is reachable, say so once instead of guessing.
Setup: `docs/getting-started.md` § Browser.

Capabilities: `listings.search` (portal search pages), `jd.fetch` (full
verbatim postings, including login-walled boards), `form.inspect` (read-only
question capture on application forms).

## Failure modes

**The extension is not reachable.** Probe at session start: one cheap
browser-client call (list open tabs), **before** any other work; on error wait
two seconds and retry once. Any non-error response means the extension is
working. Record the outcome as a `browser_probe` event so `/optimise` can count
availability. On failure, degrade exactly as with claude-in-chrome: mail +
manual URLs still work; write surviving candidate URLs into the run report as
a ready-to-run list. Do not try to repair the extension or native host, and
never substitute AppleScript or shell automation for it — tell the user to
reinstall the Browser plugin from the Codex/ChatGPT plugin UI.

**The domain is not permitted.** If the extension refuses a domain before the
page loads, record it as a distinct `permission_denied` reason on the
`portal_probe` or `job_failed` event, never as "barren" or "dead" — the same
rule as `claude-in-chrome.md` § Failure modes: a board the agent was never
allowed to open is not evidence about the board. Name the domain in the run
report so the user can grant it.

**A confirmation prompt appears.** The plugin has its own confirmation policy:
typing personal data into a form counts as *transmitting* it and needs the
user's go-ahead. That is compatible with — and weaker than — invariant 5:
`/apply` still stops before submit with a screenshot and a field-by-field
summary, whatever the plugin would allow.

## Field notes

The LinkedIn extraction recipe and the alert-digest notes in
`claude-in-chrome.md` (§ Field notes, § Alert-digest mining) are about page
structure, not the tool, and apply here too — translate the tool names:

| claude-in-chrome | codex-chrome |
|---|---|
| `tabs_context_mcp` | list open tabs |
| `navigate` + `get_page_text` | open the URL in a tab, read the page text |
| `javascript_tool` | evaluate script in the tab |
| `browser_batch` | issue the calls back-to-back in one step |

The core rules carry over unchanged: render the LinkedIn guest endpoint
`https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}` as a page and
read its text (2 calls per job); harvest **ids only** from virtualised result
lists; never scroll them; rebuild URLs from ids rather than returning raw
`href`s. Re-verify the dated selectors before relying on them, and update
`claude-in-chrome.md` (the single copy) when they drift.
