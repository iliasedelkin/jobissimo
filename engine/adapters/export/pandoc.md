# Export adapter: pandoc

`scripts/export.py` renders the audited finals to submission formats:

- `cv_final.md` → `cv.docx` via pandoc with
  `templates/ats_reference.docx` as the reference doc (plain single-column,
  Calibri/Arial 11pt — the ATS-safe baseline).
- PDF (secondary format) via the first available engine: tectonic → xelatex →
  pdflatex → LibreOffice headless conversion of the DOCX. A missing PDF
  engine is a warning, not a failure; DOCX is the primary submission format.

Degradation: no pandoc at all → the markdown finals (`cv_final.md`,
`cover_letter_final.md`) are still produced with traces stripped, and the
user converts or pastes them manually. `/setup` S0 records the detected
state in `config/capabilities.yaml`; `/doctor` re-checks it.

Export always runs the truth audit first and refuses on FAIL unless the user
explicitly chose bypass (recorded in `audit_log.md`).
