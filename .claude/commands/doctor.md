# /doctor – config health, provenance, drift

Re-run the validator, explain any config value's provenance on request, and
detect drift between setup-time state and the workspace now. Read-only
except for re-recording `config/capabilities.yaml` when the user asks.

## Default run

```bash
python3 scripts/setup_check.py
python3 scripts/paths.py
```

Relay the output, then add judgement the script can't:
- If a stage's inputs drifted (knowledge hand-edited since setup, competency
  map stale, positioning citing a dead bullet ID), name the cheapest fix:
  `python3 scripts/competency_map.py`, `/setup --stage <name>`, or `/enrich`.
- If capabilities changed (pandoc appeared/disappeared, a browser MCP is now
  present), offer to re-run the S0 preflight and update
  `config/capabilities.yaml`.

## Provenance questions

"Where did `<value>` come from?" → answer from, in order:
1. `profile/setup_state.yaml` (which stage wrote it, when, from what inputs)
2. the intake manifest (`profile/_intake/manifest.yaml`) for extracted facts
   — every bullet's `<!-- from:{src_id}#{locator} -->` points at a source
   document and location
3. `events` (`db.py export-csv`) for `/optimise`-applied changes
   (`suggestion_applied` rows name the target and suggestion)
4. If none of those explain it, say so plainly — an unexplained config value
   is worth flagging, not papering over.

## Focused modes

- `/doctor --languages` – reopen the S5 language stage: show configured
  languages + proficiencies + locale verification status, and walk the user
  through changes (writes `config/languages.yaml` on confirmation).
- `/doctor --capabilities` – re-run the S0 probe and diff against
  `config/capabilities.yaml`.

## Stdout summary (always end with this)

```
Doctor: {ok | N errors, M warnings}
Errors:   {list or none}
Warnings: {list or none}
Drift:    {stale stages or none}
Suggested next: {command(s) or "nothing — healthy"}
```
