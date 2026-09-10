# Job Evaluation Rubric — generic pack

A minimal rubric skeleton. `/setup` fills the specifics from the user's
targets; the structure mirrors the product pack's rubric so the scoring
fields stay comparable.

## Dimensions

1. **Role fit** — match with the ranked targets in `config/targets.yaml`.
2. **Seniority match** — score by years required in the JD vs
   `targets.yaml → seniority.baseline_years`, never by title.
3. **Company fit** — preferred/avoided profiles from
   `targets.yaml → company_preferences`.
4. **Role content signals** — must/weak/reject signals from each target's
   `must_signals` / `reject_signals`.
5. **Location & work-mode fit** — judged against `targets.yaml → geography`;
   region strings on portals are marketing copy — verify eligible countries
   on the employer source before `location_fit: match`.
6. **Velocity SLA** — prepare-and-apply within
   `pipeline.yaml → thresholds.velocity_sla_days` of discovery for high-fit
   jobs; re-verify liveness when delayed.

Decision logic (same as every pack): fit ≥ 4 + no red flags + location ≠
reject → `yes`; fit ≥ 3.5 + minor flags or stretch seniority → `maybe`;
fit < 3.5 or any reject signal → `no` with a one-sentence reason.
