#!/usr/bin/env python3
"""intake.py — convert career documents to text for /setup ingestion.

Takes files, folders, or pasted text; writes extracted plain text into
$JOBISSIMO_HOME/_intake/ and records every source in _intake/manifest.yaml
with a stable `src_id`, original filename, format, detected language, word
count and SHA-256. Nothing is interpreted here — this stage only gives every
fact an address (`{src_id}#{locator}`) that extraction can point at later.

Stdlib-only conversion:
- .md .txt .csv       read directly
- .html .htm          tags stripped
- .docx               zipfile + XML text nodes
- .pdf .odt .rtf .doc pandoc / pdftotext / textutil when available; otherwise
                      the file is recorded as `needs_text: true` and /setup
                      asks the user for a text version rather than guessing.

Usage:
  python3 scripts/intake.py <file-or-folder> [...]
  python3 scripts/intake.py --text "pasted content" --name "old_cover_letter"
  python3 scripts/intake.py --list
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

ACCEPTED = {".md", ".txt", ".csv", ".html", ".htm", ".docx", ".pdf",
            ".odt", ".rtf", ".doc", ".json", ".yaml", ".yml"}

# Crude stopword-vote language detector — enough to tag a CV's language for
# the manifest; /setup confirms the language matrix with the user anyway.
LANG_MARKERS = {
    "en": {"the", "and", "with", "for", "of", "to", "in", "experience", "management"},
    "it": {"il", "la", "di", "che", "per", "con", "una", "del", "della", "esperienza"},
    "de": {"der", "die", "und", "mit", "für", "von", "das", "ein", "erfahrung"},
    "fr": {"le", "la", "les", "des", "une", "avec", "pour", "dans", "expérience"},
    "es": {"el", "la", "los", "las", "una", "con", "para", "de", "experiencia"},
    "pt": {"o", "a", "os", "as", "uma", "com", "para", "de", "experiência"},
    "nl": {"de", "het", "een", "en", "met", "voor", "van", "ervaring"},
}


def detect_language(text: str) -> str:
    words = set(re.findall(r"[a-zà-ÿ]+", text.lower())[:2000])
    best, best_hits = "und", 0
    for code, markers in LANG_MARKERS.items():
        hits = len(words & markers)
        if hits > best_hits:
            best, best_hits = code, hits
    return best


def docx_text(path: Path) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    out = []
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as fh:
            tree = ElementTree.parse(fh)
    for para in tree.iter(f"{ns}p"):
        runs = [node.text or "" for node in para.iter(f"{ns}t")]
        if runs:
            out.append("".join(runs))
    return "\n".join(out)


def html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = raw.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
             .replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", raw).strip()


def external_convert(path: Path) -> str | None:
    """Try pandoc, pdftotext, textutil — first one that works wins."""
    candidates = []
    if path.suffix.lower() == ".pdf":
        if shutil.which("pdftotext"):
            candidates.append(["pdftotext", "-layout", str(path), "-"])
    if shutil.which("pandoc") and path.suffix.lower() in (".odt", ".rtf", ".docx", ".html", ".htm"):
        candidates.append(["pandoc", "-t", "plain", str(path)])
    if sys.platform == "darwin" and shutil.which("textutil") \
            and path.suffix.lower() in (".doc", ".rtf", ".odt", ".docx"):
        candidates.append(["textutil", "-convert", "txt", "-stdout", str(path)])
    for cmd in candidates:
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=120)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def extract_text(path: Path) -> str | None:
    suffix = path.suffix.lower()
    try:
        if suffix in (".md", ".txt", ".csv", ".json", ".yaml", ".yml"):
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix in (".html", ".htm"):
            return html_text(path.read_text(encoding="utf-8", errors="replace"))
        if suffix == ".docx":
            try:
                return docx_text(path)
            except Exception:
                return external_convert(path)
        return external_convert(path)
    except OSError:
        return None


def manifest_path() -> Path:
    return paths.intake() / "manifest.yaml"


def read_manifest() -> list:
    entries, current = [], None
    if not manifest_path().exists():
        return entries
    for line in manifest_path().read_text(encoding="utf-8").splitlines():
        if line.startswith("- src_id:"):
            current = {"src_id": line.split(":", 1)[1].strip()}
            entries.append(current)
        elif current is not None and ":" in line and line.startswith("  "):
            k, v = line.strip().split(":", 1)
            current[k.strip()] = v.strip()
    return entries


def write_manifest(entries: list) -> None:
    lines = ["# Intake manifest — one entry per ingested source document.",
             "# src_id is the stable address every extracted fact points back to.", ""]
    for e in entries:
        lines.append(f"- src_id: {e['src_id']}")
        for key in ("original", "format", "language", "words", "sha256", "text_file", "needs_text"):
            if key in e:
                lines.append(f"  {key}: {e[key]}")
    manifest_path().write_text("\n".join(lines) + "\n", encoding="utf-8")


def next_src_id(entries: list) -> str:
    max_n = 0
    for e in entries:
        m = re.fullmatch(r"SRC-(\d+)", e["src_id"])
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"SRC-{max_n + 1:03d}"


def ingest_file(path: Path, entries: list) -> dict:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    for e in entries:
        if e.get("sha256") == sha:
            print(f"  skip (already ingested as {e['src_id']}): {path.name}")
            return e
    src_id = next_src_id(entries)
    text = extract_text(path)
    entry = {"src_id": src_id, "original": path.name,
             "format": path.suffix.lower().lstrip("."), "sha256": sha}
    paths.intake().mkdir(parents=True, exist_ok=True)
    if text and text.strip():
        out = paths.intake() / f"{src_id}.txt"
        out.write_text(text, encoding="utf-8")
        entry["text_file"] = out.name
        entry["language"] = detect_language(text)
        entry["words"] = str(len(text.split()))
        print(f"  {src_id}: {path.name} -> {out.name} "
              f"({entry['language']}, {entry['words']} words)")
    else:
        entry["needs_text"] = "true"
        print(f"  {src_id}: {path.name} — could not extract text "
              "(no converter available); ask the user for a text version.")
    entries.append(entry)
    return entry


def ingest_text(text: str, name: str, entries: list) -> dict:
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for e in entries:
        if e.get("sha256") == sha:
            print(f"  skip (already ingested as {e['src_id']})")
            return e
    src_id = next_src_id(entries)
    paths.intake().mkdir(parents=True, exist_ok=True)
    out = paths.intake() / f"{src_id}.txt"
    out.write_text(text, encoding="utf-8")
    entry = {"src_id": src_id, "original": name or "pasted_text", "format": "pasted",
             "language": detect_language(text), "words": str(len(text.split())),
             "sha256": sha, "text_file": out.name}
    entries.append(entry)
    print(f"  {src_id}: {entry['original']} ({entry['language']}, {entry['words']} words)")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="*", help="Files or folders to ingest.")
    parser.add_argument("--text", help="Ingest pasted text instead of a file.")
    parser.add_argument("--name", help="Label for --text content.")
    parser.add_argument("--list", action="store_true", help="Print the manifest and exit.")
    args = parser.parse_args()

    entries = read_manifest()
    if args.list:
        if not entries:
            print("Manifest is empty — nothing ingested yet.")
        for e in entries:
            flag = " NEEDS TEXT" if e.get("needs_text") else ""
            print(f"{e['src_id']}  {e.get('original','?'):<40} "
                  f"{e.get('language','-'):<4} {e.get('words','-'):>7} words{flag}")
        return 0

    if not args.sources and not args.text:
        parser.error("nothing to ingest — pass files/folders, --text, or --list")

    if args.text:
        ingest_text(args.text, args.name or "pasted_text", entries)
    for src in args.sources:
        p = Path(src).expanduser()
        if p.is_dir():
            files = sorted(f for f in p.rglob("*")
                           if f.is_file() and f.suffix.lower() in ACCEPTED
                           and not f.name.startswith("."))
            print(f"folder {p}: {len(files)} candidate file(s)")
            for f in files:
                ingest_file(f, entries)
        elif p.is_file():
            ingest_file(p, entries)
        else:
            print(f"  WARN: not found: {p}", file=sys.stderr)

    write_manifest(entries)
    pending = sum(1 for e in entries if e.get("needs_text"))
    print(f"\nManifest: {manifest_path()} ({len(entries)} source(s)"
          + (f", {pending} need a text version" if pending else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
