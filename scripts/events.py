#!/usr/bin/env python3
"""events.py — the registry of event actions the pipeline logs.

`db.py log` checks every event against this table. An unknown action, or a
known one missing a required detail key, prints a warning and is still
logged: history written before the registry existed must never become
unloggable, and an agent mid-run must never be stopped by a telemetry typo.
`db.py log --strict` turns the warning into a refusal (the test suite and new
command text use it).

The registry is what lets anything downstream — the local UI, /optimise,
/doctor — read `events` without guessing: a name means one thing, and the
detail keys a consumer relies on are declared here.

    python3 scripts/events.py            # print the registry
    python3 scripts/events.py --check    # audit the live events table
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# name -> (group, required detail keys, optional detail keys, description)
# `required` is kept deliberately short: only keys a consumer cannot work
# without. Everything else stays optional so the agent's run reports can grow.
ACTIONS: dict[str, tuple[str, tuple, tuple, str]] = {
    # run lifecycle -------------------------------------------------------
    "run_start": ("run", (), ("selection", "target_count", "max_age_days", "mode",
                              "source", "intensity", "config_rev"),
                  "A command run began. Pairs with exactly one run_end."),
    "run_end": ("run", (), ("status", "reason", "found", "shortlisted", "discarded",
                            "skipped", "failed", "prepared", "checked", "changed"),
                "A command run finished. status: complete (default) | partial | aborted | starved."),
    "run_complete": ("run", (), (), "Legacy synonym of run_end (older /optimise runs)."),
    "halted": ("run", (), ("reason",), "The user chose `halt` at an audit failure."),
    "noop": ("run", (), ("reason",), "A run that had nothing to do."),
    # lifecycle (written by db.py itself) ---------------------------------
    "status_change": ("lifecycle", ("from", "to"), ("via", "outcome", "date_applied",
                                                    "response_date", "follow_up_date",
                                                    "applied_via", "rejection_reason"),
                      "A validated lifecycle transition."),
    "forced_transition": ("lifecycle", ("from", "to"), (),
                          "A transition outside the matrix, taken with --force."),
    "stage_added": ("lifecycle", ("seq", "kind"), ("result",), "A stage-ledger row was recorded."),
    "stage_resolved": ("lifecycle", ("seq", "to"), ("from",), "A stage-ledger row was settled."),
    "user_update": ("lifecycle", (), ("said", "change"), "/track recorded something the user said."),
    "auto_reconcile": ("lifecycle", (), ("signal", "change"),
                       "Mail reconciliation applied an unambiguous signal."),
    "application_submitted": ("lifecycle", (), ("via", "fields"),
                              "/apply recorded a submission the user confirmed."),
    "follow_up_sent": ("lifecycle", (), ("channel",), "A warm follow-up went out."),
    "follow_up_generated": ("lifecycle", (), (), "Legacy: /prepare drafted a follow-up."),
    # sourcing ------------------------------------------------------------
    "job_processed": ("hunt", (), ("portal", "recommendation", "originated", "questions",
                                   "duration_s"), "A posting was extracted, scored and recorded."),
    "job_skipped": ("hunt", (), ("reason", "url", "company"), "A posting was skipped before extraction."),
    "job_failed": ("hunt", (), ("url", "error", "reason"), "Extraction or scoring failed."),
    "job_scored": ("hunt", (), (), "Legacy (/brief): a posting was scored."),
    "job_originated": ("hunt", (), (), "Legacy (/brief): an employer URL was found."),
    "browser_probe": ("hunt", (), ("ok", "adapter", "latency_s", "error"),
                      "The browser adapter was probed at run start."),
    "portal_probe": ("hunt", (), ("portal", "ok", "reason"), "One board was probed."),
    "portal_swept": ("hunt", (), ("portal", "seen", "new"), "One board was swept."),
    "adaptive_intake": ("hunt", (), ("fit_bar", "target_count"), "/hunt raised its bar under a deep shortlist."),
    "questions_captured": ("hunt", (), ("count",), "Application-form questions were captured."),
    "questions_unknown": ("hunt", (), (), "The form's questions could not be read."),
    "questions_saved": ("prepare", (), ("count",), "Application-form questions were saved."),
    # preparation ---------------------------------------------------------
    "job_prepared": ("prepare", (), ("folder", "ats_det", "ats_llm", "iterations", "audit",
                                     "duration_s", "variant_id"),
                     "An application folder reached `ready`."),
    "application_answers_drafted": ("prepare", (), ("count",), "Form answers were drafted."),
    "asset_generated": ("prepare", (), (), "Legacy (migration): an asset existed before telemetry."),
    "asset_recorded": ("prepare", ("kind", "variant_id"), ("text_hash", "src_count"),
                       "db.py asset record fingerprinted a generated asset."),
    # liveness + mail -----------------------------------------------------
    "job_checked": ("refresh", (), ("state", "evidence"), "A pre-application posting was checked."),
    "mail_scanned": ("mail", (), ("account", "messages", "matched"), "The mailbox was scanned."),
    "mail_probe": ("mail", (), ("ok", "adapter"), "The mail adapter was probed."),
    "mail_skipped": ("mail", (), ("reason",), "The mail phase was skipped."),
    "mail_reply_found": ("mail", (), (), "Legacy (/brief): a reply was found."),
    # optimisation + configuration ----------------------------------------
    "suggestion_added": ("optimise", ("id",), ("lens", "target"), "A suggestion entered the ledger."),
    "suggestion_decided": ("optimise", ("id", "status"), ("reason",), "A suggestion was decided."),
    "suggestion_applied": ("optimise", (), ("id", "target", "suggestion"), "An approved suggestion was applied."),
    "suggestion_rejected": ("optimise", (), ("id", "target", "suggestion"), "A suggestion was rejected."),
    "suggestion_deferred": ("optimise", (), ("id", "suggestion"), "A suggestion was deferred."),
    "suggestion_filed_upstream": ("optimise", (), ("issue", "title"), "An engine finding was filed upstream."),
    "asset_incorporation": ("optimise", (), (), "Evidence was incorporated into an asset library."),
    "config_changed": ("config", ("file", "key", "reason"), ("from", "to", "suggestion",
                                                              "rev_before", "rev_after"),
                       "config.py changed one setting, with a reason."),
    "first_run_criteria_loosened": ("setup", (), ("change",), "/setup loosened criteria for a first result."),
    # agent runs started from the local UI ---------------------------------
    "agent_run_started": ("ui", ("agent", "command"), ("arg", "turn"),
                          "The local UI started a command in Claude Code or Codex (turn > 1: the user replied)."),
    "agent_run_finished": ("ui", ("agent", "command", "status"), ("exit_code", "cost_usd", "duration_s",
                                                                  "turn", "asked", "denied"),
                           "A turn of a UI-started agent run ended: succeeded | failed | stopped."),
    "agent_permission_changed": ("ui", ("capability", "mode"), ("rules",),
                                 "The user changed what UI-started agent runs may do without asking."),
    # recurring names from runs before the registry — kept so history reads
    # clean; new runs should use the names above (/doctor lists one-offs)
    "question_escalated": ("legacy", (), (), "Legacy: /apply escalated a form question to the user."),
    "audit_disposition": ("legacy", (), (), "Legacy: the user's fix/bypass/halt decision on an audit failure."),
    "mail_reconcile": ("legacy", (), (), "Legacy: an early name for mail reconciliation."),
    "suggestion_raised": ("legacy", (), (), "Legacy: a run raised a pending suggestion."),
    "tier2_probe": ("legacy", (), (), "Legacy: a tier-2 board was probed."),
    "watchlist_sweep": ("legacy", (), (), "Legacy: the company watchlist was swept."),
    "verify_noop": ("legacy", (), (), "Legacy: a verification pass found nothing to do."),
    # knowledge -----------------------------------------------------------
    "knowledge_proposed": ("knowledge", ("id", "op"), ("target_id", "by"),
                           "A knowledge change entered the inbox."),
    "knowledge_decided": ("knowledge", ("id", "decision"), ("op", "target_id"),
                          "A knowledge inbox item was accepted or rejected."),
}

GROUPS = sorted({v[0] for v in ACTIONS.values()})


def check(action: str, detail: str | None) -> list[str]:
    """Problems with one event, as human-readable strings (empty = clean).
    Never raises: the caller decides whether a problem is a warning or a
    refusal."""
    spec = ACTIONS.get(action)
    if spec is None:
        return [f"unknown event action `{action}` (not in scripts/events.py)"]
    required = spec[1]
    if not required:
        return []
    try:
        parsed = json.loads(detail) if detail else {}
    except json.JSONDecodeError:
        return []  # db.py reports malformed JSON itself
    if not isinstance(parsed, dict):
        return [f"`{action}` detail must be a JSON object"]
    missing = [k for k in required if k not in parsed]
    return [f"`{action}` detail is missing {', '.join(missing)}"] if missing else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="Count events in the live DB whose action is not registered.")
    parser.add_argument("--json", action="store_true", help="Print the registry as JSON.")
    args = parser.parse_args()
    if args.check:
        import sqlite3

        import paths
        db = paths.state_db()
        if not db.exists():
            print("No pipeline DB yet.")
            return 0
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute("SELECT action, COUNT(*) FROM events GROUP BY action").fetchall()
        unknown = [(a, n) for a, n in rows if a not in ACTIONS]
        for a, n in sorted(unknown, key=lambda x: -x[1]):
            print(f"unregistered  {a:<32} {n}")
        print(f"{len(rows) - len(unknown)}/{len(rows)} distinct actions registered.")
        return 0
    if args.json:
        print(json.dumps({k: {"group": v[0], "required": list(v[1]), "optional": list(v[2]),
                              "description": v[3]} for k, v in ACTIONS.items()}, indent=2))
        return 0
    for group in GROUPS:
        print(f"## {group}")
        for name, (g, req, _opt, desc) in ACTIONS.items():
            if g == group:
                req_s = f"  [requires {', '.join(req)}]" if req else ""
                print(f"  {name:<30} {desc}{req_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
