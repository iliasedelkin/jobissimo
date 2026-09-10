# Browse adapter: playwright (headless)

Headless, server-friendly browsing for installs without a desktop Chrome.
Capabilities: `jd.fetch` on public pages; limited `listings.search` on boards
that render without login.

Costs: **no logged-in sessions.** Login-walled boards degrade to their guest
views or are skipped; anything requiring authentication belongs to the
claude-in-chrome adapter or the manual path.

Boundaries (non-negotiable, same as every browse adapter): no captcha or
interstitial bypass — a challenge page is logged and skipped; respect
`robots.txt` and per-board rate limits; single-user personal use. Headless
browsing is the mode most likely to hit bot defences: when a board blocks it,
record the fact in `config/boards.yaml` access notes and stop probing that
board with this adapter.

Implementation notes:
- Use the guest/public endpoints documented in `claude-in-chrome.md` where
  they exist — they are cheaper and more stable than rendered pages.
- Prefer the public ATS board APIs (see `webfetch.md`) whenever the employer
  is known; they are authoritative and need no browser at all.
- Set a normal descriptive user agent; do not rotate agents or proxies —
  that is evasion, which this project does not do.
