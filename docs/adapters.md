# Adapters

Discovery, JD fetching, form inspection, and mail are behind capability
contracts so the pipeline runs on whatever your session has. `/setup` S0
probes and records the choice in `config/capabilities.yaml`; every command
degrades honestly. A missing capability is never a blocker — it just narrows
the feature set.

The contracts:

```
listings.search(query, region, since_days) → [{id,title,company,location,posted,url}]
jd.fetch(url)                              → {title, company, raw_text, posted, language}
form.inspect(url)                          → {questions[]} | unknown    # read-only
mail.search(query, since_days)             → [{id, subject, body}]      # read-only
```

## Browse adapters

| Adapter | Gets you | Costs you |
|---|---|---|
| `claude-in-chrome` | Logged-in sessions; cheap guest-endpoint extraction; batched digest triage | Requires that MCP and a real browser |
| `playwright` | Headless, server-friendly | No logged-in sessions; login-walled boards degrade |
| `webfetch` | Zero dependencies; company career pages + public Ashby/Greenhouse/Lever board APIs (stable, documented, verbatim) | No search-results harvesting; company-direct only |
| `manual` | You paste URLs or JD text; the whole prepare→audit→score→export chain is unaffected. A first-class path — also the ToS-safest mode | No discovery |

Details and dated field notes (e.g. the LinkedIn guest-endpoint extraction
recipe) are in `engine/adapters/browse/`.

## Mail adapters

`gmail-mcp`, `imap`, or `none`. All read-only by contract — the pipeline
never sends, replies, labels, or deletes. The **account guard** verifies the
connected mailbox matches `config/pipeline.yaml → mail.account` before
reading a single message; reading a different mailbox is a privacy decision
only you can make.

## Export adapter

`pandoc` renders the audited finals to DOCX (+ optional PDF via
tectonic/xelatex/LibreOffice). No pandoc → the markdown finals are still
produced with traces stripped, and you convert them yourself.

## Stated boundaries (project policy, not configurable)

- A browser adapter means **you, driving your own logged-in session** — not a
  scraper.
- **No captcha or interstitial bypass.** A challenge is logged and skipped.
- Respect `robots.txt` and per-board rate limits; one probe per board per run.
- Single-user, personal use.
