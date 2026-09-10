# Browse adapter: manual (the user supplies the postings)

The user pastes URLs or full JD text into the chat; the agent runs everything
downstream — JD file, scoring, origination when a URL allows it, and the whole
prepare → audit → score → export chain — unaffected.

This is a **first-class path, not a fallback**:

- It is the ToS-safest mode: no automated access to any board at all.
- It is the zero-dependency mode: works with no browser, no MCP, no network
  tooling in the session.
- It is often the fastest mode for a handful of hand-picked postings.

Procedure when the user pastes a URL: dedupe it first
(`python3 scripts/db.py urls --check <url>`), then fetch it with whatever
fetch capability exists, or ask the user to paste the posting text if none
does.

Procedure when the user pastes JD text: write `jd_texts/{job_id}.md` per
`engine/rules/jd_template.md` with the pasted text verbatim in `## Raw text`
(note `source: pasted text`), then score and record normally. The verbatim
acceptance check still applies — if the paste looks truncated, ask for the
rest rather than proceeding against a stub.

Discovery is the user's job in this mode; the pipeline's job is everything
after discovery.
