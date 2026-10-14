#!/usr/bin/env python3
"""assets.py — deterministic fingerprints of a generated application.

A generated CV is identified two ways, both derived from files /prepare
already writes, so every historical folder can be fingerprinted without
re-running anything:

- `variant_id` — sha1[:10] of the sorted, de-duplicated `<!-- src:ID -->`
  trace IDs in `cv_draft.md`: *which knowledge bullets* the CV cites. Two CVs
  that cite the same bullets are the same variant, however they are phrased.
- `text_hash`  — sha1[:12] of the final text (`cv_final.md`, falling back to
  the trace-stripped draft): *exactly what was sent*.

The ATS score and the scorer version are read back from `ats_report.md`, so a
score is never compared across scorer versions without knowing it.

    python3 scripts/assets.py --folder applications/<folder>   # print JSON
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

TRACE_RE = re.compile(r"<!--\s*src:([^>]+)-->")
SCORE_RE = re.compile(r"^## Score:\s*(\d+)/100", re.MULTILINE)
SCORER_RE = re.compile(r"Scorer:\s*`?([0-9][\w.\-]*)`?")
# kind -> (draft, final)
KINDS = {"cv": ("cv_draft.md", "cv_final.md"),
         "cover_letter": ("cover_letter_draft.md", "cover_letter_final.md")}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def trace_ids(text: str) -> list:
    """Sorted unique `src:` IDs. `company:` pseudo-refs are not knowledge."""
    ids = set()
    for m in TRACE_RE.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if part and not part.startswith("company:"):
                ids.add(part)
    return sorted(ids)


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def ats_from_report(folder: Path) -> tuple:
    """(score | None, scorer_version | None) from ats_report.md."""
    text = _read(folder / "ats_report.md")
    m = SCORE_RE.search(text)
    v = SCORER_RE.search(text)
    return (int(m.group(1)) if m else None, v.group(1) if v else None)


def fingerprint(folder: Path, kind: str = "cv") -> dict | None:
    """Fingerprint one asset kind in an application folder, or None when the
    folder has neither a draft nor a final of that kind."""
    draft_name, final_name = KINDS[kind]
    draft, final = _read(folder / draft_name), _read(folder / final_name)
    if not draft and not final:
        return None
    srcs = trace_ids(draft)
    sent = final or _strip_comments(draft)
    score, scorer = ats_from_report(folder) if kind == "cv" else (None, None)
    return {
        "kind": kind,
        "variant_id": hashlib.sha1(",".join(srcs).encode()).hexdigest()[:10] if srcs else None,
        "text_hash": hashlib.sha1(sent.strip().encode()).hexdigest()[:12],
        "src_ids": srcs,
        "ats_score_det": score,
        "scorer_version": scorer,
    }


def fingerprint_all(folder: Path) -> list:
    return [fp for fp in (fingerprint(folder, k) for k in KINDS) if fp]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", required=True, help="Application folder.")
    args = parser.parse_args()
    folder = paths.resolve_folder(args.folder)
    if not folder.is_dir():
        print(f"ERROR: folder does not exist: {folder}", file=sys.stderr)
        return 1
    print(json.dumps(fingerprint_all(folder), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
