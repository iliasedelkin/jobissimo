#!/usr/bin/env python3
"""readmodel.py — the read-only model behind the local UI.

Pure functions from the workspace (pipeline DB, application folders,
knowledge, config) to JSON-ready dicts. It opens the DB read-only and never
writes anything: changes go through db.py / knowledge.py / config.py. The
funnel arithmetic is db.py's own (`funnel_metrics`, `job_progress`), so the
UI and `db.py dashboard` can never disagree.

    python3 scripts/readmodel.py overview
    python3 scripts/readmodel.py job <job_id>
    python3 scripts/readmodel.py analytics --since 2030-01-01

Views: overview, jobs, job, analytics, knowledge, gaps, pipeline,
suggestions, insights.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402  (pure helpers + constants; its connect() is never called here)
import insights as insights_mod  # noqa: E402
import knowledge as kb  # noqa: E402
import packs  # noqa: E402
import paths  # noqa: E402

PIPELINE_STAGES = [  # (key, label, statuses counted, the command that moves it on)
    ("found", "Found", ("found", "scored"), "/hunt"),
    ("shortlisted", "Shortlisted", ("shortlisted",), "/prepare"),
    ("ready", "Ready to send", ("generated", "ready"), "/apply"),
    ("applied", "Applied", ("applied",), "/track"),
    ("responded", "In process", ("responded", "offered"), "/track"),
    ("closed", "Closed", ("closed",), None),
]
PARKED = ("on_hold", "missed", "skipped", "discarded")

INVARIANTS = [
    ("Truth first", "CV content is selected and rephrased from your verified knowledge only. "
                    "A requirement you have no evidence for is never written into a CV."),
    ("Audit is a hard gate", "Every CV passes the truth audit before scoring or export. "
                             "A failure comes to you to fix, bypass (recorded) or halt."),
    ("You submit", "Jobissimo fills forms and stops before submit. Nothing is ever sent for you."),
    ("You approve changes", "Optimiser suggestions and knowledge proposals change nothing "
                            "until you accept them."),
    ("Local by default", "Your career data stays on this machine. Nothing is uploaded."),
]

# Settings the UI may show and change through config.py, in display order.
# (file, dotted key, label, type, help, options)
SETTINGS = [
    ("Targeting", [
        ("pipeline", "thresholds.adaptive_fit_bar", "Fit bar when the shortlist is deep", "number",
         "Minimum fit score (1–5) /hunt shortlists at once the shortlist passes its depth cap.", None),
        ("pipeline", "thresholds.shortlist_depth_cap", "Shortlist depth cap", "int",
         "Above this many shortlisted jobs, /hunt raises the bar and halves its target.", None),
        ("targets", "seniority.baseline_years", "Your years of experience", "int",
         "Seniority is matched on years required, not titles.", None),
        ("targets", "company_preferences.preferred_stages", "Preferred company stages", "list", "", None),
        ("targets", "company_preferences.avoid", "Avoid", "list", "", None),
    ]),
    ("Location and work", [
        ("targets", "geography.work_modes", "Work modes", "list", "",
         ["remote", "hybrid", "onsite"]),
        ("targets", "geography.remote_ok", "Remote roles", "bool", "", None),
        ("targets", "geography.relocation", "Relocation", "text", "e.g. no, EU with friction, anywhere", None),
        ("targets", "geography.max_commute_minutes", "Max commute (minutes)", "int",
         "Only used for onsite or hybrid roles.", None),
        ("targets", "employment.types", "Employment types", "list", "",
         ["full-time", "part-time", "contract", "freelance", "internship"]),
        ("targets", "employment.exclude", "Never consider", "list", "Hard rejects, skipped outright.",
         ["full-time", "part-time", "contract", "freelance", "internship"]),
    ]),
    ("Preparation and sending", [
        ("pipeline", "thresholds.ats_min_score", "ATS score to aim for", "int",
         "/prepare regenerates (max twice) below this. Truth always outranks it.", None),
        ("pipeline", "thresholds.ready_wip_cap", "Ready queue limit", "int",
         "At this many unsent applications, /cycle stops preparing new ones.", None),
        ("pipeline", "thresholds.prepare_per_cycle", "Prepared per cycle", "int", "", None),
        ("pipeline", "thresholds.velocity_sla_days", "Send within (days)", "int",
         "Target time from shortlist to sent for high-fit jobs.", None),
        ("pipeline", "thresholds.stale_pre_application_days", "Re-check postings older than (days)", "int",
         "/refresh verifies these are still open.", None),
    ]),
    ("Schedule and execution", [
        ("pipeline", "cycle.default_intensity", "Default /cycle intensity", "enum",
         "daily while hunting hard, weekly otherwise.", ["daily", "weekly"]),
        ("capabilities", "adapters.browse", "Browser", "enum", "How commands open web pages.",
         ["claude-in-chrome", "codex-chrome", "playwright", "webfetch", "manual"]),
        ("capabilities", "adapters.mail", "Mail", "enum", "Read-only mail reconciliation.",
         ["gmail-mcp", "imap", "none"]),
    ]),
]


# ---------------------------------------------------------------- plumbing

class Ctx:
    """One read-only snapshot of the DB for a request."""

    def __init__(self):
        self.conn = None
        path = paths.state_db()
        if path.exists():
            self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
        self.jobs = self.q("SELECT * FROM jobs")
        self.ledger = {}
        for r in self.q("SELECT * FROM stages ORDER BY job_id, seq"):
            self.ledger.setdefault(r["job_id"], []).append(r)
        self.today = date.today()

    def q(self, sql: str, params=()) -> list:
        if self.conn is None:
            return []
        try:
            return self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []  # a table this DB predates (opened read-only, never migrated)


def _d(row, key):
    """row[key] that tolerates a column an older DB lacks."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _days(a, b):
    a, b = _date(a), _date(b)
    return (b - a).days if a and b else None


def _week(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def _json(v):
    try:
        return json.loads(v) if v else None
    except json.JSONDecodeError:
        return None


def fit_bucket(x):
    if x is None:
        return None
    return "<3.5" if x < 3.5 else ("3.5–3.9" if x < 4.0 else "4.0+")


def ats_band(x):
    if x is None:
        return None
    return "<70" if x < 70 else ("70–79" if x < 80 else ("80–89" if x < 90 else "90+"))


def _assets(ctx) -> dict:
    out = {}
    for r in ctx.q("SELECT * FROM assets"):
        out.setdefault(r["job_id"], {})[r["kind"]] = dict(r)
    return out


def next_action(job, ledger_rows) -> str | None:
    s = job["status"]
    if s == "shortlisted":
        return f"/prepare {job['job_id']}"
    if s in ("generated", "ready"):
        return f"/apply {job['job_id']}"
    if s == "offered":
        return "Decide on the offer"
    if s in ("applied", "responded"):
        pending = [g for g in ledger_rows or [] if g["result"] == "pending"]
        if pending:
            return f"Awaiting {pending[-1]['kind']} decision"
        today = date.today()
        # same window as `db.py dashboard`: >14 days past due is noise, not an action
        if s == "applied" and job["follow_up_date"] and \
                (today - timedelta(days=14)).isoformat() <= job["follow_up_date"] <= today.isoformat():
            return "Follow-up due"
        return "Waiting for reply" if s == "applied" else "Record the next round"
    return None


def job_summary(job, ctx, assets=None) -> dict:
    ledger = ctx.ledger.get(job["job_id"], [])
    cv = (assets or {}).get(job["job_id"], {}).get("cv") or {}
    return {
        "job_id": job["job_id"], "company": job["company"], "title": job["title"],
        "status": job["status"], "outcome": job["outcome"], "source": job["source"],
        "location": job["location"], "remote": job["remote_flag"],
        "fit": job["fit_score"], "priority": job["priority"], "rec": job["apply_recommendation"],
        "role_cluster": job["role_cluster"], "language": job["jd_language"],
        "ats": job["ats_score_det"], "ats_band": ats_band(job["ats_score_det"]),
        "variant": cv.get("variant_id"),
        "date_found": job["date_found"], "date_applied": job["date_applied"],
        "response_date": job["response_date"],
        "age_days": _days(job["date_found"], ctx.today.isoformat()),
        "stages": [{"seq": g["seq"], "kind": g["kind"], "label": g["label"], "date": g["date"],
                    "result": g["result"], "party": g["party"]} for g in ledger],
        "progress": db.job_progress(job, ledger) if job["date_applied"] else None,
        "next": next_action(job, ledger),
        "url": job["original_url"] or job["url"],
        "seniority_level": _d(job, "seniority_level"), "country": _d(job, "country"),
        "industry": _d(job, "industry"),
    }


def _health() -> dict:
    import setup_check
    errors, warnings = [], []
    for fn in (setup_check.check_configs, setup_check.check_capabilities):
        try:
            fn(errors, warnings)
        except Exception as exc:  # health is advisory; never break a page
            warnings.append(f"{fn.__name__} could not run: {exc}")
    return {"errors": errors, "warnings": warnings}


def last_runs(ctx) -> dict:
    conn = ctx.conn
    if conn is None:
        return {"latest": [], "by_command": {}, "orphans": 0}
    runs = db.run_summaries(conn)
    by_cmd = {}
    for r in runs:
        by_cmd.setdefault(r["command"], r)
    return {"latest": runs[:8], "by_command": by_cmd,
            "orphans": sum(1 for r in runs if r["orphan"])}


# ---------------------------------------------------------------- views

def overview(ctx=None) -> dict:
    ctx = ctx or Ctx()
    jobs = ctx.jobs
    by_status = {}
    for r in jobs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    today = ctx.today
    monday = today - timedelta(days=today.weekday())
    applied_dates = [_date(r["date_applied"]) for r in jobs if r["date_applied"]]
    applied_dates = [d for d in applied_dates if d]

    def sent(since, until=None):
        return sum(1 for d in applied_dates if d >= since and (until is None or d < until))

    f = db.funnel_metrics(None, jobs, ctx.ledger)
    eight = today - timedelta(weeks=8)
    recent_apps = [r for r in jobs if r["date_applied"] and (_date(r["date_applied"]) or today) >= eight]
    resp_recent = sum(1 for r in recent_apps if r["response_date"])
    th = packs.thresholds()

    def queue(statuses):
        rows = [r for r in jobs if r["status"] in statuses]
        ages = [a for a in (_days(r["date_found"], today.isoformat()) for r in rows) if a is not None]
        return {"count": len(rows), "oldest_days": max(ages) if ages else None}

    assets = _assets(ctx)
    in_process = [job_summary(r, ctx, assets) for r in jobs if r["status"] in ("responded", "offered")]
    in_process.sort(key=lambda j: j["response_date"] or "", reverse=True)

    # what needs the user — ordered by urgency
    act = []
    for r in jobs:
        if r["status"] == "offered":
            act.append({"kind": "offer", "job_id": r["job_id"],
                        "title": f"Offer from {r['company']}",
                        "detail": r["title"], "cta": "Open"})
    due = [r for r in jobs if r["status"] == "applied" and r["follow_up_date"]
           and (today - timedelta(days=14)).isoformat() <= r["follow_up_date"] <= today.isoformat()]
    for r in sorted(due, key=lambda r: r["follow_up_date"]):
        act.append({"kind": "follow_up", "job_id": r["job_id"],
                    "title": f"Follow up with {r['company']}",
                    "detail": f"Applied {r['date_applied']}", "command": f"/track follow up {r['job_id']}"})
    rq = queue(("ready", "generated"))
    if rq["count"]:
        act.append({"kind": "ready", "title": f"{rq['count']} application{'s' if rq['count'] != 1 else ''} ready to send",
                    "detail": f"Oldest posting found {rq['oldest_days']} days ago" if rq["oldest_days"] is not None else "",
                    "view": "applications?status=ready", "command": "/apply <job_id>"})
    sq = queue(("shortlisted",))
    if sq["count"]:
        act.append({"kind": "shortlisted", "title": f"{sq['count']} shortlisted to prepare",
                    "detail": "Freshest postings first", "view": "applications?status=shortlisted",
                    "command": "/prepare"})
    inbox = [i for i in _inbox() if i["status"] == "pending"]
    if inbox:
        act.append({"kind": "inbox", "title": f"{len(inbox)} knowledge proposal{'s' if len(inbox) != 1 else ''} to review",
                    "detail": "Nothing changes until you accept", "view": "knowledge"})
    pending_sugg = [s for s in ctx.q("SELECT id FROM suggestions WHERE status='pending'")]
    if pending_sugg:
        act.append({"kind": "suggestions", "title": f"{len(pending_sugg)} pipeline suggestion{'s' if len(pending_sugg) != 1 else ''} to decide",
                    "detail": "From /optimise", "view": "pipeline"})
    runs = last_runs(ctx)

    recent = []
    for e in ctx.q("SELECT e.ts, e.job_id, e.detail, j.company, j.title FROM events e "
                   "JOIN jobs j ON j.job_id = e.job_id WHERE e.action='status_change' "
                   "ORDER BY e.id DESC LIMIT 200"):
        d = _json(e["detail"]) or {}
        if d.get("to") in ("applied", "responded", "offered", "closed"):
            recent.append({"ts": e["ts"], "job_id": e["job_id"], "company": e["company"],
                           "title": e["title"], "to": d.get("to"), "outcome": d.get("outcome")})
        if len(recent) >= 6:
            break

    return {
        "today": today.isoformat(),
        "has_data": bool(jobs),
        "totals": {"jobs": len(jobs), "by_status": by_status},
        "momentum": {"week_start": monday.isoformat(), "this_week": sent(monday),
                     "last_week": sent(monday - timedelta(days=7), monday),
                     "this_month": sent(today.replace(day=1))},
        "funnel": f,
        "rates": {"response_8w": insights_mod.rate_row("response", resp_recent, len(recent_apps)),
                  "past_screen": insights_mod.rate_row("past_screen", f["past_screen"], f["applied"]),
                  "interview": insights_mod.rate_row("interview", f["interview"], f["applied"])},
        "queue": {"ready": rq, "shortlisted": sq},
        "thresholds": th,
        "act_now": act,
        "in_process": in_process,
        "recent": recent,
        "runs": {"latest": runs["latest"][:5], "orphans": runs["orphans"]},
        "health": _health(),
        "benchmark": {"enabled": False,
                      "note": "Anonymous benchmarks are off. Nothing leaves this machine."},
    }


def jobs_view(ctx=None, status=None, source=None, since=None, q=None) -> dict:
    ctx = ctx or Ctx()
    assets = _assets(ctx)
    rows = ctx.jobs
    if status:
        wanted = set(status)
        if "ready" in wanted:
            wanted.add("generated")
        rows = [r for r in rows if r["status"] in wanted]
    if source:
        rows = [r for r in rows if r["source"] == source]
    if since:
        rows = [r for r in rows if (r["date_found"] or "") >= since]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["company"] or "").lower() or ql in (r["title"] or "").lower()
                or ql in r["job_id"].lower()]
    items = [job_summary(r, ctx, assets) for r in rows]
    order = {s: i for i, s in enumerate(["offered", "responded", "applied", "ready", "generated",
                                         "shortlisted", "scored", "found", "on_hold", "closed",
                                         "missed", "skipped", "discarded"])}
    items.sort(key=lambda j: (order.get(j["status"], 99), -(j["fit"] or 0),
                              j["date_found"] or ""), reverse=False)
    counts = {}
    for r in ctx.jobs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"items": items, "total": len(ctx.jobs), "counts": counts,
            "sources": sorted({r["source"] for r in ctx.jobs})}


def _folder_summary(folder: Path) -> dict:
    import audit
    em = audit.parse_evidence_map(folder.joinpath("evidence_map.md").read_text(encoding="utf-8")) \
        if (folder / "evidence_map.md").exists() else []
    counts = {"explicit_match": 0, "implicit_match": 0, "no_evidence": 0}
    for r in em:
        if r.get("status") in counts:
            counts[r["status"]] += 1
    draft = folder / "cv_draft.md"
    import assets as assets_mod
    srcs = assets_mod.trace_ids(draft.read_text(encoding="utf-8")) if draft.exists() else []
    files = sorted(p.name for p in folder.iterdir() if p.is_file())
    audit_text = (folder / "audit_log.md").read_text(encoding="utf-8") if (folder / "audit_log.md").exists() else ""
    m = re.search(r"\b(PASS|FAIL)\b", audit_text)
    return {"name": folder.name, "files": files, "evidence": counts,
            "requirements": [{k: r.get(k) for k in ("requirement_id", "jd_wording", "priority",
                                                    "status", "evidence_refs")}
                             for r in em if "parse_error" not in r],
            "src_ids": srcs, "audit": m.group(1) if m else None}


def _credentials() -> dict:
    """{EDU-/CERT- id: heading} from education_credentials.md — also valid CV traces."""
    path = paths.knowledge() / "education_credentials.md"
    if not path.exists():
        return {}
    return {m.group(1): m.group(2).strip() for m in
            re.finditer(r"^###\s+([A-Z]+-[A-Z0-9-]+)\s+—\s+(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)}


def job_view(job_id: str, ctx=None) -> dict | None:
    ctx = ctx or Ctx()
    row = next((r for r in ctx.jobs if r["job_id"] == job_id), None)
    if row is None:
        return None
    assets = _assets(ctx)
    out = job_summary(row, ctx, assets)
    out["fields"] = {k: row[k] for k in row.keys() if row[k] not in (None, "")}
    out["assets"] = list(assets.get(job_id, {}).values())
    for a in out["assets"]:
        a["src_ids"] = _json(a.get("src_ids")) or []
    timeline = []
    for e in ctx.q("SELECT ts, command, action, detail FROM events WHERE job_id=? ORDER BY id",
                   (job_id,)):
        timeline.append({"ts": e["ts"], "command": e["command"], "action": e["action"],
                         "detail": _json(e["detail"])})
    out["timeline"] = timeline
    out["folder"] = None
    if row["application_folder"]:
        folder = paths.resolve_folder(row["application_folder"])
        if folder.is_dir():
            out["folder"] = _folder_summary(folder)
    if out["folder"]:
        bullets = kb.all_bullets()
        creds = _credentials()
        cited = []
        for sid in out["folder"]["src_ids"]:
            if sid in bullets:
                b = bullets[sid]
                cited.append({"id": sid, "kind": "achievement", "status": b["meta"]["status"],
                              "text": (b["phrasings"] or b["facts"] or [""])[0]})
            elif sid in creds:
                cited.append({"id": sid, "kind": "credential", "status": "verified", "text": creds[sid]})
            else:
                cited.append({"id": sid, "kind": "unknown", "status": "unknown", "text": ""})
        out["folder"]["bullets"] = cited
    out["allowed_transitions"] = sorted(db.TRANSITIONS.get(row["status"], set()))
    return out


def analytics(ctx=None, since=None) -> dict:
    ctx = ctx or Ctx()
    rows = [r for r in ctx.jobs if not since or (r["date_found"] or "") >= since]
    f = db.funnel_metrics(None, rows, ctx.ledger)
    applied = [r for r in rows if r["date_applied"]]
    prog = {r["job_id"]: db.job_progress(r, ctx.ledger.get(r["job_id"])) for r in applied}
    assets = _assets(ctx)

    # weekly series, by the week a job was applied to / found
    today = ctx.today
    start = today - timedelta(weeks=25)
    start = start - timedelta(days=start.weekday())
    weeks = []
    w = start
    while w <= today:
        weeks.append(w.isoformat())
        w += timedelta(days=7)
    series = {wk: {"week": wk, "found": 0, "recommended": 0, "applied": 0, "responded": 0,
                   "past_screen": 0} for wk in weeks}
    for r in rows:
        d = _date(r["date_found"])
        if d and _week(d) in series:
            series[_week(d)]["found"] += 1
            if r["apply_recommendation"] in ("yes", "maybe"):
                series[_week(d)]["recommended"] += 1
        d = _date(r["date_applied"])
        if d and _week(d) in series:
            s = series[_week(d)]
            s["applied"] += 1
            s["responded"] += 1 if r["response_date"] else 0
            s["past_screen"] += 1 if prog[r["job_id"]]["past_screen"] else 0

    scored = [r for r in rows if r["fit_score"] is not None]
    recommended = [r for r in rows if r["apply_recommendation"] in ("yes", "maybe")]
    prepared = [r for r in rows if r["application_folder"] or r["ats_score_det"] is not None
                or r["date_applied"]]
    steps = [
        {"key": "found", "label": "Found", "n": len(rows)},
        {"key": "recommended", "label": "Shortlisted", "n": len(recommended)},
        {"key": "prepared", "label": "Prepared", "n": len(prepared)},
        {"key": "applied", "label": "Applied", "n": f["applied"]},
        {"key": "responded", "label": "Replied", "n": f["responded"]},
        {"key": "past_screen", "label": "Past screen", "n": f["past_screen"]},
        {"key": "offer", "label": "Offer", "n": f["offer"]},
    ]
    if f["interview"] and f["interview"] != f["past_screen"]:
        steps.insert(6, {"key": "interview", "label": "Interview", "n": f["interview"]})

    def breakdown(keyfn):
        groups = {}
        for r in applied:
            k = keyfn(r)
            if k in (None, ""):
                k = "unknown"
            g = groups.setdefault(k, {"n": 0, "responded": 0, "past_screen": 0})
            g["n"] += 1
            g["responded"] += 1 if r["response_date"] else 0
            g["past_screen"] += 1 if prog[r["job_id"]]["past_screen"] else 0
        out = [insights_mod.rate_row(k, g["responded"], g["n"], past_screen=g["past_screen"])
               for k, g in groups.items()]
        out.sort(key=lambda x: -x["n"])
        return out

    def variant_key(r):
        cv = assets.get(r["job_id"], {}).get("cv")
        return (r["role_cluster"] or "—") + (f" · {r['jd_language']}" if r["jd_language"] else "") \
            if cv is None else (r["role_cluster"] or "—") + f" · {cv.get('language') or r['jd_language'] or '?'}"

    breakdowns = {
        "source": breakdown(lambda r: r["source"]),
        "fit_bucket": breakdown(lambda r: fit_bucket(r["fit_score"])),
        "ats_band": breakdown(lambda r: ats_band(r["ats_score_det"])),
        "role_cluster": breakdown(lambda r: r["role_cluster"]),
        "language": breakdown(lambda r: r["jd_language"]),
        "positioning": breakdown(variant_key),
        "seniority_level": breakdown(lambda r: _d(r, "seniority_level")),
        "applied_via": breakdown(lambda r: r["applied_via"]),
    }

    ttr = [d for d in (_days(r["date_applied"], r["response_date"]) for r in applied
                       if r["response_date"]) if d is not None and d >= 0]
    buckets = [("0–3 days", 0, 3), ("4–7", 4, 7), ("8–14", 8, 14), ("15–30", 15, 30), ("31+", 31, 10 ** 6)]
    time_to_response = [{"label": lbl, "n": sum(1 for d in ttr if lo <= d <= hi)} for lbl, lo, hi in buckets]

    rounds = []
    gates = [g for r in applied for g in ctx.ledger.get(r["job_id"], []) if g["kind"] != "offer"]
    for kind in db.STAGE_KINDS:
        ks = [g for g in gates if g["kind"] == kind]
        if ks:
            rounds.append({"kind": kind, "reached": len(ks),
                           **{res: sum(1 for g in ks if g["result"] == res) for res in db.GATE_RESULTS}})

    cutoff = (today - timedelta(days=90)).isoformat()
    rec90 = [r for r in rows if r["apply_recommendation"] in ("yes", "maybe")
             and (r["date_found"] or "") >= cutoff]
    missed = sum(1 for r in rec90 if r["status"] == "missed")
    return {
        "since": since, "funnel": f, "steps": steps, "weekly": list(series.values()),
        "breakdowns": breakdowns, "time_to_response": time_to_response,
        "median_days_to_response": db._median(ttr), "rounds": rounds,
        "lost_before_sending": insights_mod.rate_row("missed", missed, len(rec90)),
        "scored": len(scored),
    }


def _inbox() -> list:
    try:
        return kb.load_inbox()
    except kb.KnowledgeError:
        return []


def knowledge_view(ctx=None) -> dict:
    ctx = ctx or Ctx()
    text = (paths.knowledge() / "master_experience.md")
    text = text.read_text(encoding="utf-8") if text.exists() else ""
    roles = kb.parse_master(text)
    usage = kb.usage_index([{"job_id": r["job_id"], "application_folder": r["application_folder"]}
                            for r in ctx.jobs])
    jobs = {r["job_id"]: r for r in ctx.jobs}
    applied = [r for r in ctx.jobs if r["date_applied"]]
    base = insights_mod.rate_row("all", sum(1 for r in applied if r["response_date"]), len(applied))
    stats = {"roles": len(roles), "bullets": 0, "deprecated": 0, "with_metric": 0,
             "contradictions": 0, "used": 0}
    for role in roles:
        for b in role["bullets"]:
            u = usage.get(b["id"], {"folders": [], "jobs": []})
            sent = [jobs[j] for j in u["jobs"] if j in jobs and jobs[j]["date_applied"]]
            dates = sorted(filter(None, (_date(jobs[j]["date_found"]) for j in u["jobs"] if j in jobs)))
            b["usage"] = {"applications": len(u["folders"]), "sent": len(sent),
                          "last_used": dates[-1].isoformat() if dates else None,
                          "replies": insights_mod.rate_row(b["id"], sum(1 for r in sent if r["response_date"]),
                                                           len(sent))}
            has_metric = bool(re.search(r"\d", " ".join(b["facts"])))
            b["has_metric"] = has_metric
            stats["bullets"] += 1
            stats["deprecated"] += b["meta"]["status"] == "deprecated"
            stats["with_metric"] += has_metric
            stats["contradictions"] += b["contradiction"]
            stats["used"] += bool(u["folders"])
    import competency_map
    skills_text = paths.knowledge() / "skills_inventory.md"
    skills = competency_map.parse_declared_skills(
        skills_text.read_text(encoding="utf-8")) if skills_text.exists() else {}
    unev_path = paths.knowledge() / "unevidenced.md"
    unevidenced = []
    if unev_path.exists():
        for line in unev_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"-\s+(.+?)\s+—\s+(.+)$", line.strip())
            if m and not m.group(1).startswith("{"):
                unevidenced.append({"name": m.group(1), "note": m.group(2)})
    import coverage
    try:
        queue = [e for e in coverage.read_queue() if e.get("status", "open") == "open"]
    except Exception:
        queue = []
    for e in queue:
        e["prompt"] = (e.get("prompt") or "").strip('"')
    return {
        "roles": roles, "stats": stats, "baseline": base,
        "skills": [{"name": k, **v} for k, v in skills.items()],
        "unevidenced": unevidenced,
        "inbox": [i for i in _inbox() if i["status"] == "pending"],
        "decided": [i for i in _inbox() if i["status"] != "pending"][-20:],
        "queue": sorted(queue, key=lambda e: -int(e.get("impact") or 0)),
    }


def gaps_view(ctx=None) -> dict:
    """Requirements jobs asked for that your knowledge has no evidence for —
    aggregated over every evidence map, most frequent first."""
    ctx = ctx or Ctx()
    import audit
    by_folder = {Path(r["application_folder"]).name: r for r in ctx.jobs if r["application_folder"]}
    terms = {}
    apps = paths.applications()
    folders = sorted(apps.iterdir()) if apps.is_dir() else []
    n_maps = 0
    for folder in folders:
        em = folder / "evidence_map.md"
        if not em.is_file():
            continue
        n_maps += 1
        job = by_folder.get(folder.name)
        for row in audit.parse_evidence_map(em.read_text(encoding="utf-8")):
            if row.get("status") != "no_evidence":
                continue
            key = row["jd_wording"].strip().lower()
            t = terms.setdefault(key, {"term": key, "count": 0, "must": 0, "jobs": [], "last_seen": None})
            t["count"] += 1
            t["must"] += row.get("priority") == "must"
            if job:
                t["jobs"].append({"job_id": job["job_id"], "company": job["company"]})
                seen = job["date_found"]
                if seen and (t["last_seen"] is None or seen > t["last_seen"]):
                    t["last_seen"] = seen
    items = sorted(terms.values(), key=lambda t: (-t["count"], -t["must"], t["term"]))
    return {"items": items, "evidence_maps": n_maps}


def pipeline_view(ctx=None) -> dict:
    ctx = ctx or Ctx()
    counts = {}
    for r in ctx.jobs:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    stages = [{"key": k, "label": lbl, "count": sum(counts.get(s, 0) for s in sts), "command": cmd}
              for k, lbl, sts, cmd in PIPELINE_STAGES]
    parked = {s: counts.get(s, 0) for s in PARKED}
    cfg_dir = paths.config_dir()
    groups = []
    for title, items in SETTINGS:
        out = []
        for file, key, label, typ, help_, options in items:
            exists = (cfg_dir / f"{file}.yaml").exists()
            node = packs.load_config(file)
            for part in key.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            out.append({"file": file, "key": key, "label": label, "type": typ, "help": help_,
                        "options": options, "value": node,
                        "editable": exists and node is not None and not isinstance(node, dict)})
        groups.append({"title": title, "items": out})
    targets = packs.load_config("targets").get("targets") or []
    cycle = packs.load_config("pipeline").get("cycle") or {}
    boards_cfg = packs.load_config("boards")
    if not any(k.startswith("tier") for k in boards_cfg):
        boards_cfg = packs.load_yaml(packs.pack_dir() / "boards.yaml")
    boards = []
    for tier in sorted(k for k in boards_cfg if str(k).startswith("tier")):
        for b in boards_cfg.get(tier) or []:
            if isinstance(b, dict):
                boards.append({"tier": tier, "slug": b.get("slug"), "name": b.get("name"),
                               "kind": b.get("kind")})
    sources = {}
    for r in ctx.jobs:
        s = sources.setdefault(r["source"], {"found": 0, "applied": 0, "responded": 0})
        s["found"] += 1
        s["applied"] += 1 if r["date_applied"] else 0
        s["responded"] += 1 if r["response_date"] else 0
    history = []
    for e in ctx.q("SELECT ts, detail FROM events WHERE action='config_changed' ORDER BY id DESC LIMIT 50"):
        d = _json(e["detail"]) or {}
        history.append({"ts": e["ts"], **d})
    expectation = None
    try:
        expectation = db.salary_expectation()
    except Exception:
        pass
    import config as config_mod
    return {
        "stages": stages, "parked": parked, "runs": last_runs(ctx), "settings": groups,
        "targets": targets, "cycle": cycle, "boards": boards,
        "sources": [{"slug": k, **v} for k, v in sorted(sources.items(), key=lambda kv: -kv[1]["found"])],
        "history": history, "invariants": [{"title": t, "text": x} for t, x in INVARIANTS],
        "pack": packs.active_pack(), "config_rev": config_mod.revision(),
        "salary_expectation": {"amount": expectation[0], "currency": expectation[1]} if expectation else None,
        "suggestions": suggestions_view(ctx),
    }


def suggestions_view(ctx=None) -> dict:
    ctx = ctx or Ctx()
    items = []
    for r in ctx.q("SELECT * FROM suggestions ORDER BY created_at DESC, id DESC"):
        d = dict(r)
        d["evidence"] = _json(d["evidence"])
        d["ops"] = _json(d["ops"]) or []
        items.append(d)
    pend_file = paths.reports() / "pending_suggestions.md"
    queued = 0
    if pend_file.exists():
        queued = len(re.findall(r"^Status:\s*pending", pend_file.read_text(encoding="utf-8"), re.MULTILINE))
    reports = sorted(paths.reports().glob("optimiser_*.md")) if paths.reports().is_dir() else []
    return {"items": items, "queued_from_runs": queued,
            "latest_report": reports[-1].name if reports else None}


def insights_view(ctx=None) -> list:
    ctx = ctx or Ctx()
    return insights_mod.diagnose(analytics(ctx), overview(ctx))


VIEWS = {
    "overview": lambda a: overview(),
    "jobs": lambda a: jobs_view(status=a.get("status"), source=a.get("source"),
                                since=a.get("since"), q=a.get("q")),
    "job": lambda a: job_view(a["job_id"]),
    "analytics": lambda a: analytics(since=a.get("since")),
    "knowledge": lambda a: knowledge_view(),
    "gaps": lambda a: gaps_view(),
    "pipeline": lambda a: pipeline_view(),
    "suggestions": lambda a: suggestions_view(),
    "insights": lambda a: insights_view(),
}


def view(name: str, **kwargs):
    return VIEWS[name](kwargs)


def _default(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, sqlite3.Row):
        return dict(o)
    raise TypeError(type(o).__name__)


def dumps(obj) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("view", choices=sorted(VIEWS))
    parser.add_argument("job_id", nargs="?", help="For `job`.")
    parser.add_argument("--status", action="append")
    parser.add_argument("--source")
    parser.add_argument("--since", help="YYYY-MM-DD (date found)")
    parser.add_argument("--q", help="Search company/title (jobs view)")
    args = parser.parse_args()
    if args.view == "job" and not args.job_id:
        parser.error("job needs a job_id")
    out = view(args.view, job_id=args.job_id, status=args.status, source=args.source,
               since=args.since, q=args.q)
    if out is None:
        print(f"ERROR: unknown job `{args.job_id}`", file=sys.stderr)
        return 1
    print(json.dumps(out, default=_default, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
