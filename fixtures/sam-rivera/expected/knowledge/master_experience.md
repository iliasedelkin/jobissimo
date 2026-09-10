# Master Experience — Sam Rivera

The single source of truth for work history. Every bullet below is a factual
claim the generator may **select and rephrase**. It may never be combined
with facts from other bullets, re-metricized, or generalized.

(Fixture: the extraction a correct /setup S2 produces from the sam-rivera
source documents. SRC-001 = cv_2024.md, SRC-002 = cv_2025.docx,
SRC-003 = linkedin_export, SRC-004 = old_cover_letter.txt.)

---

## Schema

Each role has a `ROLE_ID`. Each bullet has a `BULLET_ID` in the form
`{ROLE_ID}-{NNN}`. A bullet contains **Tags**, **Facts** (atomic, immutable),
and **Phrasings** (1–3 pre-approved wordings).

**Competency tags:**
`PRODUCT` `ANALYTICS` `TECHNICAL` `LEADERSHIP` `OPERATIONS` `DISCOVERY` `DELIVERY` `SUPPORT`

---

## ROLE: FERN-PM — Fernwood Labs, Product Manager

- **Company:** Fernwood Labs
- **Stage:** B2B SaaS, mid-size (workforce analytics)
- **Industry:** Workforce analytics software
- **Work mode:** Hybrid (Milan)
- **Period:** Aug 2022 – Present
- **Title (canonical):** Product Manager
- **Title (alt, use only if JD scope matches):** Product Owner
- **Team context:** Cross-functional — engineering, design, support

### Bullets

#### FERN-PM-001
- **Tags:** PRODUCT, ANALYTICS, DELIVERY
- **Facts:**
  - Led the onboarding redesign
  - Outcome: trial-to-active activation up 18%
  - Mechanism: funnel analysis + weekly experiment cadence
- **Phrasings:**
  - "Led the onboarding redesign, raising trial-to-active activation by 18% through funnel analysis and a weekly experiment cadence."
  - "Redesigned onboarding around funnel analysis and weekly experiments, lifting trial-to-active activation 18%."
<!-- from:SRC-001#experience-fernwood, SRC-002#experience-fernwood -->

#### FERN-PM-002
- **Tags:** DISCOVERY, PRODUCT, DELIVERY
- **Facts:**
  - Shipped a self-serve reporting module
  - Outcome: adopted by 40+ enterprise accounts
  - Mechanism: discovery interviews with 25 customers
- **Phrasings:**
  - "Shipped a self-serve reporting module now used by 40+ enterprise accounts, shaped by discovery interviews with 25 customers."
  - "Ran discovery interviews with 25 customers and shipped the self-serve reporting module adopted by 40+ enterprise accounts."
<!-- from:SRC-001#experience-fernwood, SRC-002#experience-fernwood, SRC-004#body -->

#### FERN-PM-003
- **Tags:** PRODUCT, SUPPORT, OPERATIONS
- **Facts:**
  - Introduced a customer feedback triage process
  - Mechanism: connects support tickets to the product backlog
  - (no metric in any source — queued for metric rescue)
- **Phrasings:**
  - "Introduced a customer feedback triage process connecting support tickets to the product backlog."
<!-- from:SRC-001#experience-fernwood, SRC-002#experience-fernwood -->

#### FERN-PM-004
- **Tags:** TECHNICAL, PRODUCT
- **Facts:**
  - Partnered with engineering on public API integrations
  - Scope: customer data imports
  - (no metric in any source — queued for metric rescue)
- **Phrasings:**
  - "Partnered with engineering on public API integrations for customer data imports."
<!-- from:SRC-001#experience-fernwood, SRC-002#experience-fernwood -->

---

## ROLE: HARB-OA — Harborline Logistics, Operations Analyst

- **Company:** Harborline Logistics
- **Industry:** Logistics
- **Work mode:** Onsite (Rotterdam)
- **Period:** May 2019 – Jul 2022
- **Title (canonical):** Operations Analyst
- **Team context:** Regional operations teams

### Bullets

#### HARB-OA-001
- **Tags:** TECHNICAL, ANALYTICS, OPERATIONS
- **Facts:**
  - Automated the weekly capacity report
  - Stack: SQL + scripting
  - Outcome: saving 5 hours of manual work per week
- **Phrasings:**
  - "Automated the weekly capacity report with SQL and scripting, saving 5 hours of manual work per week."
<!-- from:SRC-001#experience-harborline, SRC-002#experience-harborline, SRC-003#positions -->

#### HARB-OA-002
- **Tags:** ANALYTICS, TECHNICAL
- **Facts:**
  - Built the KPI dashboard used by 3 regional teams
  - Stack: SQL views + Metabase
- **Phrasings:**
  - "Built the KPI dashboard used by 3 regional teams, on SQL views and Metabase."
<!-- from:SRC-001#experience-harborline, SRC-002#experience-harborline -->

#### HARB-OA-003
- **Tags:** ANALYTICS, OPERATIONS
- **Facts:**
  - Analyzed carrier performance data
  - Outcome: supported contract renegotiations that cut late deliveries by 12%
- **Phrasings:**
  - "Analyzed carrier performance data and supported contract renegotiations that cut late deliveries by 12%."
<!-- from:SRC-001#experience-harborline, SRC-002#experience-harborline -->

---

## ROLE: BRIGHT-CS — Brightpath Learning, Customer Support Team Lead

- **Company:** Brightpath Learning
- **Industry:** EdTech
- **Work mode:** Onsite (Chicago)
- **Period:** Jan 2016 – Apr 2019
- **Title (canonical):** Customer Support Team Lead
- **Team context:** Support team, two markets

### Bullets

#### BRIGHT-CS-001
- **Tags:** SUPPORT, OPERATIONS, LEADERSHIP
- **Facts:**
  - Cut average first-response time, starting point 6 hours
  - Mechanism: introduced a shared triage queue
  - CONTRADICTION: SRC-001 and SRC-003 say "to 90 minutes"; SRC-002 says
    "to 45 minutes". Unresolved — do not use this bullet's end figure until
    the user picks one (S3 / /enrich).
- **Phrasings:**
  - "Cut average first-response time from 6 hours by introducing a shared triage queue."
<!-- from:SRC-001#experience-brightpath, SRC-002#experience-brightpath, SRC-003#positions -->

#### BRIGHT-CS-002
- **Tags:** LEADERSHIP, SUPPORT
- **Facts:**
  - Led a team of 6 support agents
  - Scope: two markets
- **Phrasings:**
  - "Led a team of 6 support agents across two markets."
<!-- from:SRC-001#experience-brightpath, SRC-003#positions -->
