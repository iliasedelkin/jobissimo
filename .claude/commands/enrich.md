# /enrich – answer the highest-impact profile gaps in five minutes

Pull the top queue items by impact, ask them in one short batch, write after
every answer, rebuild the competency map, and report what the strength score
moved to. This should feel like five minutes, not an onboarding.

## Input

- **default:** top 5 open items from `knowledge/_queue.yaml` by impact
- a number (`/enrich 10`) – batch size
- a kind (`/enrich metrics` | `skills` | `targets` | `identity`) – filter by
  queue `kind` (`metric_rescue`, `skill_evidence`, ...)

## Procedure

1. Read the queue and the current score:
   ```bash
   python3 scripts/coverage.py --no-queue
   ```
   Note the strength score. Select the batch (open items, highest impact
   first; ties by lowest est_minutes).
2. Ask the batch conversationally — one message, numbered, with the impact
   framing ("these are the answers that raise your profile most"). Accept
   partial answers; "skip" and "no number exists" are valid answers.
3. **Write after every answer, not at the end:**
   - metric rescue → add the figure to the bullet's `Facts` (verbatim, with
     unit and scope) and extend a `Phrasing`; "no number exists" → mark the
     queue item `answered` and the bullet stays qualitative.
   - skill evidence → add the cited bullet ID to the skill's `Evidence:` line
     (the skill becomes CV-eligible); if the user cannot cite one, move the
     skill to `knowledge/unevidenced.md`.
   - proficiency calibration → challenge inconsistencies aloud ("advanced
     SQL, but no bullet mentions a query — which role was that?"); a
     challenged claim gains evidence or loses its level.
   - identity/logistics → `applicant_profile.yaml` (with `confirm: true`
     removed once the user confirms).
   - new facts always carry provenance: `<!-- from:user#enrich-{date} -->`.
   - update the item's `status:` in `knowledge/_queue.yaml` after each write.
4. Truth guardrails apply: record what the user says, verbatim numbers, no
   embellishment. If an answer contradicts an existing fact, surface the
   contradiction and let the user pick — never keep both silently.
5. Rebuild and re-score:
   ```bash
   python3 scripts/competency_map.py
   python3 scripts/coverage.py
   ```
6. If positioning cites anything that changed, regenerate the affected
   `positioning_library.md` section and audit it at birth
   (`audit.py --library`), same as /setup S7.

## Stdout summary (always end with this)

```
Enriched: N answered, S skipped ({kinds})
Profile strength: {before} → {after}
Now CV-eligible: {newly evidenced skills, or "none"}
Queue remaining: {K} items (top: {one-line prompt})
```
