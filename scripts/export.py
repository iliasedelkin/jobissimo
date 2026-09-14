#!/usr/bin/env python3
"""export.py — strip trace comments and export final DOCX/PDF via pandoc.

- cv_draft.md          -> cv_final.md          -> cv.docx (+ cv.pdf)
- cover_letter_draft.md-> cover_letter_final.md-> cover_letter.docx (+ .pdf)

DOCX uses templates/ats_reference.docx. PDF uses tectonic when available;
a missing PDF engine is a warning, not a failure (DOCX is the primary
submission format). A missing pandoc IS a failure: the audited markdown
finals are still written, but the command exits 1 so /prepare does not
mark the job ready on a half-finished export.

Runs the audit first and refuses to export on FAIL unless --skip-audit
(bypass must be an explicit user decision recorded in audit_log.md).

State lives in the pipeline DB and is written only via db.py — run
`python3 scripts/db.py set-status --job-id <id> --status ready` after export.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
from audit import validate  # noqa: E402

REFERENCE_DOC = paths.reference_docx()


def strip_html_comments(text: str) -> str:
    stripped = re.sub(r"\s*<!--.*?-->", "", text, flags=re.DOTALL)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip() + "\n"


PANDOC_INSTALL = ("  macOS:   brew install pandoc\n"
                  "  Debian:  sudo apt install pandoc\n"
                  "  Windows: winget install JohnMacFarlane.Pandoc")


def run_pandoc_docx(md: Path, out: Path) -> bool:
    """Export one markdown final to DOCX. Never raises: a missing or broken
    pandoc is reported as a sentence the user can act on, not a traceback."""
    cmd = ["pandoc", str(md), "-o", str(out)]
    if REFERENCE_DOC.exists():
        cmd += ["--reference-doc", str(REFERENCE_DOC)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except FileNotFoundError:
        print(f"ERROR: pandoc not found — cannot export {out.name}.\n{PANDOC_INSTALL}",
              file=sys.stderr)
        return False
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip()
        print(f"ERROR: pandoc failed on {md.name}: {detail or exc}", file=sys.stderr)
        return False


def run_pandoc_pdf(md: Path, out: Path, margin: str, font_size: str,
                   docx: Path | None = None) -> bool:
    """Produce a PDF, trying engines in order:
    1. pandoc + tectonic / xelatex / pdflatex (compact A4 styling)
    2. LibreOffice headless conversion of the already-exported DOCX
       (PDF guaranteed to match the DOCX styling)
    """
    for engine in ("tectonic", "xelatex", "pdflatex"):
        cmd = ["pandoc", "-f", "markdown+hard_line_breaks", str(md), "-o", str(out),
               f"--pdf-engine={engine}", "-V", "papersize=a4",
               "-V", f"geometry:margin={margin}", "-V", f"fontsize={font_size}",
               "-V", "pagestyle=empty"]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    if docx and docx.exists():
        for soffice in ("soffice", "libreoffice"):
            try:
                subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                                "--outdir", str(out.parent), str(docx)],
                               check=True, capture_output=True, timeout=120)
                produced = out.parent / (docx.stem + ".pdf")
                if produced.exists():
                    if produced != out:
                        produced.replace(out)
                    return True
            except (FileNotFoundError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired):
                continue
    print(f"WARN: PDF export failed for {md.name} — no working PDF engine "
          "(tried tectonic/xelatex/pdflatex/libreoffice). DOCX is the primary "
          "format; install tectonic for styled PDFs.", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", required=True, help="Application folder.")
    parser.add_argument("--skip-audit", action="store_true",
                        help="Export even if the audit fails (requires an explicit user bypass).")
    parser.add_argument("--skip-pdf", action="store_true", help="Skip PDF export.")
    args = parser.parse_args()

    folder = paths.resolve_folder(args.folder)
    if not folder.exists():
        print(f"ERROR: folder does not exist: {folder}", file=sys.stderr)
        return 1

    if not args.skip_audit:
        overall, issues, _ = validate(folder)
        if overall != "PASS":
            detail = "\n".join(f"- {i}" for i in issues[:10])
            print(f"ERROR: audit FAIL — adjudicate fix/bypass/halt before export.\n{detail}",
                  file=sys.stderr)
            return 1

    have_pandoc = shutil.which("pandoc") is not None
    if not have_pandoc:
        print("ERROR: pandoc not found — the audited markdown finals will still be "
              "written, but DOCX/PDF export cannot run.\n" + PANDOC_INSTALL +
              "\nRe-run this command once installed; nothing else needs redoing.",
              file=sys.stderr)

    produced, docx_failed = [], False
    for draft_name, final_name, docx_name, pdf_name, margin, size in (
        ("cv_draft.md", "cv_final.md", "cv.docx", "cv.pdf", "0.55in", "10pt"),
        ("cover_letter_draft.md", "cover_letter_final.md", "cover_letter.docx",
         "cover_letter.pdf", "0.65in", "11pt"),
    ):
        draft = folder / draft_name
        if not draft.exists():
            continue
        final = folder / final_name
        final.write_text(strip_html_comments(draft.read_text(encoding="utf-8")), encoding="utf-8")
        produced.append(final)
        if not have_pandoc:
            continue
        docx = folder / docx_name
        if run_pandoc_docx(final, docx):
            produced.append(docx)
        else:
            docx_failed = True
            continue
        if not args.skip_pdf:
            pdf = folder / pdf_name
            if run_pandoc_pdf(final, pdf, margin, size, docx=docx):
                produced.append(pdf)

    if not produced:
        print("ERROR: nothing to export (no cv_draft.md / cover_letter_draft.md).", file=sys.stderr)
        return 1
    print(f"Exported: {folder.name}")
    for p in produced:
        print(f"  {p.name}")
    if not have_pandoc or docx_failed:
        # The finals are audited and usable, but a submission-ready DOCX is the
        # point of this command — do not let /prepare mark the job ready.
        print("\nIncomplete: markdown finals only, no DOCX. Fix pandoc and re-run.",
              file=sys.stderr)
        return 1
    print("Next: python3 scripts/db.py set-status --job-id <id> --status ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
