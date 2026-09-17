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
  credible-now/with-framing/stretch verdict). An optional top-level `common:`
  block holds competencies shared by every cluster, so a pack whose clusters
  overlap heavily states them once:

  ```yaml
  common:
    competencies: [version control, code review, automated testing]
  clusters:
    Web:
      competencies: [...]    # the 20% that is genuinely Web-only
  ```

  `common` is merged into every cluster and is never itself a cluster id. Use
  it when clusters share most of a competency set; a pack whose clusters
  barely overlap does not need it.
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

## The config layer: overriding a pack without editing it

A pack is never edited in place. An install's own additions live in the
workspace `config/` directory, using the same filenames and the same shape:

| Pack file | Config override |
|---|---|
| `roles.yaml` | `config/roles.yaml` |
| `ats_keywords.yaml` | `config/ats_keywords.yaml` |
| `ats_synonyms.yaml` | `config/ats_synonyms.yaml` |
| `locales/<code>.yaml` | `config/locales/<code>.yaml` |

**The config layer extends the pack; it does not replace it.** "Last wins"
applies per term, not per file: a config file that omits a pack term does not
remove it, and re-stating one is a harmless no-op. That is deliberate — it
means adding a term can never silently drop the pack's own vocabulary. There
is currently **no way to remove a pack term from config**; if a pack ships a
wrong term, fix the pack (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

In `config/roles.yaml` a cluster id that already exists in the pack extends
that cluster's competencies; a new id defines a new cluster, competencies
included. `extra_role_clusters` in `config/pipeline.yaml` still registers a
bare cluster id with no competencies, and remains the shortest way to add one.

Inspect what resolved on this install:

```bash
python3 scripts/packs.py     # active pack, clusters, synonym + keyword files
```

## The generic fallback

`generic` is deliberately near-empty. Because the scorer extracts keywords
from the JD itself, scoring still works with almost no lexicon; `/setup`
seeds a starter taxonomy from the user's own documents and writes it as config
overrides (see the table above for where each file lands). Use it to bootstrap
a role family no pack covers yet — then consider contributing the pack
upstream.

## Where a pack lives

A pack resolves from two places, in order:

| Order | Location | What lives there |
|---|---|---|
| 1 | `<workspace>/packs/<name>` | **your** packs — forked or written from scratch |
| 2 | `packs/<name>` (engine checkout) | the shipped, community-maintained packs |

A workspace pack **shadows** a shipped pack of the same name — that is how an
install takes ownership of one. Because it lives in the workspace it travels
with `/sync` to your other machines, it is never a commit on a repo you do not
own, and a `git clean -xfd` in the engine checkout cannot touch it.

```bash
python3 scripts/packs.py --list                      # every pack + where it came from
python3 scripts/packs.py --fork product --as myprod  # take ownership of a copy
python3 scripts/packs.py --validate myprod           # structural check
```

Forking gives you the whole pack — including `evaluation.md` and
`figure_nouns`, which have no config override and cannot be tuned any other
way. The trade-off is that a fork stops receiving upstream improvements, so
prefer the config layer above for small deltas and fork when you need real
control.

`packs/generic` is marked `scaffold: true`: it is intentionally incomplete, so
the finished-pack checks are skipped for it and it cannot be exported under
that name. Forking it clears the flag — the fork is a real pack.

## Contributing a pack back

```bash
python3 scripts/packs.py --export <name>
```

Copies a workspace pack into the engine checkout so you can open a PR. Before
it copies anything it validates the structure and runs the **scrub gate** over
a staging copy — a pack you have been using carries competency wording and
board notes drawn from real applications, and none of that belongs in a public
repo. Nothing is written if the gate finds anything.

The scrub runs on a staging copy rather than the pack in place because
`scrub_check.py` skips directories named `profile` (the default workspace
name), so scanning the source would silently pass on a default install.

## Building a pack

```bash
python3 scripts/packs.py --fork generic --as <yourdomain>
```

Fill in the files above in `<workspace>/packs/<yourdomain>/` and set
`pack: <yourdomain>` in `config/pipeline.yaml`. Build it in the workspace, not
in the engine checkout: it is yours, it syncs, and it survives a `git clean`.
When it works, `--export` it and add a fixture and a test.
See [CONTRIBUTING.md](../CONTRIBUTING.md).
