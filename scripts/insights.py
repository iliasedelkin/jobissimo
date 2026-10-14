#!/usr/bin/env python3
"""insights.py — deterministic diagnostics: where the search is leaking, and
which lever moves it.

Every insight names its evidence (the counts it was computed from) and one
lever (a setting or a command). Nothing is shown unless the sample is big
enough to mean something: rates carry a Wilson 95% interval, and a comparison
only counts when the intervals do not overlap. No LLM, no network — the same
input always yields the same list.

    python3 scripts/insights.py            # print insights for this workspace
    python3 scripts/insights.py --json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_N = 8  # smallest group a rate is reported for


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """(rate, low, high) — Wilson score interval; (None, None, None) at n=0."""
    if n <= 0:
        return None, None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def rate_row(key, k: int, n: int, **extra) -> dict:
    r, lo, hi = wilson(k, n)
    return {"key": key, "n": n, "k": k, "rate": r, "low": lo, "high": hi, **extra}


def _pct(x) -> str:
    return "–" if x is None else f"{round(100 * x)}%"


def diagnose(a: dict, o: dict) -> list:
    """Insights from readmodel.analytics() (`a`) and readmodel.overview() (`o`)."""
    out = []
    f = a["funnel"]
    th = o.get("thresholds", {})

    # 1. sending is the bottleneck: prepared work is waiting
    ready = o["queue"]["ready"]
    sla = th.get("velocity_sla_days") or 5
    if ready["count"] and (ready["count"] >= (th.get("ready_wip_cap") or 8)
                           or (ready["oldest_days"] or 0) > 2 * sla):
        out.append({
            "id": "sending-bottleneck", "severity": "high", "area": "volume",
            "title": "Prepared applications are waiting to be sent",
            "detail": f"{ready['count']} ready to apply; the oldest was found "
                      f"{ready['oldest_days']} days ago. Postings close — send before preparing more.",
            "evidence": {"ready": ready["count"], "oldest_days": ready["oldest_days"],
                         "velocity_sla_days": sla},
            "lever": {"label": "Apply to the ready queue", "command": "/apply <job_id>"}})

    # 2. postings lost before sending
    lost = a.get("lost_before_sending") or {}
    if lost.get("n", 0) >= MIN_N and (lost.get("rate") or 0) >= 0.3:
        out.append({
            "id": "freshness", "severity": "medium", "area": "volume",
            "title": "Many shortlisted postings close before you apply",
            "detail": f"{lost['k']} of {lost['n']} recommended postings in the last 90 days ended "
                      f"`missed` ({_pct(lost['rate'])}). Prepare the newest first, or shortlist fewer.",
            "evidence": {"missed": lost["k"], "recommended": lost["n"]},
            "lever": {"label": "Lower prepare_per_cycle or raise adaptive_fit_bar",
                      "setting": "pipeline:thresholds.adaptive_fit_bar"}})

    # 3. responses that are screening rejections → CV / targeting
    if f["responded"] >= MIN_N:
        k, n = f["past_screen"], f["responded"]
        r, lo, hi = wilson(k, n)
        if hi is not None and hi < 0.4:
            out.append({
                "id": "screen-conversion", "severity": "high", "area": "cv",
                "title": "Most replies are screening rejections",
                "detail": f"Only {k} of {n} replies passed the CV screen ({_pct(r)}). The CV and "
                          "targeting, not the volume, are the lever: check seniority and positioning.",
                "evidence": {"past_screen": k, "responded": n, "rate": r},
                "lever": {"label": "Review CV variants in Analytics", "view": "analytics"}})

    # 4. does fit score predict replies?
    fb = {row["key"]: row for row in a["breakdowns"].get("fit_bucket", [])}
    below = [fb[k] for k in ("<3.5", "3.5–3.9") if k in fb]
    hi_b = fb.get("4.0+")
    lo_b = rate_row("below 4.0", sum(r["k"] for r in below), sum(r["n"] for r in below)) \
        if below else None
    if hi_b and lo_b and hi_b["n"] >= MIN_N and lo_b["n"] >= MIN_N:
        if hi_b["low"] > lo_b["high"]:
            out.append({
                "id": "fit-predicts", "severity": "low", "area": "targeting",
                "title": "High-fit applications get more replies",
                "detail": f"{_pct(hi_b['rate'])} reply rate at fit 4.0+ vs {_pct(lo_b['rate'])} below. "
                          "Spend preparation time on the top of the shortlist.",
                "evidence": {"high": hi_b, "low": lo_b},
                "lever": {"label": "adaptive_fit_bar", "setting": "pipeline:thresholds.adaptive_fit_bar"}})
        elif hi_b["high"] < lo_b["low"] or abs((hi_b["rate"] or 0) - (lo_b["rate"] or 0)) < 0.05:
            out.append({
                "id": "fit-flat", "severity": "low", "area": "targeting",
                "title": "Fit score is not predicting replies",
                "detail": f"{_pct(hi_b['rate'])} at fit 4.0+ vs {_pct(lo_b['rate'])} below. Freshness "
                          "and channel may matter more than a higher bar.",
                "evidence": {"high": hi_b, "low": lo_b},
                "lever": {"label": "Re-calibrate scoring with /optimise", "command": "/optimise"}})

    # 5. a channel clearly better or worse than the rest
    overall = wilson(f["responded"], f["applied"])
    for row in a["breakdowns"].get("source", []):
        if row["n"] < MIN_N or overall[0] is None:
            continue
        if row["low"] > overall[0] + 0.05:
            out.append({
                "id": f"channel-strong-{row['key']}", "severity": "low", "area": "sourcing",
                "title": f"{row['key']} replies more than average",
                "detail": f"{_pct(row['rate'])} reply rate over {row['n']} applications "
                          f"vs {_pct(overall[0])} overall. Give it more of the hunt.",
                "evidence": row, "lever": {"label": "Board tiers", "view": "pipeline"}})
        elif row["high"] < overall[0] - 0.05:
            out.append({
                "id": f"channel-weak-{row['key']}", "severity": "medium", "area": "sourcing",
                "title": f"{row['key']} replies less than average",
                "detail": f"{_pct(row['rate'])} reply rate over {row['n']} applications "
                          f"vs {_pct(overall[0])} overall.",
                "evidence": row, "lever": {"label": "Board tiers", "view": "pipeline"}})

    # 6. low volume while the shortlist is full
    recent = a["weekly"][-4:]
    per_week = sum(w["applied"] for w in recent) / max(1, len(recent))
    short = o["queue"]["shortlisted"]["count"]
    if recent and per_week < 2 and short >= 10:
        out.append({
            "id": "volume", "severity": "medium", "area": "volume",
            "title": "Few applications sent while the shortlist is full",
            "detail": f"{per_week:.1f} applications/week over the last 4 weeks with "
                      f"{short} shortlisted. Prepare and send before hunting more.",
            "evidence": {"per_week": per_week, "shortlisted": short},
            "lever": {"label": "Run /cycle (it prepares the most perishable)", "command": "/cycle"}})

    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda i: rank[i["severity"]])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    import readmodel
    items = readmodel.view("insights")
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    if not items:
        print("No insights: not enough data, or nothing stands out.")
    for i in items:
        print(f"[{i['severity']}] {i['title']}\n  {i['detail']}\n  lever: {i['lever']['label']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
