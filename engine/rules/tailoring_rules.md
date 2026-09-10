# Tailoring Rules

How the Generator turns a `jd_analysis.md` into specific decisions for the CV and cover letter.

---

## Inputs

- `jd_analysis.md` – structured JD analysis
- `evidence_map.md` – requirement-level match map; mandatory for chat-run generation
- `knowledge/master_experience.md` – bullet pool
- `knowledge/skills_inventory.md` – evidence-backed skills
- `knowledge/education_credentials.md`
- `positioning/candidate_profile.md`, `positioning/role_fit_map.md`, `positioning/positioning_library.md`
- `positioning/role_order.md` – this candidate's role-ordering and always-include
  decisions, generated at /setup S7 and maintained via /enrich (see §3, §7)
- `config/pipeline.yaml` – identity (name for the header), `years_experience`

## Outputs

- `cv_draft.md` – with `<!-- src:ID -->` trace on every bullet
- `cover_letter_draft.md` – with `<!-- claims:ID,ID -->` trace per paragraph
- `gap_suggestions.md` – advisory list of JD requirements that cannot be claimed

---

## 1. Headline selection

- Title comes from `positioning_library.md` for the detected cluster.
- If the JD's exact title is identical to one in the library's headlines, use that verbatim. Humans and ATS both reward the exact match.
- Never invent a seniority level. If the JD says "Senior" and the candidate has 5+ years in-cluster, "Senior" is allowed. Otherwise match library headline as-is.

## 1a. Mandatory contact block

Before writing any sections, emit this exact top-of-file structure:

1. `# {identity.full_name}` (from `applicant_profile.yaml`; audit checks it against `config/pipeline.yaml` identity.name)
2. headline line
3. contact line per `style_and_ats_rules.md` § Contact line

Hard rules:
- The contact line is mandatory in every CV draft.
- `## Summary` must come immediately after the contact block.
- Do not omit configured profile links (GitHub, LinkedIn) unless the underlying source files are explicitly changed.

## 2. Summary paragraph selection

- Pick the variant from `positioning_library.md` whose emphasis best matches the JD's must-haves.
- Lightly adjust to include **2 or 3** keywords from `evidence_map.md`, but only rows with `status = explicit_match` or `status = implicit_match` and `cv_action` containing `use_summary`.
- Never insert a keyword from `jd_analysis.md` unmatched keywords or an `evidence_map.md` row with `status = no_evidence`.
- Append the geographic framing per `positioning_library.md` § Universal elements.

## 3. Experience section – role ordering

Default order: reverse chronological. Exceptions live in
`positioning/role_order.md`, generated per candidate. The recurring cases it
must cover:

- **Dual-role periods** (two overlapping roles at one company): present the
  most relevant role for the cluster first; include the other only if space
  and relevance warrant.
- **Substantial programs that read as education** (a long engagement with a
  measurable client outcome): `role_order.md` may declare it a full
  Experience role rather than an education line.
- **Early career**: collapse into a single "Earlier experience" block or drop
  entirely if the CV exceeds 2 pages.

## 3a. Date formatting normalization

Before finalizing any CV line, normalize all date strings to the ATS format from
`style_and_ats_rules.md` § Date normalization:

- Experience headers: `(Mon YYYY to Mon YYYY)` or `(Mon YYYY to Present)`
- Education lines: same format whenever month data exists in source

Never emit:
- `--` in role headers
- ASCII hyphen ranges like `2009 - 2013`
- mixed date styles within one draft

## 4. Bullet selection per role

For each role included, pick 3–5 bullets using this priority:

1. Bullets referenced by `evidence_map.md` rows with `priority = must` and `status` in `{explicit_match, implicit_match}`.
2. Bullets whose tags intersect the JD's must-have competencies (from `jd_analysis.md` § Role content signals).
3. Bullets with the strongest metrics – especially metrics that align with outcomes mentioned in the JD.
4. Bullets matching the cluster's "Proof-point priority" in `positioning_library.md`.

Hard rules:
- **Never include more than 5 bullets per role.** Signal-to-noise matters.
- **Never include fewer than 2 bullets for a recent relevant role.** Looks like a gap.
- **Senior roles (last 5 years) get more bullets than older ones.**
- For tightly scoped applications, keep the CV to the 2–3 most relevant roles unless removing a role would create chronology confusion.
- De-emphasize or omit bullets with no JD overlap when the CV is crowded.

## 5. Bullet rephrasing (within fact boundaries)

The Generator may:
- Pick any of the `Phrasings` offered for a bullet.
- Rewrite a phrasing to emphasize a different tag while preserving all facts.
- Shorten a phrasing (never lengthen with new content).
- Swap synonyms for action verbs to match JD register (e.g. "drove" ↔ "led" – but avoid "spearheaded" unless the JD uses that register).

The Generator may not:
- Combine facts from two different bullets.
- Alter any number, percentage, date, title, employer, or technology.
- Add a mechanism or outcome not in the `Facts` list.
- Claim use of a tool or language not in `skills_inventory.md` with matching evidence.

## 5a. Figure de-duplication – one CV, one figure

A numeric figure (metric, count, timeframe – e.g. "10k+", "65%", "2 months")
may appear at most twice in the whole CV, and the second occurrence is allowed
only in the Summary as the single headline metric. Hard rules:

- **Never the same figure in two Experience bullets.** If two selected bullets
  share a figure, keep it in the bullet most load-bearing for the JD and use
  (or derive by shortening) a figure-free phrasing for the other. Omitting a
  number is always allowed; altering one never is.
- The Summary may echo at most **one** figure that also appears in a bullet;
  every other Summary claim stays figure-free.
- Timeframes count as figures: "two months" and "2 months" are the same figure.

## 6. Skills section selection

- Pull only skills whose `Evidence` field is populated.
- Prioritize skills named in `evidence_map.md` with `status = explicit_match` or `status = implicit_match`.
- Where the JD and the skills inventory describe the same evidenced skill with different wording, prefer the JD wording if it remains truthful.
- Group by categories (Programming / Data / Product / Methodologies / Languages).
- Cap total: 25 skills. More than that signals padding.
- Languages: always include – it's a fast human-scan signal.

## 7. Education & awards

The always-include credential list is per candidate, not per engine: it lives
in `positioning/role_order.md` § Always include (populated at /setup from
`education_credentials.md`, typically the highest degree, the most
role-relevant program, and any notable award). Optional inclusions
(case-by-case): portfolio/GitHub link, publications.

## 8. Cover letter delegation

The cover letter is generated per `cover_letter_playbook.md`. The tailoring decision here is only:
- Which 2–3 proof-point bullets to anchor the letter on (from `jd_analysis.md` § Positioning recommendation § Proof points).
- Which "gap handling" strategy to apply per `truth_guardrails.md` § Handling gaps.
- Tone register (startup / scale-up / corporate) from `jd_analysis.md` § Company signals.

## 9. Length targets

- **CV**: 1 page for <5 years experience, 2 pages for 5+ years (read
  `years_experience` from `config/pipeline.yaml`). Never 3 pages.
- **Cover letter**: per `cover_letter_playbook.md` § Length.

## 10. Title normalization

- A dual title like "Co-Founder & Head of Operations" may be presented as-is
  for startup audiences, or as "Head of Operations, {Company} (co-founded)"
  for corporate audiences where "Co-Founder" reads as volatility — but only
  if both forms are listed for that role in `master_experience.md`.
- Adjacent cluster titles (e.g. "Product Owner" vs "Product Manager"): use the
  `Title (canonical)` from `master_experience.md` unless the JD explicitly asks
  for the alt; alt use is allowed only when the candidate's actual scope fits
  and the alt is listed.
- Never invent seniority modifiers ("Senior", "Lead", "Head of") not present in canonical titles.

## 11. Keyword integration – the honesty test

Before inserting any JD keyword into the CV, run this check:
1. Does the keyword appear in `evidence_map.md` with `status = explicit_match` or `status = implicit_match`?
2. If yes → insert naturally in one of: summary (max 2 keywords), a role bullet where evidence lives, skills section.
3. If no → **do not insert.** Put it in `gap_suggestions.md` if it is material.

Keyword stuffing tells. ATS may be fooled for 8 seconds; humans aren't. Quality > keyword count.

## 11a. Evidence map contract

`evidence_map.md` is mandatory for chat-run generation. It must contain a row
for every explicit JD must-have and every high-value JD keyword that might be
useful for ATS.

Allowed statuses:
- `explicit_match`: direct support in `master_experience.md`, `skills_inventory.md`, or `education_credentials.md`.
- `implicit_match`: adjacent but defensible support in the source files.
- `no_evidence`: not safe to claim.

Allowed `cv_action` values:
- `use_summary`
- `use_experience`
- `use_skills`
- `cover_letter_only`
- `gap_only`
- `omit`

Hard rules:
- `no_evidence` rows cannot be presented in the CV as existing skills, tools,
  certifications, domains, or outcomes.
- Every `use_experience` row must cite at least one source bullet ID.
- Every `use_skills` row must cite a skill present in `skills_inventory.md` with
  populated evidence.
- Every `gap_only` row should appear in `gap_suggestions.md`, not the CV.

## 12. Output file requirements

`cv_draft.md` structure:
```
# {Name}
{Headline}
{contact line}

## Summary
{paragraph}

## Experience
### {Title}, {Company} (Mon YYYY to Mon YYYY)
- {bullet} <!-- src:BULLET_ID -->
- {bullet} <!-- src:BULLET_ID -->
...

## Skills
**{Category}:** {comma-separated list}
...

## Education
- {entry}

## Awards
- {entry}
```

Every bullet must carry a trace comment. No exceptions. The Auditor halts if any are missing.

Generator self-check before returning `cv_draft.md`:
1. Is the contact line present directly under the headline?
2. Do all experience date ranges use `(Mon YYYY to Mon YYYY)` or `(Mon YYYY to Present)`?
3. Do all education date ranges follow the same normalization rule?
4. Are there any ` -- ` or ` - ` date separators left in headers or education lines?
5. Does any numeric figure appear more than once across Summary + Experience
   bullets (beyond the single allowed headline echo, per §5a)? If yes, swap in a
   figure-free phrasing before returning the draft.

If the answer to question 4 or 5 is "yes", rewrite before returning the draft.
