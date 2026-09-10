# Style & ATS Rules

Universal formatting rules for CV output. Optimized for both ATS parsers and human scanners.

---

## Canonical format

- **Generation target:** Markdown (`.md`).
- **Submission formats:** produced via Pandoc: `.docx` (primary, most ATS-reliable) and `.pdf` (secondary, from the same `.docx`).
- **Pandoc command (reference):**
  ```
  pandoc cv_final.md -o cv.docx --reference-doc=templates/ats_reference.docx
  pandoc cv_final.md -o cv.pdf
  ```
  The reference doc controls font and spacing; the shipped `templates/ats_reference.docx` uses a plain single-column template in Calibri/Arial 11pt.

---

## ATS-safe structural rules

**Do:**
- Single column, left-aligned.
- Standard section headers: `Summary`, `Experience`, `Skills`, `Education`, `Awards`. No creative renaming.
- Plain bullet points (hyphens in Markdown render as bullets in DOCX).
- Dates in parenthetical format `(Mon YYYY to Mon YYYY)` or `(Mon YYYY to Present)`.
- Company, role, dates on their own line, consistently ordered.
- Contact line: Name, headline, city + country, phone, email, LinkedIn, GitHub – in that order, single line or two short lines.
- Treat the contact block as mandatory CV content, not optional metadata.
- Normalize every date before writing the draft. Never emit raw forms like `2021 - Present`, `2009 - 2013`, or role headers with `--`. The word "to" connects the range — no en dash, em dash, or hyphen inside the duration.

**Don't:**
- Tables, columns, text boxes, headers/footers – ATS parsers skip or misread these.
- Images, icons, or graphics of any kind.
- Text rendered as an image.
- Unusual Unicode characters (✓ ★ ⚡ etc.) – stick to ASCII.
- Fancy separators (━━━, ❖). Horizontal rules (`---`) are fine; Pandoc renders them as plain horizontal lines.
- **Em dashes (—) anywhere in generated content.** Use an en dash (–) with a space on each side as the content separator instead (e.g. `rebuilt the reporting pipeline – cutting the weekly close from days to hours`). Regular hyphens (-) remain correct for compound words like "cross-functional" or "data-driven".
- Hyperlinks in place of readable text ("my portfolio" is fine; a bare URL is better in the contact line).
- Page numbers, watermarks, or page-break tricks.
- Abbreviations a non-domain reader wouldn't know. Spell out first use: "KPIs (key performance indicators)" on first mention only if the JD audience warrants it.

---

## Bullet structure

Each bullet follows: **Action verb → Mechanism → Quantified result.**

Shape examples (fictional):
- Good: "Built a self-serve analytics layer (SQL + a BI tool) that cut ad-hoc reporting requests by 40%."
- Good: "Automated the weekly revenue export (scripting + REST API), reducing a 4-hour manual task to minutes."
- Bad: "Responsible for analytics." (no action, no result)
- Bad: "Worked cross-functionally with stakeholders to drive alignment on outcomes." (verbs without content)
- Bad: "Passionate about building data-driven products." (belongs in the summary, not a bullet)

### Length
- Target: 15–25 words per bullet.
- Hard max: 30 words. Break into two if longer.
- Hard min: 8 words. Shorter bullets look thin.

### Count per role
- Most recent / most relevant role: 3–5 bullets.
- Older or less relevant: 2–3 bullets.
- Any role included must have ≥ 2 bullets, or it looks like a listing gap.

### Verb register
- Use past tense for past roles, present tense for current role. Don't mix.
- Prefer: built, led, drove, designed, shipped, scaled, automated, reduced, increased, orchestrated.
- Avoid: helped, assisted, participated, was responsible for, worked on, contributed to. These are low-ownership verbs.
- Avoid thesaurus-reach: "spearheaded", "catalyzed", "unleashed", "pioneered". These read as filler.

---

## Summary section

- One paragraph, 3–5 sentences, 50–80 words.
- No first-person pronouns. Third-person-implied voice.
- No adjective stacking ("dynamic, results-oriented, passionate").
- Lead with the role noun and years of experience. End with a differentiator (education award, unusual domain, etc.).

---

## Skills section

Group by category, comma-separated within each group (shape example — the
actual items come only from `knowledge/skills_inventory.md`):

```
Programming: <evidenced languages>
Data & Analytics: <evidenced tools and methods>
Product: <evidenced product skills>
Languages: <spoken languages with CEFR levels>
```

Rules:
- No proficiency bars, star ratings, or visual skill graphs.
- Numeric proficiency for languages only (CEFR levels).
- Max 5–7 skills per category; too many signals padding.
- Total skills cap: 25. The rest are in the role bullets where they're proven.

---

## Education & Awards

- One line per entry. `Institution – degree/program (Mon YYYY to Mon YYYY)`. An en dash (–) with spaces separates institution from program (content, not duration); the duration itself uses the parenthetical "to" form with no dash.
- Awards: one line per award, with year and one-phrase context. A single year (e.g. `(2023)`) needs no range.

---

## Contact line

The rendered contact block is templated from the workspace's
`applicant_profile.yaml` — never hardcoded. Shape:

```
# {identity.full_name}
{headline — cluster-dependent, from positioning_library}
{identity.location_city}, {identity.location_country} | {identity.phone} | {identity.email} | {links.linkedin} | {links.github}
```

- Use readable URLs, not hyperlink text. A bare `linkedin.com/in/<handle>` parses cleanly in ATS; `[LinkedIn](...)` may not.
- Phone in international format with `+`.
- For fully-remote applications: the plain `{city}, {country}` line is fine – it signals your timezone.
- For relocation openings: append `– open to relocation` to the city line.

Hard rule:
- Every CV draft must start with this three-line block shape before `## Summary`:

  1. `# {identity.full_name}`
  2. headline line
  3. contact line

- If line 3 is missing, the draft is structurally invalid.

## Date normalization

Canonical duration format is **parenthetical, with the word "to" as the range
connector and no dashes inside the duration**. This is more organic to read and
parses cleanly in every major ATS (Workday, Greenhouse, Lever, Taleo), which all
handle "to" ranges at least as reliably as a Unicode en dash.

- Always use abbreviated month + year:
  `Jan`, `Feb`, `Mar`, `Apr`, `May`, `Jun`, `Jul`, `Aug`, `Sep`, `Oct`, `Nov`, `Dec`.
- Experience role header shape:
  `### {Role}, {Company} (Mon YYYY to Mon YYYY)` or `(Mon YYYY to Present)`.
  No `—` separator before the dates — the parentheses carry the duration.
  Example: `### Product Manager, Example Corp (Mar 2021 to Present)`.
- Range connector is the literal word `to`, surrounded by single spaces, inside
  parentheses: `(Mar 2021 to Present)`, `(Sep 2009 to Jun 2013)`.
- Do not use inside a duration:
  `–` (en dash), `—` (em dash), `--`, `-`, the word `present` lowercased, bare
  years without parentheses, or mixed formats within one CV.
- Education entries follow the same range rule: `2009 - 2013` is invalid;
  `(Sep 2009 to Jun 2013)`, or `(2009 to 2013)` only if month data is unavailable
  in source.

Legacy note: assets already submitted under the old en-dash format
(`Mar 2021 – Present`) remain valid — the audit still accepts the en dash so
historical applications do not fail re-validation. New drafts use "to".

---

## Trace comments

Every bullet in the draft carries `<!-- src:BULLET_ID -->` at the end of the line. The Auditor strips these before export. In Markdown the comment is invisible when rendered; Pandoc removes it. They exist only in the draft.

---

## Common failures to catch at review

- Inconsistent date formatting (e.g. "2021 - Present" vs "Mar 2021 to Present" in the same CV), or a stray dash left inside a duration.
- Missing contact line between the headline and `## Summary`.
- Bullets that describe responsibilities instead of outcomes.
- Summary paragraphs that could describe any candidate in the cluster.
- Skills listed without corresponding evidence in a role bullet.
- Keywords appearing in summary but not anywhere else in the CV – obvious stuffing.
- Over-2-page length for candidates with < 15 years experience.
