# Master Experience — {candidate name}

The single source of truth for work history. Every bullet below is a factual
claim the generator may **select and rephrase**. It may never be combined
with facts from other bullets, re-metricized, or generalized.

Written by /setup S2 from the intake documents; corrected in S3; enriched by
/enrich. Every fact carries provenance back to a source document
(`<!-- from:SRC-NNN#locator -->`).

---

## Schema

Each role has a `ROLE_ID`. Each bullet has a `BULLET_ID` in the form
`{ROLE_ID}-{NNN}`.

A bullet contains:
- **Tags**: competencies (one or more, from the active pack's vocabulary)
- **Facts**: canonical, immutable claims — numbers verbatim with unit and
  scope; named tools; named outcomes; mechanisms
- **Phrasings**: 1–3 pre-approved wordings the generator may pick from or
  paraphrase within fact boundaries

Contradictions between source documents are flagged inline with
`CONTRADICTION:` until the user resolves them (S3 / /enrich).

---

## ROLE: {ROLE_ID} — {Company}, {Title}

- **Company:** {name}
- **Stage:** {e.g. scale-up, ~50 employees}
- **Industry:** {sector}
- **Work mode:** {remote | hybrid | onsite}
- **Period:** {Mon YYYY – Mon YYYY | Present}
- **Title (canonical):** {title as held}
- **Title (alt, use only if JD scope matches):** {approved alternate, if any}
- **Team context:** {who the role worked with}

### Bullets

#### {ROLE_ID}-001
- **Tags:** {TAG, TAG}
- **Facts:**
  - {atomic claim}
  - Outcome: {literal outcome, number verbatim}
  - Mechanism: {how, as stated in the source}
- **Phrasings:**
  - "{pre-approved wording 1}"
  - "{pre-approved wording 2}"
<!-- from:SRC-001#section-or-line -->
