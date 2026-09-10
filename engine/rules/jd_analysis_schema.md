# JD Analysis Schema

The Evaluator step reads a JD and outputs a Markdown document conforming to this schema. The Generator consumes it directly; do not change field names without updating both.

---

## Template

```markdown
# JD Analysis

## Source
- Company: {name}
- Role title (as posted): {title}
- Date retrieved: {YYYY-MM-DD}
- URL / source: {link or "pasted text"}

## Company signals
- Stage: {seed | Series A | Series B | Series C | scale-up | public | enterprise | unknown}
- Industry: {e.g. B2B SaaS, fintech, consumer}
- Size: {headcount band}
- Work mode: {remote-global | remote-region | hybrid-{city} | onsite-{city}}
- Product-led?: {yes | no | unclear}
- Tech stack (mentioned): {list}
- Red flags detected: {list from the pack's evaluation.md § Universal red flags, or "none"}

## Role cluster (detected)
Primary: {a cluster id from the active pack's roles.yaml}
Secondary (if ambiguous): {...}
Seniority: {junior | mid | senior | lead | director}

## Role content signals
- Must-haves: [list of explicit requirements]
- Nice-to-haves: [list]
- Strong positive signals (from the pack's evaluation.md § Role content signals): [list]
- Weak / reject signals: [list]

## Keyword extraction
- Domain keywords: [5–10 terms to weave into CV if evidence exists in skills_inventory.md]
- Methodology keywords: [e.g. "discovery", "OKRs", "experimentation"]
- Tool keywords: [e.g. named tools from the JD]
- Keyword-to-evidence matches: [keyword → BULLET_ID or skill entry; any unmatched keywords → flag]

## Location fit
- JD location requirement: {verbatim}
- Fit: {one of the configured location-fit values, judged against config/targets.yaml geography}
- Penalty applied: {none | small | major | reject}

## Positioning recommendation
- Best-fit cluster from positioning_library.md: {cluster + variant}
- Tone: {startup-informal | scale-up-balanced | corporate-formal}
- Proof points to prioritize (in order): [BULLET_ID, BULLET_ID, ...]

## Gaps vs. JD
- Requirements not matched by candidate: [list]
- Handling strategy (per truth_guardrails.md): [omit | transferable bridge | acknowledge honestly]

## Decision
DECISION: {PROCEED | REJECT}
Reason: {one sentence, citing the specific evaluation.md section or targets.yaml rule that triggered the decision}
```

---

## Notes on filling this in

- Under **Keyword-to-evidence matches**: any JD keyword without a matching skill or bullet must appear in the "unmatched" list. The Generator will not introduce keywords from the unmatched list – ever.
- Under **Gaps vs. JD**: list every must-have the candidate doesn't cleanly meet. The cover letter playbook defines how to handle these: small gap → omit silently, medium gap → transferable-skill bridge, hard no → DECISION: REJECT or honest acknowledgment per case.
- Under **Decision**: a REJECT here halts the pipeline. The user sees the reason and can choose to override, but the default is trust the gate.
