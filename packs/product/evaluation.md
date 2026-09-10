# Job Evaluation Rubric — product pack

The evaluation dimensions for scoring a posting's fit. This file holds the
**rubric**; the candidate's own numbers live in `config/targets.yaml`
(baseline years, geography, preferred stages), and observed calibration
evidence lives in the `/optimise`-owned calibration block there. A pack is
never edited in place — propose rubric changes upstream.

## Evaluation Dimensions

### 1. Role Fit
- Match with the ranked targets in `config/targets.yaml`
- Presence of product / analytics / systems thinking

---

### 2. Seniority Match

Score by **years required in the JD**, not by title, against
`targets.yaml → seniority.baseline_years` (call it B):

- ≤B years required (or none stated), mid-level title → `yes` – core target
- "Senior" title but ≤B years required (small-company title inflation) → `yes`
- "Senior" requiring more than B years → `stretch_up`; recommendation caps at
  `maybe`, priority caps at `medium`
- Staff / Lead / Principal / B+2 or more years → `stretch_up`; recommendation
  `no` unless exceptional must-have overlap (then `maybe`)
- Junior/entry roles (0–2 years) at otherwise strong-fit companies →
  `stretch_down`, recommendation `maybe` – a **controlled experiment**; flag
  overqualification/salary risk in `red_flags` and keep the tranche small
  (`targets.yaml → seniority.stretch_down_cap_in_flight`, default 2–3 in
  flight) until responses land
- Director/VP → avoid (unless early-stage startup scope fits mid-senior)

Judge seniority from the **JD body** (responsibilities, years, reporting
line), never a portal's seniority tag, which is frequently wrong in both
directions.

---

### 3. Company Fit

Preferred and avoided company profiles come from
`config/targets.yaml → company_preferences`. Typical strong profile for this
pack: product-led startups/scale-ups, data-heavy or AI/SaaS environments,
remote-first or international. Typical avoid: large corporate hierarchies,
PMO-driven orgs, non-digital industries.

---

### 4. Role Content Signals

Strong signals:
- Discovery + execution
- KPI ownership
- Data-driven decision-making
- Cross-functional ownership

Weak signals:
- Pure coordination
- Limited strategic input

Reject signals:
- Ticket execution only
- No access to data
- No ownership

---

### 5. Technical & Data Signals

Positive:
- SQL, Python, BI tools
- Experimentation / A/B testing
- Analytics infrastructure

Negative:
- Spreadsheet-only environments
- No tooling mentioned

---

### 6. Growth Potential

Important for BA / Analyst roles:

Must have:
- Clear PM/PO transition path

---

### 7. Location & Work Mode Fit

Candidate constraints come from `config/targets.yaml → geography`.
Interpretation template:

Strong signals:
- Fully remote (global, or friendly to the candidate's region)
- Remote-first company
- Hybrid/on-site inside the candidate's onsite-ok regions

Weak signals:
- Relocation required but not clearly supported
- Hybrid with unclear flexibility
- On-site outside the ok-regions with no relocation support

Reject signals:
- Location-restricted roles the candidate cannot satisfy (e.g. single-country
  eligibility without visa support)

Interpretation:
- Remote roles = no penalty
- In-region roles = no penalty
- Supported relocation = small friction penalty
- Unsupported out-of-region on-site = major penalty or reject

**Region strings are marketing copy.** A portal location like "European
Economic Area" or "EMEA" is not an eligibility list — the employer's ATS page
carries the contractual country list. For region-tagged postings, resolve the
employer posting and read the eligible countries *before* recording
`location_fit: match`.

---

### 8. Universal Positive Signals

- Remote-first
- AI / automation usage
- Cross-functional ownership
- Growth-stage environment

---

### 9. Universal Red Flags

- "Reporting to PMO"
- Waterfall-only
- Corporate background requirement
- No product/data ownership

---

### 10. Velocity SLA

For any job with `fit_score ≥ 4.0` and `apply_recommendation = yes`:
- Prepare and apply within the configured window
  (`config/pipeline.yaml → thresholds.velocity_sla_days`, default **5
  calendar days**) of discovery.
- If preparation is delayed beyond the window, verify the posting is still
  active before starting.
- Most postings in fast markets expire in 7–14 days;
  shortlisted-but-unprepared is the largest avoidable loss in the pipeline.
