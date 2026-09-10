# Adapters

Four capability contracts. `/setup` S0 probes what exists on this machine and
records it in `config/capabilities.yaml`; each command degrades honestly when a
capability is missing — a missing browser never blocks the prepare → audit →
score → export chain.

```
listings.search(query, region, since_days) → [{id,title,company,location,posted,url}]
jd.fetch(url)                              → {title, company, raw_text, posted, language}
form.inspect(url)                          → {questions[]} | unknown    # read-only
mail.search(query, since_days)             → [{id, subject, body}]      # read-only
```

| Adapter | Gets you | Costs you |
|---|---|---|
| `browse/claude-in-chrome` | Logged-in sessions; cheap 2-calls-per-job guest-endpoint extraction; batched triage of a whole alert digest | Requires that MCP and a real browser |
| `browse/playwright` | Headless, server-friendly | No logged-in sessions; login-walled boards degrade to guest views |
| `browse/webfetch` | Zero extra dependencies; company career pages and the public Ashby / Greenhouse / Lever board APIs — stable, documented, verbatim | No search-results harvesting; company-direct only |
| `browse/manual` | User pastes URLs or JD text; the entire prepare → audit → score → export chain is unaffected. A first-class path, not a fallback — it is also the ToS-safest mode | No discovery |
| `mail/gmail-mcp`, `mail/imap`, `mail/none` | Job-alert digests are high-yield and free to read | Read-only by contract; the account is verified against config before a single message is read |
| `export/pandoc` | DOCX (+PDF) finals from markdown | Requires pandoc; PDF needs tectonic/xelatex/LibreOffice |

## Stated boundaries (project policy, not configurable)

- A browser adapter means **the user, driving their own logged-in session** —
  not a scraper.
- **No captcha or interstitial bypass.** A Cloudflare challenge or similar is
  logged (`portal_probe` / `job_failed`) and skipped, never worked around.
- Respect `robots.txt` and per-board rate limits; one probe per board per run.
- Single-user, personal use.
