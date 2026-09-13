#!/usr/bin/env python3
"""db.py — the ONLY write path to the pipeline database.

Every mutation of pipeline state goes through a subcommand here. The LLM never
writes SQL and never edits the DB file directly. Every subcommand validates
enums and required fields and refuses bad input loudly (non-zero exit + stderr).

The database lives at $JOBISSIMO_HOME/state/pipeline.db (see scripts/paths.py).
Role clusters and location-fit values are validated against the active pack +
config UNION values already present in the DB, so historical rows imported
from another install never fail validation.

Run `python3 scripts/db.py --help` or `python3 scripts/db.py <cmd> --help`.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import socket
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402

DB_PATH = paths.state_db()

# ---------------------------------------------------------------- enums

STATUSES = [
    "found", "scored", "discarded", "shortlisted", "generated",
    "ready", "applied", "responded", "closed",
    "on_hold", "missed", "skipped",
]

# Allowed forward transitions. `discarded` is permanent (dedupe/no-rework
# record) — leaving it requires --force and is logged.
TRANSITIONS = {
    "found": {"scored", "discarded", "skipped"},
    "scored": {"discarded", "shortlisted", "on_hold", "skipped", "missed"},
    "shortlisted": {"generated", "discarded", "on_hold", "skipped", "missed"},
    "generated": {"ready", "on_hold", "skipped", "missed", "discarded"},
    "ready": {"applied", "on_hold", "skipped", "missed"},
    "applied": {"responded", "closed", "on_hold"},
    "responded": {"closed", "applied"},
    "closed": set(),
    "discarded": set(),
    "on_hold": {"scored", "shortlisted", "generated", "ready", "applied", "responded", "closed", "skipped", "discarded"},
    "missed": {"shortlisted", "discarded"},
    "skipped": {"shortlisted", "discarded"},
}

ATS_PLATFORMS = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "other", "unknown"]
OUTCOMES = ["no_response", "rejected", "interview", "offer", "withdrawn"]
RECOMMENDATIONS = ["yes", "maybe", "no"]
PRIORITIES = ["high", "medium", "low"]
REMOTE_FLAGS = ["remote", "hybrid", "onsite", "unclear"]
SENIORITY = ["yes", "stretch_up", "stretch_down", "no"]
AUDIT_STATUSES = ["pass", "fail", "bypassed"]

JOB_COLUMNS = [
    # identity
    "job_id", "source", "company", "title", "location", "remote_flag", "url",
    "original_url", "ats_platform", "date_found", "jd_path", "jd_language",
    "salary", "employment_type",
    # scoring
    "fit_score", "role_cluster", "seniority_match", "location_fit",
    "must_have_match", "missing_keywords", "company_stage", "company_signals",
    "red_flags", "apply_recommendation", "rejection_reason", "priority",
    "scored_at",
    # application lifecycle
    "status", "application_folder", "ats_score_det", "ats_score_llm",
    "ats_iterations", "audit_status", "date_applied", "applied_via",
    "follow_up_date", "response_date", "interview_stage", "outcome", "notes",
    "recruiter_name", "recruiter_url",
    # bookkeeping
    "created_at", "updated_at",
]

EVENT_COLUMNS = ["id", "ts", "run_id", "command", "job_id", "action", "detail"]
RESERVATION_COLUMNS = ["source", "max_n"]
META_COLUMNS = ["key", "value"]

# Bump when the CSV/table shape changes so import-csv can refuse a mismatch.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    remote_flag TEXT,
    url TEXT NOT NULL,
    original_url TEXT,
    ats_platform TEXT,
    date_found TEXT,
    jd_path TEXT,
    jd_language TEXT,
    salary TEXT,
    employment_type TEXT,
    fit_score REAL,
    role_cluster TEXT,
    seniority_match TEXT,
    location_fit TEXT,
    must_have_match TEXT,
    missing_keywords TEXT,
    company_stage TEXT,
    company_signals TEXT,
    red_flags TEXT,
    apply_recommendation TEXT,
    rejection_reason TEXT,
    priority TEXT,
    scored_at TEXT,
    status TEXT NOT NULL DEFAULT 'found',
    application_folder TEXT,
    ats_score_det INTEGER,
    ats_score_llm TEXT,
    ats_iterations INTEGER,
    audit_status TEXT,
    date_applied TEXT,
    applied_via TEXT,
    follow_up_date TEXT,
    response_date TEXT,
    interview_stage TEXT,
    outcome TEXT,
    notes TEXT,
    recruiter_name TEXT,
    recruiter_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    command TEXT,
    job_id TEXT,
    action TEXT NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS id_reservations (
    source TEXT PRIMARY KEY,
    max_n INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
"""


class DbError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Some mounted/sandboxed filesystems cannot take SQLite's rollback-journal
    # file locks. In-memory journal is fine for this single-user pipeline;
    # `export-csv` is the backup escape hatch.
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.executescript(SCHEMA)
    return conn


def stamp_write(conn: sqlite3.Connection) -> None:
    """Record which machine wrote and when, on every mutating path. `/sync`
    reads this to warn — before a machine overwrites the committed state — that
    the CSVs on the remote came from the OTHER machine more recently than this
    database was written."""
    for key, value in (("last_machine", socket.gethostname()),
                       ("last_write_at", now_iso())):
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))


def _column_values(conn: sqlite3.Connection, column: str) -> set:
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT {column} FROM jobs WHERE {column} IS NOT NULL")}


def role_clusters(conn: sqlite3.Connection | None = None) -> list:
    """Pack/config clusters ∪ clusters already present in the DB — imported
    historical rows must never fail validation."""
    vals = list(packs.role_clusters())
    if conn is not None:
        for v in sorted(_column_values(conn, "role_cluster")):
            if v not in vals:
                vals.append(v)
    return vals


def location_fit_values(conn: sqlite3.Connection | None = None) -> list:
    vals = list(packs.location_fit_values())
    if conn is not None:
        for v in sorted(_column_values(conn, "location_fit")):
            if v not in vals:
                vals.append(v)
    return vals


def validate_language(value: str) -> str:
    if not re.fullmatch(r"[a-z]{2}", value):
        raise DbError(f"jd_language must be a 2-letter lowercase ISO 639-1 code (en, it, de, ...), got `{value}`.")
    return value


def require_enum(value: str, allowed: list, name: str) -> str:
    if value not in allowed:
        raise DbError(f"Invalid {name} `{value}`. Allowed: {', '.join(allowed)}")
    return value


def require_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise DbError(f"Unknown job_id `{job_id}`.")
    return row


def validate_date(value: str, name: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DbError(f"{name} must be YYYY-MM-DD, got `{value}`.")
    return value


def canon_url(url: str | None) -> str | None:
    """Canonical form for dedupe. LinkedIn serves one listing under many
    locale subdomains (www./it./uk.) and slugged paths; the numeric job ID
    is the real identifier."""
    if not url:
        return url
    url = url.rstrip('/')
    m = re.search(r'linkedin\.com/jobs/view/(?:[^/?]*?-)?(\d{8,})', url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return url


# ---------------------------------------------------------------- commands

def _norm_title(title: str | None) -> str:
    """Collapse a job title to a comparison key: lowercased, punctuation and
    runs of non-alphanumerics folded to single spaces. Used by the add-job
    repost gate. This catches exact reposts regardless of case/spacing/
    punctuation (e.g. 'Product Manager' == 'product  manager!'), but does NOT
    fold away qualifier tokens like '(m/f/d)' or 'Senior' — a differently-worded
    title at the same company is treated as a distinct role and allowed through,
    to avoid false-positive blocks."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def cmd_add_job(args) -> None:
    require_enum(args.status, STATUSES, "status")
    if args.remote_flag:
        require_enum(args.remote_flag, REMOTE_FLAGS, "remote_flag")
    if args.ats_platform:
        require_enum(args.ats_platform, ATS_PLATFORMS, "ats_platform")
    if args.jd_language:
        validate_language(args.jd_language)
    validate_date(args.date_found, "date_found")
    conn = connect()
    if conn.execute("SELECT 1 FROM jobs WHERE job_id = ?", (args.job_id,)).fetchone():
        raise DbError(f"job_id `{args.job_id}` already exists. Use set-field to modify.")
    new_canon = canon_url(args.url)
    dup = next(
        (r for r in conn.execute("SELECT job_id, url, original_url FROM jobs").fetchall()
         if canon_url(r["url"]) == new_canon or canon_url(r["original_url"]) == new_canon),
        None,
    )
    if dup and not args.allow_duplicate_url:
        raise DbError(f"URL already recorded for job `{dup['job_id']}`. Pass --allow-duplicate-url to override.")
    # Company + title repost gate: URL dedupe misses portal reposts (fresh ids)
    # and origination-URL drift (careers-site path variants for the same job).
    # Deterministic here so it holds even when the hunt prompt's company check
    # is skipped.
    if not args.allow_duplicate_url:
        new_ct = ((args.company or "").strip().lower(), _norm_title(args.title))
        ct_dup = next(
            (r for r in conn.execute(
                "SELECT job_id, status, company, title FROM jobs "
                "WHERE status != 'discarded'").fetchall()
             if ((r["company"] or "").strip().lower(), _norm_title(r["title"])) == new_ct),
            None,
        )
        if ct_dup:
            raise DbError(
                f"Same company + title as `{ct_dup['job_id']}` (status {ct_dup['status']}) — "
                "likely a repost. Skip it, or pass --allow-duplicate-url if genuinely distinct.")
    ts = now_iso()
    conn.execute(
        """INSERT INTO jobs (job_id, source, company, title, location, remote_flag,
            url, original_url, ats_platform, date_found, jd_path, jd_language,
            salary, employment_type, status, notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (args.job_id, args.source, args.company, args.title, args.location,
         args.remote_flag, args.url, args.original_url, args.ats_platform,
         args.date_found, args.jd_path, args.jd_language, args.salary,
         args.employment_type, args.status, args.notes, ts, ts),
    )
    stamp_write(conn)
    conn.commit()
    print(f"Added {args.job_id} ({args.company} — {args.title}) status={args.status}")


def cmd_score(args) -> None:
    conn = connect()
    require_enum(args.role_cluster, role_clusters(conn), "role_cluster")
    require_enum(args.seniority_match, SENIORITY, "seniority_match")
    require_enum(args.location_fit, location_fit_values(conn), "location_fit")
    require_enum(args.apply_recommendation, RECOMMENDATIONS, "apply_recommendation")
    require_enum(args.priority, PRIORITIES, "priority")
    fit = float(args.fit_score)
    if not 1.0 <= fit <= 5.0:
        raise DbError(f"fit_score must be in [1.0, 5.0], got {fit}.")
    if args.apply_recommendation == "no" and not args.rejection_reason:
        raise DbError("apply_recommendation=no requires --rejection-reason.")
    if args.set_status:
        require_enum(args.set_status, ["scored", "discarded", "shortlisted"], "set-status (after scoring)")
    row = require_job(conn, args.job_id)
    new_status = args.set_status or (
        "discarded" if args.apply_recommendation == "no" else "shortlisted"
    )
    if row["status"] not in ("found", "scored") and not args.force:
        raise DbError(
            f"{args.job_id} has status `{row['status']}`; rescoring needs --force."
        )
    conn.execute(
        """UPDATE jobs SET fit_score=?, role_cluster=?, seniority_match=?,
            location_fit=?, must_have_match=?, missing_keywords=?,
            company_stage=?, company_signals=?, red_flags=?,
            apply_recommendation=?, rejection_reason=?, priority=?, scored_at=?,
            status=?, updated_at=? WHERE job_id=?""",
        (fit, args.role_cluster, args.seniority_match, args.location_fit,
         args.must_have_match, args.missing_keywords, args.company_stage,
         args.company_signals, args.red_flags, args.apply_recommendation,
         args.rejection_reason, args.priority, args.scored_at or now_iso(),
         new_status, now_iso(), args.job_id),
    )
    stamp_write(conn)
    conn.commit()
    print(f"Scored {args.job_id}: fit={fit} rec={args.apply_recommendation} "
          f"priority={args.priority} -> status={new_status}")


def cmd_set_status(args) -> None:
    require_enum(args.status, STATUSES, "status")
    conn = connect()
    row = require_job(conn, args.job_id)
    current = row["status"]
    if args.status == current:
        print(f"{args.job_id} already has status `{current}`. No change.")
        return
    allowed = TRANSITIONS.get(current, set())
    if args.status not in allowed:
        if not args.force:
            raise DbError(
                f"Transition `{current}` -> `{args.status}` is not allowed for {args.job_id}. "
                f"Allowed from `{current}`: {', '.join(sorted(allowed)) or '(none — terminal)'}. "
                "Pass --force to override (it will be logged)."
            )
        log_event(conn, run_id=args.run_id, command="set-status",
                  job_id=args.job_id, action="forced_transition",
                  detail=json.dumps({"from": current, "to": args.status}))
    updates = {"status": args.status}
    today = date.today().isoformat()
    if args.status == "applied":
        if not row["date_applied"]:
            updates["date_applied"] = args.date or today
        # Follow-ups are warm-channel only: referral/email applies or a known
        # recruiter. Cold portal applies get no follow_up_date.
        warm = (args.applied_via or row["applied_via"] or "") in ("referral", "email") \
            or bool(row["recruiter_name"])
        if warm and not row["follow_up_date"]:
            base = date.fromisoformat(updates.get("date_applied", row["date_applied"] or today))
            updates["follow_up_date"] = (base + timedelta(days=7)).isoformat()
        if args.applied_via:
            updates["applied_via"] = args.applied_via
    if args.status == "responded" and not row["response_date"]:
        updates["response_date"] = args.date or today
    if args.status == "discarded" and args.reason:
        updates["rejection_reason"] = args.reason
    if args.status == "closed" and args.outcome:
        require_enum(args.outcome, OUTCOMES, "outcome")
        updates["outcome"] = args.outcome
    sets = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE jobs SET {sets}, updated_at=? WHERE job_id=?",
                 (*updates.values(), now_iso(), args.job_id))
    log_event(conn, run_id=args.run_id, command="set-status", job_id=args.job_id,
              action="status_change", detail=json.dumps({"from": current, "to": args.status, **{k: v for k, v in updates.items() if k != "status"}}))
    stamp_write(conn)
    conn.commit()
    extra = {k: v for k, v in updates.items() if k != "status"}
    print(f"{args.job_id}: {current} -> {args.status}" + (f" ({extra})" if extra else ""))


def settable_fields(conn: sqlite3.Connection) -> dict:
    """Fields settable via `set-field`, with optional enum constraint."""
    return {
        "source": None, "company": None, "title": None, "location": None,
        "remote_flag": REMOTE_FLAGS, "url": None, "original_url": None,
        "ats_platform": ATS_PLATFORMS, "date_found": None, "jd_path": None,
        "jd_language": None,  # ISO 639-1 code, validated separately
        "salary": None, "employment_type": None,
        "fit_score": None, "role_cluster": role_clusters(conn),
        "seniority_match": SENIORITY, "location_fit": location_fit_values(conn),
        "must_have_match": None, "missing_keywords": None, "company_stage": None,
        "company_signals": None, "red_flags": None,
        "apply_recommendation": RECOMMENDATIONS, "rejection_reason": None,
        "priority": PRIORITIES, "scored_at": None,
        "application_folder": None, "ats_score_det": None, "ats_score_llm": None,
        "ats_iterations": None, "audit_status": AUDIT_STATUSES,
        "date_applied": None, "applied_via": None, "follow_up_date": None,
        "response_date": None, "interview_stage": None, "outcome": OUTCOMES,
        "notes": None, "recruiter_name": None, "recruiter_url": None,
    }


def cmd_set_field(args) -> None:
    conn = connect()
    fields = settable_fields(conn)
    if args.field not in fields:
        raise DbError(f"Field `{args.field}` is not settable. Allowed: {', '.join(sorted(fields))}. "
                      "(status changes go through set-status.)")
    allowed = fields[args.field]
    value = args.value
    if value == "":
        value = None
    elif allowed is not None:
        require_enum(value, allowed, args.field)
    if args.field in ("date_applied", "follow_up_date", "response_date", "date_found") and value:
        validate_date(value, args.field)
    if args.field == "jd_language" and value:
        validate_language(value)
    if args.field in ("ats_score_det", "ats_iterations") and value is not None:
        if not value.isdigit():
            raise DbError(f"{args.field} must be a non-negative integer.")
        value = int(value)
    if args.field == "fit_score" and value is not None:
        value = float(value)
    row = require_job(conn, args.job_id)
    old = row[args.field]
    conn.execute(f"UPDATE jobs SET {args.field}=?, updated_at=? WHERE job_id=?",
                 (value, now_iso(), args.job_id))
    stamp_write(conn)
    conn.commit()
    print(f"{args.job_id}.{args.field}: {old!r} -> {value!r}")


def cmd_get(args) -> None:
    conn = connect()
    row = require_job(conn, args.job_id)
    for col in JOB_COLUMNS:
        val = row[col]
        if val not in (None, ""):
            print(f"{col}: {val}")


def cmd_list(args) -> None:
    conn = connect()
    clauses, params = [], []
    if args.status:
        for s in args.status:
            require_enum(s, STATUSES, "status")
        ph = ",".join("?" * len(args.status))
        clauses.append(f"status IN ({ph})")
        params.extend(args.status)
    if args.recommendation:
        clauses.append("apply_recommendation = ?")
        params.append(args.recommendation)
    if args.priority:
        clauses.append("priority = ?")
        params.append(args.priority)
    if args.since:
        validate_date(args.since, "--since")
        clauses.append("date_found >= ?")
        params.append(args.since)
    if getattr(args, "source", None):
        clauses.append("source = ?")
        params.append(args.source)
    if getattr(args, "company", None):
        clauses.append("LOWER(company) LIKE ?")
        params.append(f"%{args.company.lower()}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT job_id, company, title, status, fit_score, apply_recommendation AS rec, "
        f"priority, jd_language AS lang, date_found, ats_score_det FROM jobs {where} "
        f"ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        f"fit_score DESC, date_found DESC", params
    ).fetchall()
    if not rows:
        print("No jobs match.")
        return
    headers = rows[0].keys()
    widths = {h: max(len(h), *(len(str(r[h] if r[h] is not None else "")) for r in rows)) for h in headers}
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for r in rows:
        print(" | ".join(str(r[h] if r[h] is not None else "").ljust(widths[h]) for h in headers))
    print(f"\n{len(rows)} job(s).")


def cmd_next_id(args) -> None:
    conn = connect()
    # Atomic reservation: two concurrent callers must not receive the same id.
    # BEGIN IMMEDIATE takes the write lock before we read the max, closing the
    # read-then-write race; a persisted `id_reservations` counter means the
    # reserved id is visible even before an add-job row exists. Degrades to
    # best-effort if the filesystem rejects the lock.
    conn.isolation_level = None  # manual transaction control
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("CREATE TABLE IF NOT EXISTS id_reservations "
                 "(source TEXT PRIMARY KEY, max_n INTEGER NOT NULL)")
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        pass
    rows = conn.execute("SELECT job_id FROM jobs WHERE job_id LIKE ?",
                        (f"{args.source_slug}%",)).fetchall()
    max_n = 0
    for r in rows:
        suffix = r["job_id"][len(args.source_slug):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    res = conn.execute("SELECT max_n FROM id_reservations WHERE source = ?",
                       (args.source_slug,)).fetchone()
    if res:
        max_n = max(max_n, res["max_n"])
    next_n = max_n + 1
    conn.execute("INSERT INTO id_reservations (source, max_n) VALUES (?, ?) "
                 "ON CONFLICT(source) DO UPDATE SET max_n = excluded.max_n",
                 (args.source_slug, next_n))
    stamp_write(conn)
    conn.execute("COMMIT")
    print(f"{args.source_slug}{next_n:03d}")


def loose_url(url: str | None) -> str | None:
    """Aggressive normalisation used only by `urls --check`. On top of
    canon_url: drop scheme, leading `www.`, query string, fragment and any
    trailing slash, and lowercase the host. Aggregators hand out the same ATS
    posting with different tracking params, so an exact string compare misses."""
    if not url:
        return url
    u = canon_url(url)
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = u.split('#', 1)[0].split('?', 1)[0]
    return u.rstrip('/').lower()


def cmd_urls(args) -> None:
    conn = connect()
    rows = conn.execute("SELECT job_id, url, original_url, status FROM jobs").fetchall()

    if args.check:
        index = {}
        for r in rows:
            for raw in (r["url"], r["original_url"]):
                key = loose_url(raw)
                if key and key not in index:
                    index[key] = (r["job_id"], r["status"])
        known = 0
        for probe in args.check:
            hit = index.get(loose_url(probe))
            if hit:
                known += 1
                print(f"{probe}\tKNOWN\t{hit[0]}\t{hit[1]}")
            else:
                print(f"{probe}\tNEW\t-\t-")
        print(f"# {known}/{len(args.check)} already known", file=sys.stderr)
        return

    seen = set()
    def emit(raw, job_id, status):
        for u in {raw.rstrip('/'), canon_url(raw)}:
            if u not in seen:
                seen.add(u)
                print(f"{u}\t{job_id}\t{status}")
    for r in rows:
        emit(r["url"], r["job_id"], r["status"])
        if r["original_url"]:
            emit(r["original_url"], r["job_id"], r["status"])
    print(f"# {len(rows)} jobs", file=sys.stderr)


def log_event(conn, *, run_id, command, job_id, action, detail) -> None:
    if detail:
        try:
            json.loads(detail)
        except json.JSONDecodeError:
            raise DbError(f"--detail must be valid JSON, got: {detail[:200]}")
    conn.execute(
        "INSERT INTO events (ts, run_id, command, job_id, action, detail) VALUES (?,?,?,?,?,?)",
        (now_iso(), run_id, command, job_id, action, detail),
    )


def cmd_log(args) -> None:
    conn = connect()
    log_event(conn, run_id=args.run_id, command=args.command_name,
              job_id=args.job_id, action=args.action, detail=args.detail)
    stamp_write(conn)
    conn.commit()
    print(f"Logged: run={args.run_id} action={args.action}" + (f" job={args.job_id}" if args.job_id else ""))


def cmd_dashboard(args) -> None:
    conn = connect()
    today = date.today()
    today_iso = today.isoformat()
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    total = sum(counts.values())
    print("# Pipeline Dashboard\n")
    print(f"_{today_iso} — {total} jobs tracked_\n")

    # momentum — sent counts use the same definition as stats (date_applied set)
    monday_iso = (today - timedelta(days=today.weekday())).isoformat()
    month_iso = today.replace(day=1).isoformat()
    def sent_since(since):
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE date_applied IS NOT NULL AND date_applied >= ?",
            (since,)).fetchone()[0]
    week_n, month_n = sent_since(monday_iso), sent_since(month_iso)
    print("## Momentum\n")
    print(f"- Sent this week (since Mon {monday_iso}): **{week_n}**")
    print(f"- Sent this month: **{month_n}**")
    # conversion funnel — each later stage is appended ONLY when it has events,
    # so the line grows as the pipeline matures. % is of applications sent.
    frows = conn.execute(
        "SELECT date_applied, response_date, interview_stage, outcome FROM jobs").fetchall()
    appl = [r for r in frows if r["date_applied"]]
    n_appl = len(appl)
    n_resp = sum(1 for r in appl if r["response_date"])
    _pref = ("hm:", "hr:", "tech:", "panel:", "final:", "offer:")

    def _stage(r):
        return (r["interview_stage"] or "").lower()

    def _reached_test(r):
        return "test:" in _stage(r) or "async test" in _stage(r)

    def _reached_interview(r):
        return (r["outcome"] or "") in ("interview", "offer") \
            or any(p in _stage(r) for p in _pref)
    # "past screen" = the response advanced beyond CV screening — evidenced by an
    # async test or an interview invite (vs a straight screening rejection).
    n_test = sum(1 for r in appl if _reached_test(r))
    n_screen = sum(1 for r in appl if _reached_test(r) or _reached_interview(r))
    n_intv = sum(1 for r in appl if _reached_interview(r))
    n_offer = sum(1 for r in frows if (r["outcome"] or "") == "offer"
                  or "offer:" in _stage(r))

    def _pct(x):
        return f" ({100 * x // n_appl}%)" if n_appl else ""
    chain = [f"{n_appl} applied", f"{n_resp} responded{_pct(n_resp)}"]
    if n_screen:
        chain.append(f"{n_screen} past screen{_pct(n_screen)}")
    if n_intv:
        chain.append(f"{n_intv} interview{_pct(n_intv)}")
    if n_offer:
        chain.append(f"{n_offer} offer{_pct(n_offer)}")
    print(f"- Funnel: {' → '.join(chain)}")
    if n_resp:
        detail = f"- Response quality: {n_screen}/{n_resp} responses passed CV screen"
        if n_test:
            detail += f" ({n_test} via async test)"
        detail += f", {n_resp - n_screen} were screening rejections"
        print(detail)
    print()

    print("## Funnel\n")
    for s in STATUSES:
        if counts.get(s):
            print(f"  {s:<12} {counts[s]:>4}")
    print()

    def job_line(r, meta):
        print(f"- {r['job_id']}  {r['company']} — {r['title']}  [{meta}]")
        link = r["original_url"] or r["url"]
        if link:
            print(f"  {link}")

    def section(title, query, params=(), with_ats=False):
        rows = conn.execute(query, params).fetchall()
        if not rows:
            return
        print(f"## {title}\n")
        for r in rows:
            meta = f"{r['priority'] or '-'} | fit {r['fit_score'] or '-'}"
            if with_ats and r["ats_score_det"] is not None:
                meta += f" | ats {r['ats_score_det']}"
            meta += f" | found {r['date_found'] or '-'}"
            job_line(r, meta)
        print()

    order = ("ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
             "fit_score DESC, date_found DESC")
    section("Action: shortlisted — run /prepare",
            f"SELECT * FROM jobs WHERE status='shortlisted' {order}")
    section("Action: ready — apply now",
            f"SELECT * FROM jobs WHERE status='ready' {order}", with_ats=True)

    responded_rows = conn.execute(
        "SELECT * FROM jobs WHERE status='responded' "
        "ORDER BY response_date DESC").fetchall()
    if responded_rows:
        print("## In progress: responded\n")
        for r in responded_rows:
            stage = r["interview_stage"] or "—"
            print(f"- {r['job_id']}  {r['company']} — {r['title']}")
            print(f"  stage: {stage}")
            link = r["original_url"] or r["url"]
            if link:
                print(f"  {link}")
        print()

    # A follow-up more than 14 days past due is noise, not an action.
    stale_cutoff = (date.fromisoformat(today_iso) - timedelta(days=14)).isoformat()
    overdue = conn.execute(
        "SELECT * FROM jobs "
        "WHERE status='applied' AND follow_up_date IS NOT NULL AND follow_up_date <= ? "
        "AND follow_up_date >= ? "
        "ORDER BY follow_up_date", (today_iso, stale_cutoff)).fetchall()
    if overdue:
        print(f"## Action: warm follow-ups due ({len(overdue)})\n")
        for r in overdue[:8]:
            job_line(r, f"applied {r['date_applied']} | follow-up due {r['follow_up_date']}")
        if len(overdue) > 8:
            print(f"- …and {len(overdue) - 8} more — run /track follow up <job_id>")
        print()
    waiting = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('applied','responded')").fetchone()[0]
    print(f"_In flight (applied/responded): {waiting}. "
          f"Discarded (permanent no-rework record): {counts.get('discarded', 0)}._")


def _stats_filters(args):
    clauses, params = [], []
    if args.since:
        validate_date(args.since, "--since")
        clauses.append("date_found >= ?")
        params.append(args.since)
    if args.source:
        clauses.append("source = ?")
        params.append(args.source)
    if args.status:
        ph = ",".join("?" * len(args.status))
        clauses.append(f"status IN ({ph})")
        params.extend(args.status)
    if args.priority:
        clauses.append("priority = ?")
        params.append(args.priority)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def cmd_stats(args) -> None:
    conn = connect()
    where, params = _stats_filters(args)
    rows = conn.execute(f"SELECT * FROM jobs {where}", params).fetchall()
    if not rows:
        print("No jobs match the filters.")
        return
    today = date.today().isoformat()
    filters_desc = []
    for name in ("since", "source", "priority"):
        if getattr(args, name):
            filters_desc.append(f"{name}={getattr(args, name)}")
    if args.status:
        filters_desc.append(f"status={','.join(args.status)}")
    print("# Pipeline Stats" + (f" ({'; '.join(filters_desc)})" if filters_desc else ""))
    print(f"\n_{today} — {len(rows)} jobs in scope_\n")

    # funnel ---------------------------------------------------------------
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print("## Funnel\n")
    for s in STATUSES:
        if by_status.get(s):
            print(f"  {s:<12} {by_status[s]:>4}  {100 * by_status[s] // len(rows):>3}%")
    applied_plus = [r for r in rows if r["status"] in ("applied", "responded", "closed", "on_hold")
                    and r["date_applied"]]
    responded = [r for r in applied_plus if r["response_date"]]
    _interview_prefixes = ("hm:", "hr:", "tech:", "panel:", "final:", "offer:")
    positive = [r for r in responded if (r["outcome"] or "") in ("interview", "offer")
                or "interview" in (r["interview_stage"] or "").lower()
                or any(p in (r["interview_stage"] or "").lower() for p in _interview_prefixes)]
    # past CV screen = advanced beyond a screening rejection (async test or interview)
    screen_passed = [r for r in responded
                     if "test:" in (r["interview_stage"] or "").lower()
                     or "async test" in (r["interview_stage"] or "").lower()
                     or r in positive]
    tested = [r for r in responded if "test:" in (r["interview_stage"] or "").lower()
              or "async test" in (r["interview_stage"] or "").lower()]
    print(f"\nApplications sent: {len(applied_plus)} | responses: {len(responded)}"
          + (f" ({100 * len(responded) // len(applied_plus)}%)" if applied_plus else "")
          + f" | past CV screen: {len(screen_passed)} ({len(tested)} async test)"
          + f" | interviews/offers: {len(positive)}")

    # time-to-response breakdown -------------------------------------------
    import datetime as _dt
    ttrs = []
    for r in responded:
        try:
            d1 = _dt.date.fromisoformat(r["date_applied"][:10])
            d2 = _dt.date.fromisoformat(r["response_date"][:10])
            ttrs.append((d2 - d1).days)
        except Exception:
            pass
    if ttrs:
        quick = sum(1 for d in ttrs if d <= 7)
        considered = len(ttrs) - quick
        avg = sum(ttrs) / len(ttrs)
        print(f"Time-to-response: avg {avg:.0f}d"
              f" | quick ≤7d (likely auto-screen): {quick}"
              f" | considered >7d: {considered}")

    # per-source -----------------------------------------------------------
    print("\n## Per source\n")
    sources = {}
    for r in rows:
        sources.setdefault(r["source"], []).append(r)
    progressed = ("shortlisted", "generated", "ready", "applied", "responded", "closed", "on_hold")
    print(f"  {'source':<14} {'found':>5} {'disc':>5} {'short+':>6} {'appl+':>5} {'resp':>5}")
    for src in sorted(sources, key=lambda s: -len(sources[s])):
        grp = sources[src]
        disc = sum(1 for r in grp if r["status"] == "discarded")
        short = sum(1 for r in grp if r["status"] in progressed)
        appl = sum(1 for r in grp if r["date_applied"])
        resp = sum(1 for r in grp if r["response_date"])
        print(f"  {src:<14} {len(grp):>5} {disc:>5} {short:>6} {appl:>5} {resp:>5}")

    # scoring / ATS --------------------------------------------------------
    fits = [r["fit_score"] for r in rows if r["fit_score"] is not None]
    dets = [r["ats_score_det"] for r in rows if r["ats_score_det"] is not None]
    print("\n## Scores\n")
    if fits:
        print(f"- fit_score: avg {sum(fits) / len(fits):.2f} over {len(fits)} scored")
    recs = {}
    for r in rows:
        if r["apply_recommendation"]:
            recs[r["apply_recommendation"]] = recs.get(r["apply_recommendation"], 0) + 1
    if recs:
        print("- recommendations: " + ", ".join(f"{k}={v}" for k, v in sorted(recs.items())))
    if dets:
        print(f"- ATS det score: avg {sum(dets) / len(dets):.0f} over {len(dets)} prepared"
              f" (min {min(dets)}, max {max(dets)})")
    grades = {}
    for r in rows:
        if r["ats_score_llm"]:
            grades[r["ats_score_llm"]] = grades.get(r["ats_score_llm"], 0) + 1
    if grades:
        print("- ATS LLM grades: " + ", ".join(f"{k}={v}" for k, v in sorted(grades.items())))

    # stage distribution ---------------------------------------------------
    _stage_labels = [
        ("screen:", "screen"),
        ("hr:",     "hr call"),
        ("hm:",     "hm call"),
        ("test:",   "test"),
        ("tech:",   "tech intv"),
        ("panel:",  "panel"),
        ("final:",  "final"),
        ("offer:",  "offer"),
    ]
    stage_counts = {}
    for r in rows:
        st = (r["interview_stage"] or "").lower()
        for prefix, label in _stage_labels:
            if prefix in st:
                stage_counts[label] = stage_counts.get(label, 0) + 1
    if stage_counts:
        print("\n## Stage distribution (jobs reaching each stage)\n")
        for _, label in _stage_labels:
            if stage_counts.get(label):
                print(f"  {label:<10} {stage_counts[label]}")

    # outcomes -------------------------------------------------------------
    outs = {}
    for r in rows:
        if r["outcome"]:
            outs[r["outcome"]] = outs.get(r["outcome"], 0) + 1
    if outs:
        print("\n## Outcomes\n")
        for k, v in sorted(outs.items(), key=lambda kv: -kv[1]):
            print(f"- {k}: {v}")

    # waiting / overdue ----------------------------------------------------
    overdue = [r for r in rows if r["status"] == "applied" and r["follow_up_date"]
               and r["follow_up_date"] <= today]
    if overdue:
        print("\n## Overdue follow-ups\n")
        for r in overdue:
            print(f"- {r['job_id']} {r['company']} (applied {r['date_applied']}, due {r['follow_up_date']})")


# The text export is the record of record: the DB is a runtime artefact,
# rebuilt from these CSVs (see /sync). Stable table set, stable row order, and
# stable column order so a commit diff shows only what actually changed.
CSV_TABLES = [
    ("jobs", JOB_COLUMNS, "job_id"),
    ("events", EVENT_COLUMNS, "id"),
    ("id_reservations", RESERVATION_COLUMNS, "source"),
    ("meta", META_COLUMNS, "key"),
]


def _table_csv_bytes(conn: sqlite3.Connection, table: str, cols: list, order: str):
    """Render a table to deterministic CSV bytes. Returns (bytes, row_count)."""
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue().encode("utf-8"), len(rows)


def _events_seq(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
    return row[0] if row else None


def _default_backup_dir() -> Path:
    return paths.home() / "state" / "backup"


def cmd_export_csv(args) -> None:
    conn = connect()
    out = Path(args.out) if args.out else _default_backup_dir()
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": now_iso(),
        "machine": socket.gethostname(),
        "events_seq": _events_seq(conn),
        "tables": {},
    }
    for table, cols, order in CSV_TABLES:
        data, n = _table_csv_bytes(conn, table, cols, order)
        (out / f"{table}.csv").write_bytes(data)
        manifest["tables"][table] = {"rows": n, "sha256": hashlib.sha256(data).hexdigest()}
        print(f"Wrote {out / f'{table}.csv'} ({n} rows)")
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {out / 'manifest.json'} (schema v{SCHEMA_VERSION}, events_seq={manifest['events_seq']})")


def _read_csv(path: Path):
    """Yield rows as lists; empty string -> None (set-field '' clears to NULL,
    so the DB never stores '' deliberately). SQLite column affinity coerces
    numeric strings back to INTEGER/REAL on insert."""
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        for row in reader:
            yield header, [None if v == "" else v for v in row]


def cmd_import_csv(args) -> None:
    src = Path(args.dir) if args.dir else _default_backup_dir()
    if not src.exists():
        raise DbError(f"CSV directory not found: {src}")
    for table, _, _ in CSV_TABLES:
        if table in ("jobs", "events") and not (src / f"{table}.csv").exists():
            raise DbError(f"Missing required {table}.csv in {src}")
    manifest = {}
    if (src / "manifest.json").exists():
        manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise DbError(f"manifest schema_version {manifest.get('schema_version')} "
                          f"!= this build's {SCHEMA_VERSION}; refusing to import.")

    # Move an existing DB aside rather than overwriting — a restore is
    # reversible, an overwrite is not.
    if DB_PATH.exists():
        bak = DB_PATH.with_name(f"{DB_PATH.name}.bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        DB_PATH.rename(bak)
        print(f"Moved existing database aside: {bak}")

    conn = connect()
    total = {}
    for table, cols, _ in CSV_TABLES:
        path = src / f"{table}.csv"
        if not path.exists():
            total[table] = 0
            continue
        placeholders = ",".join("?" for _ in cols)
        collist = ",".join(cols)
        n = 0
        for header, values in _read_csv(path):
            if header != cols:
                raise DbError(f"{table}.csv header {header} != expected {cols}")
            conn.execute(f"INSERT INTO {table} ({collist}) VALUES ({placeholders})", values)
            n += 1
        total[table] = n

    # Restore the events AUTOINCREMENT high-water mark exactly. Inserting rows
    # only advances sqlite_sequence to max(id) seen; if events were ever
    # deleted, the real sequence is higher, and restarting below it would
    # re-issue an id — corrupting the telemetry /optimise depends on.
    seq = manifest.get("events_seq")
    if seq is not None:
        conn.execute("DELETE FROM sqlite_sequence WHERE name='events'")
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('events', ?)", (int(seq),))
    conn.commit()
    parts = ", ".join(f"{t}={total[t]}" for t, _, _ in CSV_TABLES)
    print(f"Imported into {DB_PATH}: {parts}" + (f", events_seq={seq}" if seq is not None else ""))


def cmd_verify_csv(args) -> None:
    """Compare the live database against the CSVs, per table: row counts and
    SHA-256 on both sides. Exit 1 on any mismatch. /sync push calls this before
    it commits anything."""
    src = Path(args.dir) if args.dir else _default_backup_dir()
    conn = connect()
    ok = True
    print(f"{'table':<16} {'db rows':>8} {'csv rows':>9}  match")
    for table, cols, order in CSV_TABLES:
        db_bytes, db_n = _table_csv_bytes(conn, table, cols, order)
        path = src / f"{table}.csv"
        if not path.exists():
            print(f"{table:<16} {db_n:>8} {'MISSING':>9}  NO")
            ok = False
            continue
        csv_bytes = path.read_bytes()
        csv_n = max(0, csv_bytes.decode('utf-8').count('\n') - 1)
        match = hashlib.sha256(db_bytes).hexdigest() == hashlib.sha256(csv_bytes).hexdigest()
        ok = ok and match
        print(f"{table:<16} {db_n:>8} {csv_n:>9}  {'yes' if match else 'NO'}")
    # events sequence, if a manifest is present
    if (src / "manifest.json").exists():
        man = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
        db_seq, csv_seq = _events_seq(conn), man.get("events_seq")
        seq_ok = db_seq == csv_seq
        ok = ok and seq_ok
        print(f"{'events_seq':<16} {str(db_seq):>8} {str(csv_seq):>9}  {'yes' if seq_ok else 'NO'}")
    if not ok:
        print("VERIFY: MISMATCH — database and CSVs disagree.", file=sys.stderr)
        raise SystemExit(1)
    print("VERIFY: clean — database and CSVs agree.")


# ---------------------------------------------------------------- argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add-job", help="Add a newly found job.")
    a.add_argument("--job-id", required=True)
    a.add_argument("--source", required=True)
    a.add_argument("--company", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--url", required=True)
    a.add_argument("--date-found", required=True, help="YYYY-MM-DD")
    a.add_argument("--jd-path", required=True, help="e.g. jd_texts/sample001.md")
    a.add_argument("--jd-language", help="ISO 639-1 code of the posting language, e.g. en, it")
    a.add_argument("--location")
    a.add_argument("--remote-flag", choices=REMOTE_FLAGS)
    a.add_argument("--original-url")
    a.add_argument("--ats-platform", choices=ATS_PLATFORMS)
    a.add_argument("--salary")
    a.add_argument("--employment-type")
    a.add_argument("--status", default="found", choices=STATUSES)
    a.add_argument("--notes")
    a.add_argument("--allow-duplicate-url", action="store_true")
    a.set_defaults(func=cmd_add_job)

    s = sub.add_parser("score", help="Record scoring fields for a job. Default status: no->discarded, yes/maybe->shortlisted.")
    s.add_argument("--job-id", required=True)
    s.add_argument("--fit-score", required=True)
    s.add_argument("--role-cluster", required=True,
                   help="Cluster id from the active pack's roles.yaml (values already in the DB stay valid).")
    s.add_argument("--seniority-match", required=True, choices=SENIORITY)
    s.add_argument("--location-fit", required=True,
                   help="One of the configured location-fit values (see config/pipeline.yaml).")
    s.add_argument("--apply-recommendation", required=True, choices=RECOMMENDATIONS)
    s.add_argument("--priority", required=True, choices=PRIORITIES)
    s.add_argument("--must-have-match", help="semicolon-separated")
    s.add_argument("--missing-keywords", help="semicolon-separated")
    s.add_argument("--company-stage")
    s.add_argument("--company-signals", help="semicolon-separated")
    s.add_argument("--red-flags", help="semicolon-separated")
    s.add_argument("--rejection-reason")
    s.add_argument("--scored-at")
    s.add_argument("--set-status", choices=["scored", "discarded", "shortlisted"],
                   help="Override the post-scoring status.")
    s.add_argument("--force", action="store_true", help="Allow rescoring past `scored`.")
    s.set_defaults(func=cmd_score)

    st = sub.add_parser("set-status", help="Change lifecycle status (validated transitions).")
    st.add_argument("--job-id", required=True)
    st.add_argument("--status", required=True, choices=STATUSES)
    st.add_argument("--date", help="YYYY-MM-DD for date_applied/response_date side effects.")
    st.add_argument("--applied-via", help="e.g. employer_site, linkedin, portal_only")
    st.add_argument("--outcome", choices=OUTCOMES, help="With --status closed.")
    st.add_argument("--reason", help="With --status discarded: rejection reason.")
    st.add_argument("--run-id", help="Run id for the event log.")
    st.add_argument("--force", action="store_true", help="Override transition validation (logged).")
    st.set_defaults(func=cmd_set_status)

    sf = sub.add_parser("set-field", help="Set one whitelisted field on a job.")
    sf.add_argument("--job-id", required=True)
    sf.add_argument("field", help="Field name (see error message for the list).")
    sf.add_argument("value", help="New value ('' clears).")
    sf.set_defaults(func=cmd_set_field)

    g = sub.add_parser("get", help="Print all non-empty fields of a job.")
    g.add_argument("job_id")
    g.set_defaults(func=cmd_get)

    l = sub.add_parser("list", help="List jobs as a table.")
    l.add_argument("--status", action="append", help="Repeatable.")
    l.add_argument("--recommendation", choices=RECOMMENDATIONS)
    l.add_argument("--priority", choices=PRIORITIES)
    l.add_argument("--since", help="date_found >= YYYY-MM-DD")
    l.add_argument("--source", help="source slug, e.g. linkedin")
    l.add_argument("--company", help="substring match on company name (case-insensitive)")
    l.set_defaults(func=cmd_list)

    sst = sub.add_parser("stats", help="Aggregate stats: funnel %%, per-source ROI, score averages, outcomes.")
    sst.add_argument("--since", help="date_found >= YYYY-MM-DD")
    sst.add_argument("--source", help="source slug, e.g. linkedin")
    sst.add_argument("--status", action="append", choices=STATUSES, help="Repeatable.")
    sst.add_argument("--priority", choices=PRIORITIES)
    sst.set_defaults(func=cmd_stats)

    n = sub.add_parser("next-id", help="Print the next free job_id for a source slug.")
    n.add_argument("source_slug")
    n.set_defaults(func=cmd_next_id)

    u = sub.add_parser("urls", help="Print all known URLs (incl. discarded) for dedupe: url<TAB>job_id<TAB>status")
    u.add_argument("--check", nargs="+", metavar="URL",
                   help="Instead of dumping all URLs, test these ones. Prints "
                        "url<TAB>KNOWN|NEW<TAB>job_id<TAB>status per probe, matched "
                        "after normalising scheme/www/query/trailing-slash and the "
                        "LinkedIn locale prefix. Always exits 0 - this is a query, "
                        "not a gate.")
    u.set_defaults(func=cmd_urls)

    lg = sub.add_parser("log", help="Append an event to the run log.")
    lg.add_argument("--run-id", required=True)
    lg.add_argument("--command", dest="command_name", required=True,
                    help="hunt | prepare | track | optimise | apply | brief | setup | other")
    lg.add_argument("--job-id")
    lg.add_argument("--action", required=True)
    lg.add_argument("--detail", help="JSON string")
    lg.set_defaults(func=cmd_log)

    d = sub.add_parser("dashboard", help="Markdown funnel + actionable lists.")
    d.set_defaults(func=cmd_dashboard)

    e = sub.add_parser("export-csv", help="Lossless, diff-friendly dump of all tables to CSV + manifest.json (the record of record).")
    e.add_argument("--out", help="Output dir (default: <workspace>/state/backup).")
    e.set_defaults(func=cmd_export_csv)

    ic = sub.add_parser("import-csv", help="Rebuild the database from CSVs (moves any existing DB aside first).")
    ic.add_argument("--dir", help="CSV dir (default: <workspace>/state/backup).")
    ic.set_defaults(func=cmd_import_csv)

    vc = sub.add_parser("verify-csv", help="Compare the live DB against the CSVs; exit 1 on any mismatch.")
    vc.add_argument("--dir", help="CSV dir (default: <workspace>/state/backup).")
    vc.set_defaults(func=cmd_verify_csv)
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except DbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
