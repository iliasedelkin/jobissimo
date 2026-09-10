# Browse adapter: webfetch (plain HTTP fetch)

Zero extra dependencies: whatever URL-fetching tool the agent session already
has. Capabilities: `jd.fetch` on company career pages and public ATS board
APIs. No search-results harvesting — this adapter is **company-direct only**,
which the pipeline's own telemetry ranks as the highest-converting source
class anyway.

## Public ATS board APIs (authoritative and verbatim)

These are documented, public, no-auth endpoints; a job present in the API is
open, and one absent is closed — which also makes them the preferred
`/refresh` liveness source:

- **Ashby**: `https://api.ashbyhq.com/posting-api/job-board/{org}`
  (job id present in `jobs[]` = open)
- **Greenhouse**: `https://boards-api.greenhouse.io/v1/boards/{org}/jobs`
  (`?content=true` for full descriptions)
- **Lever**: `https://api.lever.co/v0/postings/{org}`

The JSON descriptions are the employer's canonical wording — exactly what
downstream keyword matching and the employer's own ATS parse. Prefer them
over any portal mirror.

Costs: no logged-in views, no board search. Discovery through this adapter is
the company watchlist (sweep each watched company's board API or careers page)
plus user-supplied URLs.

Boundaries: fetch politely (no hammering; cache within a run), respect
`robots.txt`, and never fetch through rotating proxies or disguised agents.
