# Fixtures — entirely fictional

Everything in this directory is **invented for testing**: Sam Rivera does not
exist, the companies (Fernwood Labs, Harborline Logistics, Brightpath
Learning, Nimbus Metrics, Velatech, Corvid Robotics) do not exist, and the
three job descriptions were written for this repo — none is copied from a
real posting. Contact details use reserved fictional ranges
(`example.com`, `+1 555 …`).

Layout:

- `sam-rivera/` — the fixture candidate's **source documents**, used to
  rehearse `/setup` end-to-end: two CV versions in different formats (the
  differences between them are deliberate signal, including one planted
  contradiction), a LinkedIn-export CSV triplet, and an old cover letter.
- `sam-rivera/expected/` — the extraction output a correct `/setup` S2
  produces from those documents (knowledge base + applicant profile), plus
  two fully prepared application folders (English and Italian) used by the
  offline test suite to verify the audit → ATS chain and the multilingual
  invariants.
- `sam-rivera/config/` — a complete fixture config (used via
  `$JOBISSIMO_CONFIG` in tests).
- `jds/` — three synthetic JDs: `sample001` (English product role, matches
  the fixture profile), `sample002` (Italian role, exercises the locale
  path), `sample003` (deliberately mismatched role that must score below
  the bar).

Planted imperfections (do not "fix" them — tests depend on them):
- `cv_2024.md` says first-response time went to **90 minutes**;
  `cv_2025.docx` says **45 minutes** — a contradiction /setup S3 must
  surface.
- Two Fernwood bullets are deliberately unquantified (metric-rescue queue
  fodder).
- **Figma** is claimed in the 2025 CV's skills list with no evidencing
  bullet — it must land in `unevidenced.md`, never in a generated CV.
