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

3. **Workspace fingerprint** — the real values of this machine's workspace:
   every date in the pipeline (jobs + events), the companies the user applied
   to or heard from, aggregate counts (>= 10) from the jobs table, and
   money-sized amounts (>= 1000) from stage logs, notes,
   `applicant_profile.yaml` and `config/targets.yaml` (a posting's published
   salary band is the employer's data and is not collected).
   Anonymising a fact does not change its value, so a true number is caught
   even with every name removed. Built through `db.py export-csv` (read-only
   for the DB); absent workspace → no fingerprint. `--staged` checks company
   names and amounts (dates and counts are too common in engine docs);
   `--outbound` checks all four.
4. **Telemetry signatures** (`--outbound` only) — the *shape* of real
   evidence, whatever the values: "one install"-style phrasing, `N of M`,
   percentages, `n = N`, numeric funnels (`64 applied → 28 …`), and table
   rows of bare counts. An illustration that needs that shape goes between
   `<!-- synthetic -->` and `<!-- /synthetic -->`; the fingerprint still
   applies inside, so the marker permits a shape, never a real value.

Outbound text — issue/PR bodies and comments, anything leaving the machine
other than a commit — carries no workspace-derived fact at all, anonymised
or not (AGENTS.md invariant 11). Evidence is engine file:line plus a
reproduction on the synthetic fixture with obviously fictional values.

Modes:
  scrub_check.py <path> [...]      scan files/folders
  scrub_check.py --staged          scan git-staged content (pre-commit hook)
  scrub_check.py --all             scan the working tree AND all git history
  scrub_check.py --outbound F [...] strict scan of an issue/PR body or comment
  scrub_check.py --gh-hook         Claude Code PreToolUse hook: blocks a `gh`
                                   issue/PR create/edit/comment whose title or
                                   body fails --outbound
  scrub_check.py --install-hook    install as .git/hooks/pre-commit

Exit 0 = clean, 1 = findings, 2 = usage error. This is a tripwire, not a
guarantee — review diffs before publishing regardless.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
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
# Machine-local files skipped only while git confirms they are ignored: Claude
# Code writes `/add-dir` grants (absolute workspace paths) into
# .claude/settings.local.json. A copy that is not ignored is scanned as usual.
SKIP_IF_IGNORED = {"settings.local.json"}
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


# --- workspace fingerprint ----------------------------------------------------

DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# 33058 · 33,058 · 33.058 · 33 058 · 55k — normalised to an integer
AMOUNT_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[,. ]\d{3})+|\d{4,})(?![\w]|[.,]\d)|\b(\d{2,3})\s?[kK]\b")
INT_RE = re.compile(r"(?<![\w.,:#/-])(\d{2,})(?![\w]|[.,:]\d|%)")
# masked before value checks: file:line refs, URLs, issue refs, hex digests
MASK_RE = re.compile(r"https?://\S+|[\w./-]+\.\w+:\d+(?:-\d+)?|#\d+\b|\b[0-9a-f]{12,}\b")
COMPANY_STOP = {"undisclosed", "confidential", "stealth", "unknown", "various", "n/a",
                "remote", "unlisted"}
COUNT_COLUMNS = ("status", "source", "outcome", "role_cluster", "priority",
                 "apply_recommendation", "applied_via", "remote_flag", "jd_language")


def _amounts_in(text: str) -> set:
    out = set()
    for m in AMOUNT_RE.finditer(text):
        if m.group(1):
            n = int(re.sub(r"[,. ]", "", m.group(1)))
        else:
            n = int(m.group(2)) * 1000
        if n >= 1000 and not 1900 <= n <= 2100:   # a bare year is not an amount
            out.add(n)
    return out


def workspace_fingerprint() -> dict:
    """Real values from this machine's workspace. Empty when there is none
    (CI, a fresh clone) — the gate then degrades to detectors + signatures."""
    fp = {"dates": set(), "companies": set(), "counts": set(), "amounts": set()}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import paths  # noqa: E402
        home = paths.home()
    except Exception:
        return fp
    for name in ("applicant_profile.yaml", "config/targets.yaml"):
        p = home / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            fp["amounts"] |= _amounts_in(text)
            if name == "applicant_profile.yaml":
                fp["dates"] |= {m.group(0) for m in DATE_RE.finditer(text)}
    if not (home / "state" / "pipeline.db").is_file():
        return fp
    with tempfile.TemporaryDirectory() as tmp:
        res = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "db.py"),
                              "export-csv", "--out", tmp], capture_output=True)
        if res.returncode != 0:
            return fp
        jobs = list(csv.DictReader(open(Path(tmp) / "jobs.csv", encoding="utf-8")))
        events = list(csv.DictReader(open(Path(tmp) / "events.csv", encoding="utf-8")))
    for row in jobs:
        for v in row.values():
            if v:
                fp["dates"] |= {m.group(0) for m in DATE_RE.finditer(v)}
        # the user's own figures (offers, counters); a posting's published
        # `salary` band is the employer's public data, not the user's
        for field in ("interview_stage", "notes"):
            fp["amounts"] |= _amounts_in(row.get(field) or "")
        # a posting the hunt merely found is public; one the user applied to
        # or heard back from is part of their history
        if not (row.get("date_applied") or row.get("response_date")):
            continue
        company = re.split(r"\s[(—–-]\s?|\s\(", row.get("company") or "")[0].strip().lower()
        if len(company) >= 4 and company not in COMPANY_STOP:
            fp["companies"].add(company)
    for ev in events:
        fp["dates"] |= {m.group(0) for m in DATE_RE.finditer(ev.get("ts") or "")}
    counts = Counter()
    counts["jobs"] = len(jobs)
    counts["events"] = len(events)
    counts["applied"] = sum(1 for r in jobs if r.get("date_applied"))
    counts["responded"] = sum(1 for r in jobs if r.get("response_date"))
    for col in COUNT_COLUMNS:
        for v, n in Counter(r.get(col) or "" for r in jobs).items():
            counts[f"{col}={v}"] = n
    for src in {r.get("source") for r in jobs}:
        mine = [r for r in jobs if r.get("source") == src]
        counts[f"{src}:applied"] = sum(1 for r in mine if r.get("date_applied"))
        counts[f"{src}:responded"] = sum(1 for r in mine if r.get("response_date"))
    fp["counts"] = {n for n in counts.values() if n >= 10}
    return fp


def scan_fingerprint(text: str, label: str, fp: dict, kinds: tuple) -> list:
    findings = []
    for n, line in enumerate(text.splitlines(), start=1):
        masked = MASK_RE.sub(" ", line)
        low = masked.lower()
        if "dates" in kinds:
            for m in DATE_RE.finditer(masked):
                if m.group(0) in fp["dates"]:
                    findings.append((label, n, f"real workspace date `{m.group(0)}`"))
        if "companies" in kinds:
            for c in fp["companies"]:
                if re.search(rf"(?<!\w){re.escape(c)}(?!\w)", low):
                    findings.append((label, n, "real company name from the pipeline"))
        if "amounts" in kinds:
            for a in _amounts_in(DATE_RE.sub(" ", masked)) & fp["amounts"]:
                findings.append((label, n, f"real amount `{a}` (profile/config/stage log)"))
        if "counts" in kinds:
            for m in INT_RE.finditer(DATE_RE.sub(" ", masked)):
                if int(m.group(1)) in fp["counts"]:
                    findings.append((label, n, f"real pipeline count `{m.group(1)}`"))
    return findings


# --- telemetry signatures (outbound only) -------------------------------------

SIGNATURES = [
    (re.compile(r"\b(?:(?:one|this|an|the|my|our|a real|a private|a live)\s+"
                r"(?:install|installation|workspace)|(?:my|our|a real|a private|a live)\s+"
                r"pipeline)(?:'s)?\b", re.I),
     "real-install phrasing — describe the mechanism, not an install's data"),
    (re.compile(r"\b\d+\s*(?:of|out of|/)\s*\d+\b"), "`N of M` ratio"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?%"), "percentage"),
    (re.compile(r"\bn\s*=\s*\d+", re.I), "sample size `n = N`"),
    (re.compile(r"\d+\s+[\w ]+?\s*(?:→|->)\s*\d+"), "numeric funnel"),
    (re.compile(r"^\s*\|(?:[^|\n]*\|)*?(?:\s*\d+\s*\|){3,}"), "table row of bare counts"),
]


def scan_signatures(text: str, label: str) -> list:
    findings, synthetic = [], False
    for n, line in enumerate(text.splitlines(), start=1):
        if "<!-- synthetic -->" in line:
            synthetic = True
        if "<!-- /synthetic -->" in line:
            synthetic = False
            continue
        if synthetic:
            continue
        masked = MASK_RE.sub(" ", line)
        for rx, what in SIGNATURES:
            if rx.search(masked):
                findings.append((label, n, f"telemetry signature: {what}"))
    return findings


def scan_outbound(text: str, label: str, deny: set, fp: dict) -> list:
    return (scan_text(text, label, deny)
            + scan_fingerprint(text, label, fp, ("dates", "companies", "counts", "amounts"))
            + scan_signatures(text, label))


# `gh` as an invoked command (line start, after ; & | or inside $( ), not a
# mention of it in a grep pattern or a heredoc
_GH = r"(?:^|[;&|(\n]\s*|\$\(\s*)gh\s+"
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2(?=\s|$)", re.S)
GH_WRITE_RE = re.compile(_GH +r"(?:(?:issue|pr)\s+(?:create|edit|comment)\b|api\b)")


def gh_hook(deny: set) -> int:
    """PreToolUse hook. Exit 2 blocks the tool call; stderr reaches the agent."""
    try:
        cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except Exception:
        return 0
    # a heredoc body is data written somewhere, not a command being run
    cmd = HEREDOC_RE.sub("\n", cmd)
    if not GH_WRITE_RE.search(cmd):
        return 0
    # resolve $VAR / ${VAR} from assignments earlier in the same command, then
    # the environment; an unresolved path stays unreadable and blocks
    assigned = dict(os.environ)
    for m in re.finditer(r"(?:^|[;&|\s])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)", cmd):
        if not m.group(2).startswith("$("):
            assigned[m.group(1)] = m.group(2).strip("\"'")
    try:
        argv = [re.sub(r"\$\{?([A-Za-z_]\w*)\}?",
                       lambda v: assigned.get(v.group(1), v.group(0)), a)
                for a in shlex.split(cmd)]
    except ValueError:
        argv = cmd.split()
    texts, has_body, i = [], False, 0
    while i < len(argv):
        key, eq, inline = argv[i].partition("=")
        if not key.startswith("-"):
            i += 1
            continue
        val = inline if eq else (argv[i + 1] if i + 1 < len(argv) else "")
        i += 1 if eq else 2
        if val and not Path(val).exists():
            val = val.rstrip(");&|")   # shlex leaves `$( … )` and `;` glued on
        if key in ("--body-file", "-F") and val and not val.startswith(("@", "-")) \
                and "=" not in val:
            p = Path(val)
            if not p.is_file():
                print(f"outbound gate: body file `{val}` not readable — blocked.", file=sys.stderr)
                return 2
            texts.append((str(p), p.read_text(encoding="utf-8", errors="replace")))
            has_body = True
        elif key in ("--body", "-b"):
            texts.append((key, val))
            has_body = True
        elif key in ("--title", "-t") or (key in ("-f", "--field", "--raw-field", "-F")
                                          and val.split("=", 1)[0] in ("body", "title")):
            texts.append((key, val))
            if val.startswith("body=@") and Path(val[6:]).is_file():
                texts[-1] = (val[6:], Path(val[6:]).read_text(encoding="utf-8", errors="replace"))
            has_body = has_body or val.startswith("body=")
    if re.search(_GH + r"api\b", cmd) and not texts:
        return 0   # a read
    if re.search(_GH + r"(?:issue|pr)\s+(?:create|comment)\b", cmd) and not has_body:
        print("outbound gate: pass the body with --body-file so it can be scanned — blocked.",
              file=sys.stderr)
        return 2
    fp = workspace_fingerprint()
    findings = []
    for label, text in texts:
        findings += scan_outbound(text, label, deny, fp)
    if findings:
        print("outbound gate: this gh call would publish workspace-derived data "
              "(AGENTS.md invariant 11). Rewrite with engine file:line evidence and "
              "obviously fictional values, then retry:", file=sys.stderr)
        for label, n, what in findings[:40]:
            print(f"  {label}:{n}  {what}", file=sys.stderr)
        return 2
    return 0


def git_ignored(p: Path) -> bool:
    """True only when git positively reports `p` as ignored; outside a repo,
    or if git is unavailable, the file counts as not ignored and is scanned."""
    try:
        res = subprocess.run(["git", "check-ignore", "-q", "--", p.name],
                             cwd=p.parent, capture_output=True)
    except OSError:
        return False
    return res.returncode == 0


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
        if p.name in SKIP_IF_IGNORED and git_ignored(p):
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


def scan_staged(deny: set, fp: dict | None = None) -> list:
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
        text = show.stdout.decode(errors="replace")
        findings += scan_text(text, f"staged:{name}", deny)
        if fp:
            findings += scan_fingerprint(text, f"staged:{name}", fp, ("companies", "amounts"))
    return findings


def public_companies(fp: dict) -> set:
    """Fingerprint companies already present in the committed tree. A commit
    is only flagged for *introducing* one — a name that is also an ordinary
    word, or a board the engine already ships, must not block every commit."""
    seen = set()
    for c in fp["companies"]:
        r = subprocess.run(["git", "grep", "-q", "-i", "-I", "-w", "-F", c, "HEAD", "--",
                            ".", f":!scripts/{SELF}"], capture_output=True, cwd=REPO_ROOT)
        if r.returncode == 0:
            seen.add(c)
    return seen


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
    parser.add_argument("--outbound", nargs="+", metavar="FILE",
                        help="Strict scan of an issue/PR body or comment: detectors + "
                             "workspace fingerprint + telemetry signatures.")
    parser.add_argument("--gh-hook", action="store_true",
                        help="Claude Code PreToolUse hook for gh issue/PR writes "
                             "(reads the hook JSON on stdin; exit 2 blocks).")
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

    if args.gh_hook:
        return gh_hook(deny)

    findings = []
    if args.outbound:
        fp = workspace_fingerprint()
        for f in args.outbound:
            findings += scan_outbound(Path(f).read_text(encoding="utf-8", errors="replace"),
                                      f, deny, fp)
    elif args.staged:
        fp = workspace_fingerprint()
        fp["companies"] -= public_companies(fp)
        findings += scan_staged(deny, fp)
    elif args.all:
        findings += scan_paths([REPO_ROOT], deny)
        findings += scan_history(deny)
    elif args.targets:
        findings += scan_paths(args.targets, deny)
    else:
        parser.error("nothing to scan — pass paths, --staged, --all, or --outbound")

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
