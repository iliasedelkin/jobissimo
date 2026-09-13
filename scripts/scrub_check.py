#!/usr/bin/env python3
"""scrub_check.py — the PII gate. No personal data reaches the public repo.

Scans text for personal-data leaks before they are committed:

1. **Generic detectors** — any email address outside the allowlisted example
   domains, phone-shaped numbers (international `+…` runs, except the
   reserved fictional `555` ranges), `linkedin.com/in/` profile handles not
   marked as fixtures, and pipeline job-ids (`<source-slug>NNN`), which only
   exist in a real workspace.
2. **Hashed denylist** — SHA-256 hashes of known-personal tokens from the
   upstream private install (names, accounts, phone/DOB digit runs). The repo
   carries only the hashes, never the strings; a scanned token or digit-run
   that hashes to an entry is a finding. Extend the list for your own install
   with `--extra-hashes <file>` (one hex digest per line).

Modes:
  scrub_check.py <path> [...]      scan files/folders
  scrub_check.py --staged          scan git-staged content (pre-commit hook)
  scrub_check.py --all             scan the working tree AND all git history
  scrub_check.py --install-hook    install as .git/hooks/pre-commit

Exit 0 = clean, 1 = findings, 2 = usage error. This is a tripwire, not a
guarantee — review diffs before publishing regardless.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# SHA-256 digests of lowercased known-personal tokens (names, account handles,
# employer/institution tokens, phone and date-of-birth digit runs) from the
# upstream private install. Deliberately hashes, not strings.
DENY_HASHES = {
    "4d446210767b85bf3b33133b643d4db5bcc15ce19b679c8f12634995eb3285bc",
    "dd332fe8ecd24554ec3a96df2d748e65eb3788a5fd143cf447407e4aab47214a",
    "f9ac242a4ad4627f5d4ed1143f550e64cd6bb13cf6da319495585d0f9e6aeab2",
    "0e6755a4da576f9fabd8232034b40cb34bdd5972de9ff6817a0320688dfccf05",
    "4fc79861837239a41d3f019522ee07d01f01f579e987d0a1d3331ed63561f689",
    "4caf42c30479e635f5c2ba025e6c81b42f196c421871d3dbe993349a52a944f5",
    "f4569acfd0a45e13c056d9892e1cb75f5926f36446dee41b18fe31e52d5b7daf",
    "008be6875298f5a65763851b274e87055f3101a9c0477e583813c187cba187e6",
    "4852283729fd89b704d1f18593d297bc01b798a8e0a7b8a4606ba3d7ff8271b1",
    "05a17c2ffe176b1f9a91bfcee9b8123e1b2257400ea066194a15404932b0b697",
}

EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net",
                         "users.noreply.github.com", "anthropic.com"}
PHONE_RE = re.compile(r"\+\d[\d\s().-]{7,}\d")
LINKEDIN_PROFILE_RE = re.compile(r"linkedin\.com/in/([A-Za-z0-9._-]+)")
ALLOWED_HANDLE_MARKERS = ("example", "sam-rivera", "samrivera")
# Pipeline job-ids only exist in a real workspace; none belong in the repo.
JOB_ID_RE = re.compile(
    r"\b(?:linkedin|indeed|glassdoor|topremote|remotive|himalayas|wwr|"
    r"productheroes|jobgether|wellfound|euremote|builtin|startupjobs|cdpvc|"
    r"eudatajobs|englishjobs|remoteineu|arcdev|remoteok|4dayweek)\d{3}\b")

TOKEN_RE = re.compile(r"[a-z0-9]+")
SKIP_DIRS = {".git", "__pycache__", "profile", "node_modules"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc",
                 ".zip", ".db"}
# Machine-local, gitignored files that legitimately hold a personal path and
# are never committed (the workspace pointer holds an absolute $JOBISSIMO_HOME).
SKIP_NAMES = {".jobissimo"}
# scrub_check itself holds the hash list; scanning it is meaningless.
SELF = Path(__file__).name


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def scan_text(text: str, label: str, deny: set) -> list:
    findings = []
    for n, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        for m in EMAIL_RE.finditer(line):
            if m.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
                findings.append((label, n, f"email address `{m.group(0)}`"))
        for m in PHONE_RE.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if "555" in digits[:6] or len(digits) < 9:
                continue  # reserved fictional ranges / too short to be a number
            findings.append((label, n, f"phone-shaped number `{m.group(0).strip()}`"))
        for m in LINKEDIN_PROFILE_RE.finditer(low):
            if not any(mark in m.group(1) for mark in ALLOWED_HANDLE_MARKERS):
                findings.append((label, n, f"linkedin profile handle `{m.group(1)}`"))
        for m in JOB_ID_RE.finditer(low):
            findings.append((label, n, f"pipeline job-id `{m.group(0)}`"))
        # hashed denylist: single tokens, adjacent bigrams, and digit runs
        tokens = TOKEN_RE.findall(low)
        for i, t in enumerate(tokens):
            if _hash(t) in deny:
                findings.append((label, n, "denylisted token (hash match)"))
            if i + 1 < len(tokens) and _hash(f"{t} {tokens[i + 1]}") in deny:
                findings.append((label, n, "denylisted token pair (hash match)"))
        for run in re.findall(r"\d{8,}", re.sub(r"[\s().-]", "", line)):
            for start in range(0, len(run) - 7):
                for length in (8, 10, 11):
                    piece = run[start:start + length]
                    if len(piece) >= 8 and _hash(piece) in deny:
                        findings.append((label, n, "denylisted digit run (hash match)"))
    return findings


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIXES or p.name == SELF or p.name in SKIP_NAMES:
            continue
        yield p


def scan_paths(targets: list, deny: set) -> list:
    findings = []
    for target in targets:
        for f in iter_files(Path(target)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            findings += scan_text(text, str(f), deny)
    return findings


def scan_staged(deny: set) -> list:
    res = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"],
                         capture_output=True, cwd=REPO_ROOT)
    findings = []
    for name in res.stdout.decode().split("\0"):
        if not name or Path(name).name == SELF:
            continue
        if Path(name).suffix.lower() in SKIP_SUFFIXES:
            continue
        show = subprocess.run(["git", "show", f":{name}"],
                              capture_output=True, cwd=REPO_ROOT)
        if show.returncode != 0:
            continue
        findings += scan_text(show.stdout.decode(errors="replace"), f"staged:{name}", deny)
    return findings


def scan_history(deny: set) -> list:
    res = subprocess.run(["git", "log", "--all", "-p", "--format=commit %H%n%B"],
                         capture_output=True, cwd=REPO_ROOT)
    text = res.stdout.decode(errors="replace")
    # drop diff lines that belong to scrub_check.py itself (the hash list)
    cleaned, skip = [], False
    for line in text.splitlines():
        if line.startswith("diff --git"):
            skip = SELF in line
        if not skip:
            cleaned.append(line)
    return scan_text("\n".join(cleaned), "git-history", deny)


HOOK = """#!/bin/sh
# Jobissimo PII gate — refuses commits containing personal data.
exec python3 "$(git rev-parse --show-toplevel)/scripts/scrub_check.py" --staged
"""


def install_hook() -> int:
    hook_path = REPO_ROOT / ".git" / "hooks" / "pre-commit"
    if not hook_path.parent.exists():
        print("ERROR: .git/hooks not found — is this a git checkout?", file=sys.stderr)
        return 2
    hook_path.write_text(HOOK, encoding="utf-8")
    hook_path.chmod(0o755)
    print(f"Installed pre-commit hook: {hook_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", help="Files or folders to scan.")
    parser.add_argument("--staged", action="store_true", help="Scan git-staged content.")
    parser.add_argument("--all", action="store_true",
                        help="Scan the working tree and the full git history.")
    parser.add_argument("--install-hook", action="store_true",
                        help="Install as .git/hooks/pre-commit.")
    parser.add_argument("--extra-hashes", help="File of extra SHA-256 digests (one per line).")
    args = parser.parse_args()

    deny = set(DENY_HASHES)
    if args.extra_hashes:
        for line in Path(args.extra_hashes).read_text().splitlines():
            line = line.strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", line):
                deny.add(line)

    if args.install_hook:
        return install_hook()

    findings = []
    if args.staged:
        findings += scan_staged(deny)
    elif args.all:
        findings += scan_paths([REPO_ROOT], deny)
        findings += scan_history(deny)
    elif args.targets:
        findings += scan_paths(args.targets, deny)
    else:
        parser.error("nothing to scan — pass paths, --staged, or --all")

    if findings:
        print(f"SCRUB: {len(findings)} finding(s) — personal data must not enter the repo:\n")
        for label, n, what in findings[:100]:
            print(f"  {label}:{n}  {what}")
        if len(findings) > 100:
            print(f"  … and {len(findings) - 100} more")
        return 1
    print("SCRUB: clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
