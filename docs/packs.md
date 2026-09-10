# Domain packs

A **pack** is the role family the pipeline targets. It is pure config —
building one requires no engine changes — and it is the highest-value
contribution to this project.

## What a pack provides

```
packs/<name>/
├── pack.yaml            manifest: name, description, figure_nouns
├── roles.yaml           role clusters + canonical competencies
├── evaluation.md        the fit rubric (no candidate-specific numbers)
├── ats_keywords.yaml    hard/soft skill lexicon (classifier + booster)
├── ats_synonyms.yaml    wording bridges (never skill bridges)
├── boards.yaml          board catalogue + alert sender domains
└── locales/
    ├── en.yaml it.yaml  verified market conventions + synonym bridges
    └── de.yaml ...      unverified stubs (neutral fallback)
```

Schema: `engine/schemas/pack.schema.json`.

## How each file is used

- **`roles.yaml`** — the cluster ids are the values `db.py` accepts for
  `role_cluster`. Each cluster's canonical competency set is what `/setup` S6
  scores a candidate's evidence fit against (coverage %, gaps, a
  credible-now/with-framing/stretch verdict).
- **`evaluation.md`** — the fit rubric dimensions. Keep candidate numbers out:
  baseline years and geography belong in a user's `config/targets.yaml`.
- **`ats_keywords.yaml`** — the scorer extracts keywords from each JD itself,
  so this is a **classifier** (hard vs soft) plus a known-skill booster, not
  the candidate source. Keep `soft_skills` accurate.
- **`ats_synonyms.yaml`** — wording bridges only. `product management` ↔
  `product manager` is a bridge; `SQL` ↔ `Python` is a truth violation. A bad
  synonym silently defeats the guardrails, so this rule is absolute.
- **`boards.yaml`** — tiered board catalogue with *factual* access notes (403
  as of a date, login-walled, no posting dates) and *neutral* yield guidance
  (company-direct above aggregators; new aggregators on probation). Not your
  private outcome numbers. Also `alert_sender_domains` for mail discovery.
- **`locales/`** — see [languages.md](languages.md).

## The reference pack

`product` covers Product Owner / Product Manager / Business Analyst / Project
Manager / Product-Growth Analyst / Operations. Read it as the worked example.

## The generic fallback

`generic` is deliberately near-empty. Because the scorer extracts keywords
from the JD itself, scoring still works with almost no lexicon; `/setup`
seeds a starter taxonomy from the user's own documents and writes it as config
overrides. Use it to bootstrap a role family no pack covers yet — then
consider contributing the pack upstream.

## Building a pack

Copy `packs/generic/` to `packs/<yourdomain>/`, fill the files above, and set
`pack: <yourdomain>` in `config/pipeline.yaml`. Add a fixture and a test if
you are contributing it back. See [CONTRIBUTING.md](../CONTRIBUTING.md).
