#!/usr/bin/env python3
"""sync.py — version and sync the workspace across machines, safely.

Two repositories, never mixed:

  - the ENGINE repo (this checkout): public, on GitHub, holds scripts, packs,
    commands and docs. Engine/pack changes flow here as ordinary commits.
  - the WORKSPACE repo ($JOBISSIMO_HOME): PRIVATE, holds all personal data and
    generated artefacts. It is a separate git repo with its own private remote.

The pipeline database is a runtime artefact: binary, changes every run, and
unmergeable. So the workspace commits the *CSV export* (db.py export-csv) as
the record of record and gitignores the .db; `db.py import-csv` rebuilds it on
the other machine. This module never merges divergent pipeline state — it
shows both sides and lets the user choose.

Verbs:
  sync.py status   what is uncommitted, whether db and CSVs agree, remotes,
                   and which machine wrote last. No side effects.
  sync.py init     one-time: write the workspace .gitignore, git init, first
                   commit, and (optionally) a PRIVATE remote. Idempotent.
  sync.py pull     start of session: pull both repos; rebuild the DB from CSVs
                   if they are newer; STOP on divergent pipeline state.
  sync.py push     end of session: export-csv -> verify-csv -> scrub gate ->
                   commit workspace + engine separately -> push both.

`sync.py` with no verb runs `status`. Every verb is safe to run twice.
Only `/sync` talks to a remote — no pipeline command syncs on its own.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

WORKSPACE = paths.home()
ENGINE = paths.REPO_ROOT
DB_PATH = paths.state_db()
BACKUP = WORKSPACE / "state" / "backup"
DB_CLI = [sys.executable, str(ENGINE / "scripts" / "db.py")]
SCRUB_CLI = [sys.executable, str(ENGINE / "scripts" / "scrub_check.py")]


# ------------------------------------------------------------------ git helpers

def git(repo: Path, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=capture, text=True)


def is_git_repo(repo: Path) -> bool:
    return git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0


def porcelain(repo: Path) -> list[str]:
    out = git(repo, "status", "--porcelain").stdout.strip()
    return [l for l in out.splitlines() if l]


def current_branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"


def has_remote(repo: Path, name: str = "origin") -> bool:
    return name in git(repo, "remote").stdout.split()


def ahead_behind(repo: Path) -> tuple[int, int] | None:
    """(ahead, behind) vs the upstream, or None if no upstream configured."""
    up = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode != 0:
        return None
    counts = git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD").stdout.split()
    if len(counts) != 2:
        return None
    behind, ahead = int(counts[0]), int(counts[1])
    return ahead, behind


# ------------------------------------------------------------------ db helpers

def run_db(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(DB_CLI + list(args), capture_output=True, text=True)


def db_verifies() -> bool:
    return run_db("verify-csv").returncode == 0


def read_meta() -> dict:
    if not DB_PATH.exists():
        return {}
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        conn.close()
        return dict(rows)
    except sqlite3.Error:
        return {}


def csv_newer_than_db() -> bool:
    """True when the committed CSVs are newer than the local DB — the signal to
    rebuild after a pull brought in another machine's work."""
    jobs_csv = BACKUP / "jobs.csv"
    if not jobs_csv.exists():
        return False
    if not DB_PATH.exists():
        return True
    return jobs_csv.stat().st_mtime > DB_PATH.stat().st_mtime


def events_summary_since(iso_ts: str | None) -> str:
    """A commit message derived from what actually happened: aggregate the
    events since the last workspace commit into 'hunt: 8 found, 2 shortlisted;
    prepare: 1 ready'. Read-only."""
    if not DB_PATH.exists():
        return ""
    import sqlite3
    from collections import Counter
    try:
        conn = sqlite3.connect(DB_PATH)
        if iso_ts:
            rows = conn.execute("SELECT command, action FROM events WHERE ts > ?",
                                (iso_ts,)).fetchall()
        else:
            rows = conn.execute("SELECT command, action FROM events").fetchall()
        conn.close()
    except sqlite3.Error:
        return ""
    by_cmd: dict[str, Counter] = {}
    for command, action in rows:
        by_cmd.setdefault(command or "other", Counter())[action or "event"] += 1
    # Surface the actions users care about, in pipeline order.
    KEEP = ["job_added", "job_scored", "job_shortlisted", "job_prepared",
            "status_change", "job_applied", "follow_up_generated"]
    parts = []
    for cmd in ("hunt", "prepare", "track", "apply", "brief", "optimise"):
        if cmd not in by_cmd:
            continue
        c = by_cmd[cmd]
        detail = ", ".join(f"{c[a]} {a}" for a in KEEP if c[a]) or f"{sum(c.values())} events"
        parts.append(f"{cmd}: {detail}")
    return "; ".join(parts)


# ------------------------------------------------------------------ reporting

def _report_repo(label: str, repo: Path) -> None:
    if not is_git_repo(repo):
        print(f"{label}: not a git repo ({repo})")
        return
    dirty = porcelain(repo)
    ab = ahead_behind(repo)
    branch = current_branch(repo)
    remote = "origin" if has_remote(repo) else "no remote"
    state = "clean" if not dirty else f"{len(dirty)} uncommitted change(s)"
    ab_str = ""
    if ab:
        ab_str = f", ahead {ab[0]} / behind {ab[1]}"
    print(f"{label}: {branch} ({remote}) — {state}{ab_str}")
    for line in dirty[:10]:
        print(f"    {line}")
    if len(dirty) > 10:
        print(f"    … and {len(dirty) - 10} more")


# ------------------------------------------------------------------ verbs

def cmd_status(args) -> int:
    print("workspace and engine sync status\n")
    _report_repo("workspace", WORKSPACE)
    _report_repo("engine   ", ENGINE)
    print()
    if DB_PATH.exists():
        agree = db_verifies()
        print(f"database vs CSVs: {'in sync' if agree else 'OUT OF SYNC — run /sync push to re-export'}")
    else:
        print("database vs CSVs: no database (run db.py import-csv to rebuild)")
    meta = read_meta()
    if meta:
        print(f"last write:       {meta.get('last_write_at', '?')} on {meta.get('last_machine', '?')}")
    return 0


def cmd_init(args) -> int:
    if not is_git_repo(WORKSPACE):
        # Write the workspace .gitignore from the shipped template, then init.
        tmpl = ENGINE / "templates" / "workspace.gitignore"
        dest = WORKSPACE / ".gitignore"
        if tmpl.exists() and not dest.exists():
            dest.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Wrote {dest}")
        r = git(WORKSPACE, "init")
        print(r.stdout.strip() or "Initialised workspace git repo.")
    else:
        print("Workspace is already a git repo — ensuring .gitignore and remote only.")
        dest = WORKSPACE / ".gitignore"
        if not dest.exists():
            tmpl = ENGINE / "templates" / "workspace.gitignore"
            dest.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Wrote {dest}")

    # Write the pointer so desktop-launched sessions resolve the workspace even
    # without $JOBISSIMO_HOME exported (skip when it's the default location).
    if WORKSPACE.resolve() != (ENGINE / "profile").resolve():
        (ENGINE / ".jobissimo").write_text(str(WORKSPACE.resolve()) + "\n", encoding="utf-8")
        print(f"Wrote pointer {ENGINE / '.jobissimo'} -> {WORKSPACE}")

    # Ensure a fresh CSV export exists to commit (the DB itself is gitignored).
    run_db("export-csv")

    git(WORKSPACE, "add", "-A")
    staged = git(WORKSPACE, "diff", "--cached", "--name-only").stdout.splitlines()
    if staged:
        # Show a per-directory count and total size before committing.
        from collections import Counter
        by_dir = Counter(Path(f).parts[0] if Path(f).parts else "." for f in staged)
        size = sum((WORKSPACE / f).stat().st_size for f in staged if (WORKSPACE / f).exists())
        print(f"\nAbout to commit {len(staged)} files ({size / 1e6:.1f} MB):")
        for d, n in sorted(by_dir.items()):
            print(f"    {d}/  {n}")
    if args.dry_run:
        print("\n--dry-run: nothing committed.")
        return 0
    if staged:
        git(WORKSPACE, "commit", "-q", "-m", "workspace: initial sync snapshot")
        print("\nCommitted initial workspace snapshot.")

    if args.remote:
        if not has_remote(WORKSPACE):
            git(WORKSPACE, "remote", "add", "origin", args.remote)
            print(f"Added remote origin -> {args.remote}")
        else:
            print("Remote origin already set — leaving it as is.")
    return 0


def cmd_pull(args) -> int:
    rebuilt = False
    for label, repo in (("engine", ENGINE), ("workspace", WORKSPACE)):
        if not is_git_repo(repo) or not has_remote(repo):
            print(f"{label}: no remote — skipping pull")
            continue
        before = git(repo, "rev-parse", "HEAD").stdout.strip()
        r = git(repo, "pull", "--ff-only")
        after = git(repo, "rev-parse", "HEAD").stdout.strip()
        if r.returncode != 0:
            print(f"{label}: pull failed (not a fast-forward). Divergence — resolve manually:")
            print("   " + (r.stderr.strip().splitlines() or [""])[0])
            return 1
        print(f"{label}: {'up to date' if before == after else f'updated {before[:7]}..{after[:7]}'}")

    # Divergence guard on pipeline state: local DB has writes the CSVs lack AND
    # the pulled CSVs also moved => two machines diverged. Never auto-merge.
    if DB_PATH.exists() and (BACKUP / "jobs.csv").exists():
        local_ahead = not db_verifies()
        csv_moved = csv_newer_than_db()
        if local_ahead and csv_moved:
            print("\nDIVERGENCE: this machine's database has un-exported writes AND the "
                  "pulled CSVs moved. Refusing to merge pipeline state automatically.")
            print("Choose:")
            print("  • keep local  : db.py export-csv  (overwrites CSVs with this machine)")
            print("  • take remote : db.py import-csv  (archives local DB, rebuilds from CSVs)")
            print("  • inspect     : open both before deciding")
            return 2
        if csv_moved:
            print("CSVs are newer than the local DB — rebuilding database (db.py import-csv).")
            run_db("import-csv")
            rebuilt = True
    print("pull complete" + (" (database rebuilt from CSVs)" if rebuilt else ""))
    return 0


def cmd_push(args) -> int:
    # 1. Export, then verify. Abort on mismatch.
    print("1/5 export-csv + verify-csv")
    run_db("export-csv")
    if not db_verifies():
        print("ABORT: verify-csv mismatch after export — not committing.", file=sys.stderr)
        return 1

    # 2. Scrub the PUBLIC working tree. Any finding blocks the push.
    print("2/5 scrub gate (engine working tree + history)")
    scrub = subprocess.run(SCRUB_CLI + ["--all"], capture_output=True, text=True)
    if scrub.returncode != 0:
        print(scrub.stdout, file=sys.stderr)
        print("ABORT: scrub gate found personal data — not pushing.", file=sys.stderr)
        return 1

    # 3. Commit the workspace with a message derived from what happened.
    # A failed commit must never read as success: the changes stay staged and
    # the workspace push is skipped, so a green run always means committed.
    print("3/5 commit workspace")
    workspace_committed = True
    if is_git_repo(WORKSPACE) and porcelain(WORKSPACE):
        last_commit_ts = git(WORKSPACE, "log", "-1", "--format=%cI").stdout.strip() or None
        summary = events_summary_since(last_commit_ts)
        today = datetime.now(timezone.utc).date().isoformat()
        msg = f"sync {today}: {summary}" if summary else f"sync {today}: workspace snapshot"
        git(WORKSPACE, "add", "-A")
        commit = git(WORKSPACE, "commit", "-q", "-m", msg)
        if commit.returncode != 0:
            workspace_committed = False
            print("    workspace: COMMIT FAILED - changes remain staged, nothing pushed.",
                  file=sys.stderr)
            for line in (commit.stderr or commit.stdout).strip().splitlines():
                print(f"        {line}", file=sys.stderr)
        else:
            print(f"    workspace: {msg}")
    else:
        print("    workspace: nothing to commit")

    # 4. Commit the engine SEPARATELY, only if engine files changed.
    print("4/5 commit engine (only if changed)")
    if porcelain(ENGINE):
        print("    engine has uncommitted changes — commit these yourself with a")
        print("    conventional message (engine commits are code review, not a sync artefact):")
        for l in porcelain(ENGINE)[:10]:
            print(f"        {l}")
    else:
        print("    engine: clean")

    # 5. Push both. Read HEAD before pushing so the reported sha is the one
    # actually sent, and skip a repo with nothing to push so an unrelated
    # credential error cannot masquerade as a failed sync.
    failures = 0
    print("5/5 push")
    for label, repo in (("workspace", WORKSPACE), ("engine", ENGINE)):
        if label == "workspace" and not workspace_committed:
            print("    workspace: skipped - commit failed above")
            failures += 1
            continue
        if not is_git_repo(repo) or not has_remote(repo):
            print(f"    {label}: no remote — skipped")
            continue
        ab = ahead_behind(repo)
        if ab is not None and ab[0] == 0:
            print(f"    {label}: up to date — nothing to push")
            continue
        head = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        r = git(repo, "push")
        if r.returncode == 0:
            print(f"    {label}: pushed {head}")
        else:
            failures += 1
            print(f"    {label}: push FAILED: {r.stderr.strip()}", file=sys.stderr)
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb")
    sub.add_parser("status", help="Uncommitted state, db/CSV agreement, remotes, last writer.").set_defaults(func=cmd_status)
    i = sub.add_parser("init", help="One-time: workspace .gitignore, git init, first commit, private remote.")
    i.add_argument("--remote", help="Private remote URL to add as origin (never public).")
    i.add_argument("--dry-run", action="store_true", help="Show what would be committed, commit nothing.")
    i.set_defaults(func=cmd_init)
    sub.add_parser("pull", help="Pull both repos; rebuild DB from CSVs if newer; stop on divergence.").set_defaults(func=cmd_pull)
    sub.add_parser("push", help="export -> verify -> scrub -> commit workspace + engine -> push both.").set_defaults(func=cmd_push)
    return p


def main() -> int:
    args = build_parser().parse_args()
    if not getattr(args, "func", None):
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
