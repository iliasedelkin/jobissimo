# Truth Guardrails

The hard line. In strict + fire-and-forget mode, these rules are non-negotiable. The Generator must obey them; the Auditor enforces them mechanically.

---

## The core principle

The Generator is a **librarian**, not an author. It selects from and rephrases the contents of `knowledge/master_experience.md`, `knowledge/skills_inventory.md`, and `knowledge/education_credentials.md`. It does not invent.

If a fact isn't in those files, it doesn't go in the CV or cover letter. Full stop.

---

## Immutable elements (never edit)

For any bullet pulled from `master_experience.md`, the following are immutable:

1. **Employer name** (as stated in role header)
2. **Job title** (must match `Title (canonical)` or approved `Title (alt)`; nothing invented)
3. **Dates** (start and end; "Present" only where master says "Present")
4. **All numbers**: percentages, counts, durations, team sizes, revenue figures, margins, user counts, time savings
5. **Named technologies** (tools, languages, frameworks named in `Facts`)
6. **Named outcomes** (the literal outcome claim)
7. **Mechanisms** (how something was achieved – the specific means stated in `Facts`)

The Generator may NOT:
- Round metrics up or down.
- Combine two metrics into a composite (deriving "over 100% growth" from a 40% figure in one bullet plus a 70% figure in another).
- Promote scope ("10 locations" → "dozens of locations").
- Extend date ranges.
- Infer a title from scope (e.g. calling someone "Head of Product" because they did product work).

---

## Allowed transformations

The Generator MAY:

1. **Select** which bullets to include and which to omit.
2. **Paraphrase** within the fact boundaries – swap verbs, restructure a sentence, shorten.
3. **Pick among provided phrasings** in `master_experience.md`.
4. **Emphasize** a tag by choosing a phrasing that foregrounds that tag's vocabulary (e.g. "built" vs "orchestrated" for TECHNICAL vs LEADERSHIP framing of the same bullet).
5. **Reorder bullets** within a role.
6. **Omit older roles** entirely if the CV is too long.
7. **Normalize a title** per `tailoring_rules.md` § 10 – only using approved alternates from `master_experience.md`.

---

## Forbidden transformations

The Generator MAY NOT:

1. Combine facts from two different bullets.
2. Generalize a specific tool to a category it wasn't used in ("Python" → "full ML/AI stack" is forbidden; "Python" → "Python" stays).
3. Claim a skill without an entry in `skills_inventory.md` that has `Evidence` populated.
4. Insert a JD keyword that isn't in `jd_analysis.md` § Keyword-to-evidence matches.
5. Infer soft skills from context (don't write "excellent communication skills" – either demonstrate it through a specific bullet like a cross-functional outcome, or don't claim it).
6. Turn speculation or aspiration into experience ("interested in ML" does not become "ML experience").
7. Rephrase a canonical title as any variant not listed in `master_experience.md` for that role.

---

## Handling JD requirements you don't meet

Three strategies, in order of preference:

### 1. Omit silently
If the requirement is nice-to-have and your CV already demonstrates strength in the core must-haves, say nothing. Don't fabricate, don't apologize.

### 2. Transferable-skill bridge (cover letter only, not CV)
If the requirement is a must-have and you have adjacent experience, acknowledge briefly and name the transferable mechanism. See `cover_letter_playbook.md` § Handling gaps.

### 3. Honest acknowledgment
If the gap is central and can't be bridged, the Evaluator should have already returned REJECT. If generation is proceeding anyway, the cover letter acknowledges it rather than hiding it.

**Never:** adjacent-sounding claims that imply experience you don't have.

---

## Trace comment requirement

Every output element ties back to a source:

- **Experience bullets:** `<!-- src:BULLET_ID -->` at end of line, resolving to `master_experience.md`.
- **Education / awards / certification bullets:** `<!-- src:ENTRY_ID -->` at end of line, resolving to the coinciding entry in `education_credentials.md`.
- **CV skills (if a skill appears in the skills section):** Auditor verifies `skills_inventory.md` entry has `Evidence` populated. No trace comment needed on the skills line itself – verification is done against the inventory file.
- **CV summary:** `<!-- claims:BULLET_ID,BULLET_ID,... -->` at end of summary paragraph, listing every bullet whose facts are invoked.
- **Cover letter paragraphs:** `<!-- claims:BULLET_ID,... -->` at end of each paragraph that makes factual claims.
- **Cover letter claims about the company:** `<!-- claims:company:{source} -->`.

The Generator writes these. The Auditor validates and then strips them.

## Evidence map requirement

For chat-run generation, `evidence_map.md` is mandatory. It is the contract
between JD parsing and CV writing.

Rules:
- Every explicit JD must-have and high-value keyword must have one evidence-map
  row.
- `status = no_evidence` rows must never be claimed in the CV as existing
  experience, skills, tools, certifications, or domain knowledge.
- `status = explicit_match` and `status = implicit_match` rows may be used only
  through the cited evidence references.
- Any suggested additions to the candidate profile must be written to
  `gap_suggestions.md` until verified source evidence is added to `knowledge/`.

---

## Audit protocol (Auditor step)

The Auditor runs these checks in order. Any FAIL must be recorded explicitly in
`audit_log.md`. The pipeline does not silently continue past a FAIL, but the
user may review each failed check and choose one of three dispositions:

- `fix` – regenerate or edit the affected artifact and rerun audit
- `bypass` – explicitly accept the failed check for this application run
- `halt` – stop the pipeline for this job

The Auditor never chooses `bypass` on its own. That decision belongs to the user.

### Check 1 – Structural integrity
- Every bullet in `cv_draft.md` has a `src:` trace.
- Every narrative paragraph in `cover_letter_draft.md` has a `claims:` trace.
- Every experience `src:` trace resolves to an entry in `master_experience.md`.
- Every education / awards / certification `src:` trace resolves to the coinciding entry in `education_credentials.md`.
- Every cover letter `claims:` trace resolves to an entry in `master_experience.md`, `skills_inventory.md`, or (for company claims) to a cited source.
- `evidence_map.md` exists and contains at least one row for every JD must-have.

### Check 2 – Factual fidelity
For each experience bullet with `src:BULLET_ID`:
- Every numeric value in the output bullet appears in the `Facts` list of the source bullet.
- Every named technology in the output appears in the source `Facts`.
- The employer, title, and dates in the role header match the source role header exactly (modulo approved alternates).

For each education / awards / certification bullet with `src:ENTRY_ID`:
- The institution / award name, program or degree, and dates or year match the source entry in `education_credentials.md`.
- No credential, certification, or award metadata is added beyond the source entry's phrasing and declared fields.

### Check 3 – No fact combinations
For each bullet: all facts trace to a **single** source bullet. If any fact pairs cannot be found co-located in one source bullet, FAIL.

### Check 4 – Skills evidence
For each skill listed in the CV's Skills section:
- Entry exists in `skills_inventory.md`.
- Entry has at least one `Evidence` item.

### Check 5 – Keyword discipline
For each JD keyword identified in `jd_analysis.md` that appears in the CV:
- Keyword is in the "Keyword-to-evidence matches" list (not "unmatched").

For each keyword or requirement in `evidence_map.md`:
- `no_evidence` terms do not appear in `cv_draft.md` as possessed skills,
  completed work, certifications, tools, or domain experience.
- `explicit_match` and `implicit_match` terms that appear in the CV are tied to
  cited evidence references.

### Check 6 – Length and format
- CV ≤ 2 pages when rendered.
- Cover letter within the playbook's length band.
- No forbidden ATS elements (tables, images, custom section names – per `style_and_ats_rules.md`).
- No empty bullets, `None`, `TBD`, or placeholder text in user-facing files.

### Check 7 – Cover letter gap honesty
- No claim in the cover letter contradicts the gaps listed in `jd_analysis.md`.
- Gap-handling language (if present) matches an approved strategy.

### Output
- All PASS → strip trace comments → emit `cv_final.md` and `cover_letter_final.md` → pandoc export.
- Any FAIL → write `audit_log.md` with:
  - `OVERALL: FAIL`
  - one numbered failure item per failed check
  - for each item: `check_id`, `severity`, `finding`, `suggested_fix`
  - a `Disposition` field initialized to `pending user decision`
- After a FAIL, wait for the user's choice per failed item:
  - `fix`
  - `bypass`
  - `halt`

If the user chooses:
- `fix` → revise the artifact and rerun audit
- `bypass` → record the bypass in `audit_log.md` and continue only for that explicitly bypassed item
- `halt` → stop the pipeline for that job

### Bypass governance

- Bypass is allowed only when the user explicitly says so.
- Every bypass must be written into `audit_log.md` with:
  - failed `check_id`
  - short rationale
  - timestamp or run context
- A bypass does not rewrite history: the check remains a FAIL with user override, not a PASS.
- High-risk factual failures should still strongly recommend `halt` or `fix` rather than `bypass`.

---

## What to do when the rules conflict with what would "look better"

Don't. The rules win.

A slightly weaker CV with clean traceability beats a punchier one that makes a claim you can't defend in an interview. The point of strict mode is that every line in the output is something you can, if asked, walk a recruiter through and show them exactly where in your history it came from.

If the Generator finds itself wanting to invent – because the JD is pushing hard in a direction your experience doesn't cover – that's a signal the Evaluator should have caught the mismatch earlier, not a license to improvise.
