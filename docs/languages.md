# Languages and locales

The pipeline generates each application in the **posting's language** while
keeping the structural skeleton canonical, so the deterministic audit/ATS
chain never needs to understand the target language.

## The canonical / localised split

| Localised (posting's language) | Canonical (never localised) |
|---|---|
| CV summary and experience bullet text | Section headers: `## Summary`, `## Experience`, `## Skills`, `## Education`, `## Awards` |
| Cover letter, recruiter message, follow-up | Dates: `(Mon YYYY to Mon YYYY)` / `(Mon YYYY to Present)`, English months, the literal word "to", "Present" |
| Application-form answers | Skills-inventory item names (industry-English terms) |
| | Employer names, technology names, all numbers |
| | Internal artefacts (jd_analysis, evidence_map, notes, gap_suggestions) — English |

`audit.py` and `ats_score.py` key on the canonical elements. Translation is a
**paraphrase within fact boundaries**: numbers, technologies, employers,
titles, and dates are immutable, and a translation must never smuggle in a
stronger claim.

## The register cap

`config/languages.yaml` records a CEFR level per language. The generator
**never writes above that register** — you have to defend every line in an
interview. B2 means plain, concrete sentences you would write yourself; no
ornate constructions. See `engine/rules/language_rules.md`.

## Market conventions are per-locale

Whether a CV carries a personal-details block (date of birth,
residence/authorization status) or a photo is a **market decision, not a
global one**. It is conventional in some markets and an age-discrimination
anti-pattern in others. Each configured language loads its conventions from
the active pack's `locales/<code>.yaml`:

```yaml
verified: true
personal_details_block: conventional   # conventional | anti_pattern | unknown
personal_details_fields: [date_of_birth, residence_permit]
photo: unknown
cv_length_norm: "2 pages"
formality: "professional; plain and concrete"
synonyms:            # JD-vocabulary bridges into the English taxonomy
  requirements: [requisiti]
```

The `product` pack ships `en` and `it` **verified**; `de`, `fr`, `es`, `nl`,
`pt` ship as **stubs** (`verified: false`) that fall back to neutral behaviour
— no block, no photo, no invented convention.

## Adding or verifying a locale

A small, well-scoped, high-impact contribution for a market you know:

1. Edit `packs/<pack>/locales/<code>.yaml`, set `verified: true`.
2. Fill `personal_details_block`, `photo`, `cv_length_norm`, `formality` —
   and state *why* a convention holds (one line; that rationale is what makes
   the file trustworthy).
3. Add `synonyms:` bridges for common JD vocabulary → English taxonomy
   groups. **Wording only** — a bridge must describe the same evidenced
   skill, never a neighbouring one.
4. Configure it in your `config/languages.yaml` with your proficiency.

`/doctor --languages` shows configured languages, proficiencies, and locale
verification status, and walks you through changes.
