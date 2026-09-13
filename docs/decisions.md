# Decisions

The judgement calls made porting the private pipeline to this OSS project.
When the brief and the source repo could both be honoured, the rule was:
preserve current behaviour, parameterise the personal value, record it here.

## Structure

- **One gitignored workspace root (`$JOBISSIMO_HOME`, default `profile/`)**
  replaces the private repo's eight scattered personal-data directories.
  `scripts/paths.py` resolves it and every script/command goes through it, so
  the personal-data rule is mechanical and multiple workspaces (needed for the
  migration parity check) are free.
- **`$JOBISSIMO_CONFIG`** override added alongside it, so the test suite and
  parity runs can point at a fixture config without a real `config/`.
- **`packs.py` ships a stdlib mini-YAML reader** rather than adding a PyYAML
  dependency — the anti-goals forbid new dependencies, and the config/pack
  files stay within a small, documented YAML subset. Deferred improvement:
  if pack authors need richer YAML, revisit (would need PyYAML).

## Parameterising the scripts

- **`audit.py` name check** reads `identity.name` from `config/pipeline.yaml`.
  When unset, it falls back to requiring any `# ` header (with a warning via
  `/doctor`), so a half-configured workspace still audits.
- **`audit.py` `FIGURE_RE`** became a generic quantity pattern plus a
  pack-supplied `figure_nouns` list (`packs/<name>/pack.yaml`), replacing the
  private repo's hardcoded noun set. Number words two–ten are handled
  generically.
- **`audit.py` gained `--library` mode** for the /setup S7 requirement to
  audit a generated positioning library at birth. The brief specified the
  behaviour but the private `audit.py` had no such mode; added without changing
  folder-mode behaviour.
- **`db.py` role clusters and location-fit** load from pack + config and
  validate against that UNION values already present in the DB, so imported
  historical rows never fail. `ROLE_CLUSTERS`/`LOCATION_FIT` constants are
  gone.
- **`export.py` / `ats_score.py`** reference `templates/ats_reference.docx`
  and the pack lexicons through `paths.py` / `packs.py`.

## Content that was welded to a person

- **Contact block, tailoring role-ordering, always-include credentials,
  title normalisation** were de-personalised: the *rules* stay in
  `engine/rules/`, and each personal instance becomes a config/profile lookup.
  Role-ordering and always-include decisions move to a generated
  `positioning/role_order.md` (per candidate), which tailoring_rules §3/§7
  now reference.
- **`job_evaluation_rules.md`** split three ways exactly as the brief
  specified: rubric dimensions → `packs/product/evaluation.md`; thresholds and
  geography → `config/targets.yaml`; calibration → an `/optimise`-owned block
  in `targets.yaml`.
- **`language_rules.md`** generalised from the single hardcoded Italian case to
  per-locale conventions (`packs/<pack>/locales/<code>.yaml`) + declared
  proficiency (`config/languages.yaml`). The `it` rule (personal-details block
  conventional in Italy, anti-pattern in Anglo markets) ports verbatim with its
  rationale.
- **`hunt.md`** target profile → `config/targets.yaml`; tier tables →
  `packs/product/boards.yaml` + `config/boards.yaml`; the pipeline mail
  account → `config/pipeline.yaml`; LinkedIn extraction technique →
  `engine/adapters/browse/claude-in-chrome.md` (with a dated-notes caveat).
- **ATS lexicons** port near-verbatim (they carry no personal content and are
  the pack's most valuable asset). The Italian synonym bridges split out into
  `locales/it.yaml`.
- **`boards.yaml`** keeps the tier structure and factual access notes but
  **not the owner's outcome numbers**; those became neutral yield guidance
  (company-direct above aggregators; aggregators on probation; two barren
  probes demote a tier).

## Commands

- The private scheduled `SKILL.md` files (a split-brain: the scheduled hunt
  and the manual hunt behaved differently, and the broadened alert-sender list
  lived only in the scheduled file) are unified into a single `/brief` command,
  with the sender domains in `packs/product/boards.yaml`. The hard-won
  survival machinery (skeleton-first, per-phase starvation guard, browser
  probe, single-hunt lock, same-day archive) is ported into `/brief` and
  documented in `docs/scheduling.md`.
- **New commands** `/setup`, `/enrich`, `/doctor` were written from the brief's
  §6/§7 (no private equivalent to port).

## Fixtures and tests

- **Public test suite is deterministic and offline.** The LLM-driven /setup S2
  extraction cannot run in CI, so it is represented by the checked-in
  `fixtures/sam-rivera/expected/` output; the deterministic scripts around it
  (intake, competency_map, coverage, audit, ats_score, db) are tested
  end-to-end against that fixture, and the first-result milestone (audit PASS +
  ATS ≥ 75) is asserted directly. This is the honest public analogue of the
  private parity gate in `docs/migration.md`.
- **The fixture candidate (Sam Rivera) is wholly invented** and shares nothing
  with the owner's real career. Its planted imperfections (a first-response-time
  contradiction across CV versions, two unquantified bullets, an unevidenced
  Figma claim) exercise the contradiction/metric-rescue/unevidenced paths.
- **`scrub_check.py`** carries a hashed denylist (SHA-256 of known-personal
  tokens — the repo stores hashes, never strings) on top of generic detectors.
  The test file assembles its planted-leak strings at runtime so the test
  source itself passes `scrub_check --all`.

## Migration parity finding (post-cutover)

Running the ATS parity gate over a migrated workspace (~90 real prepared
folders) showed ±1–2 drift vs the recorded `ats_report.md` scores, not the
bit-identical result the gate ideally wants. Investigated to root cause:

- **Dominant cause — scorer evolution, not the port.** The recorded reports
  were written at prepare-time by whatever scorer version was live that day,
  and the private scorer's keyword-extraction stopword list grew over the
  campaign to filter portal boilerplate. Old reports literally list `job`,
  `full`, `job description` as extracted "hard skills" — tokens the *current*
  stopword list (private and OSS alike) removes. Re-scoring old apps with any
  current engine differs from those reports; the current private engine would
  differ too. The recorded snapshots are a mixture of scorer versions, not a
  single consistent baseline — so vs-recorded parity is the wrong pass/fail
  gate for judging the port.
- **One genuine port change, and it is a fix.** The private
  `ats_score.py` hardcoded a single city token (`"milan"`) in `EXTRACT_STOP` —
  personal data in the engine, and the wrong city for most users. The
  OSS engine replaces it with `geo_stopwords()`, reading `base_city` from
  `config/targets.yaml` (city only, to match the private single-token
  behaviour). This both de-personalises and corrects the leak.

Conclusion: the port is faithful; the drift is understood and benign (a CV at
62 vs 63 is substantively identical, and no divergence reflects a real quality
change). Guidance for migrators: treat vs-recorded parity as a smoke test for
gross regressions, not a bit-identity gate, and re-baseline on the current
engine after cutover.

## Workspace sync (2026-09) — engine + retrofit

Added the two-repository sync mechanism (`docs/sync.md`): the workspace becomes
the user's own private git repo; the DB is a rebuildable artefact and its CSV
export is the committed record of record. Engine work: `paths.py` config +
`.jobissimo` pointer resolution; `db.py` lossless `export/import/verify-csv` +
`meta` write-stamps; `scripts/sync.py` + `/sync`; config examples moved to
`templates/config/`.

Deltas from the sync brief's §0 snapshot, verified before starting:

- **Job count is 333, not 317.** The brief's number was stale; the pipeline
  grew between writing and execution. Round-trip parity was checked against the
  live 333/1800/3 (jobs/events/id_reservations).
- **Local `main` was 1 commit ahead of `origin/main`** (the `fix(ats)` commit
  was unpushed). That commit — and *only* that commit — carried the user's
  home-city token (a denylisted string) in `docs/decisions.md`. It was
  therefore **never public** (origin's HEAD `f7b5f77` is clean). It was
  rewritten (`filter-branch`, one idempotent text substitution) to `bd1ca94`
  before any push, so no public history was rewritten; the working-tree copy
  was de-personalised in the same pass. The scrub gate / CI history scan is now
  clean.
- **The `state/backup/*.csv` were stale** relative to the DB and predate the new
  lossless format (no `id_reservations`/`meta`, unordered). Refreshed by the new
  `export-csv` during the Part 2 round-trip.

## Deferred improvements (behaviour left as-is on purpose)

- `coverage.py`'s profile strength score is deliberately blunt (movement, not
  a number to game). A weighted, evidence-tier-aware score could be better but
  would change the reported number; deferred.
- The mini-YAML parser handles the subset the repo's own files use; block
  scalars and anchors are unsupported. Deferred unless a pack needs them.
- `intake.py` OCR is best-effort via external tools; no bundled OCR. Deferred.
