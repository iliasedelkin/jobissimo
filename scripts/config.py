#!/usr/bin/env python3
"""config.py — read and change one config setting, with a reason, traceably.

The config files are hand-readable YAML in the small subset packs.py parses.
This script changes exactly one *existing* setting per call — a scalar or an
inline list — rewriting only that line's value and keeping its comment and
every other byte of the file. It refuses anything it cannot change safely
(a missing key, a nested block, a multi-line list): those edits stay with the
agent, shown to the user as a diff.

Every change needs a reason and is logged as a `config_changed` event through
db.py, with the config revision (content hash) before and after — so every
pipeline change has a why, and analytics can split results by config version.

    python3 scripts/config.py get pipeline thresholds.ats_min_score
    python3 scripts/config.py set pipeline thresholds.ats_min_score 78 \\
        --reason "three sub-75 CVs got no response"
    python3 scripts/config.py rev                       # current config revision
    python3 scripts/config.py apply-suggestion OPT-20300115-2

Files: pipeline, targets, boards, languages, capabilities (in the workspace
config dir). Guardrails are engine, never config (AGENTS.md invariant 7):
nothing here can weaken the audit or enable autonomous submission.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402
from setup_check import content_hash  # noqa: E402

FILES = ("pipeline", "targets", "boards", "languages", "capabilities")
SCRIPTS = Path(__file__).resolve().parent


class ConfigError(RuntimeError):
    pass


def config_file(name: str) -> Path:
    if name not in FILES:
        raise ConfigError(f"Unknown config file `{name}`. Allowed: {', '.join(FILES)}")
    return paths.config_dir() / f"{name}.yaml"


def revision() -> str:
    d = paths.config_dir()
    return content_hash(*(d / f"{n}.yaml" for n in FILES))


def get(name: str, key: str):
    node = packs.load_yaml(config_file(name))
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"`{key}` is not set in config/{name}.yaml.")
        node = node[part]
    return node


def get_any(*parts: str):
    """`get FILE KEY`, or `get KEY` searched across the config files — the
    form an agent reaches for first."""
    if len(parts) == 2:
        if parts[0] not in FILES:
            raise ConfigError(f"Unknown config file `{parts[0]}` (one of: {', '.join(FILES)}).")
        return get(*parts)
    if len(parts) != 1:
        raise ConfigError("Usage: get [FILE] KEY")
    for name in FILES:
        if config_file(name).exists():
            try:
                return get(name, parts[0])
            except ConfigError:
                continue
    raise ConfigError(f"`{parts[0]}` is not set in any of config/{{{','.join(FILES)}}}.yaml.")


def _locate(lines: list, key: str) -> int:
    """Index of the line holding `key` (dotted path) with an inline value."""
    want = key.split(".")
    stack: list = []  # (indent, key)
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("- "):
            continue
        m = re.match(r"^( *)([^:#][^:]*?):(?:\s+(.*))?$", raw.rstrip("\n"))
        if not m:
            continue
        indent, k, val = len(m.group(1)), m.group(2).strip().strip('"'), (m.group(3) or "")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = [s[1] for s in stack] + [k]
        if path == want:
            if not val.strip() or val.strip().startswith("#"):
                raise ConfigError(f"`{key}` is a block, not a single setting — "
                                  "ask the agent to edit it.")
            v = val.strip()
            if v[0] in "[{" and v.count(v[0]) > v.count("]" if v[0] == "[" else "}"):
                raise ConfigError(f"`{key}` wraps across lines — ask the agent to edit it.")
            return i
        if not val.strip() or val.strip().startswith("#"):
            stack.append((indent, k))
    raise ConfigError(f"`{key}` is not present in the file — config.py only changes "
                      "existing settings; ask the agent to add it.")


def _fmt_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if s == "" or re.search(r"[:#,\[\]{}\"']|^\s|\s$", s) \
            or packs._scalar(s) != s:  # would re-read as a number/bool/null
        return '"' + s.replace('"', "'") + '"'
    return s


def format_value(v) -> str:
    if isinstance(v, dict):
        raise ConfigError("Mappings cannot be set with config.py — ask the agent.")
    if isinstance(v, list):
        if any(isinstance(x, (list, dict)) for x in v):
            raise ConfigError("Only flat lists can be set with config.py.")
        return "[" + ", ".join(_fmt_scalar(x) for x in v) + "]"
    return _fmt_scalar(v)


def _split_comment(value_part: str) -> tuple:
    """(value, trailing comment incl. leading spaces) of the text after `key:`."""
    v = value_part
    if v.lstrip().startswith(("[", "{")):
        close = "]" if v.lstrip()[0] == "[" else "}"
        end = v.rfind(close)
        return v[:end + 1], v[end + 1:]
    m = re.search(r"\s+#", v)
    return (v[:m.start()], v[m.start():]) if m else (v, "")


def parse_cli_value(raw: str):
    """A CLI value read the way the config parser would read it."""
    s = raw.strip()
    if s.startswith("[") and s.endswith("]"):
        return packs._inline_list(s)
    return packs._scalar(s)


def set_value(name: str, key: str, value, reason: str, suggestion: str | None = None,
              run_id: str | None = None, dry_run: bool = False) -> dict:
    if not reason or not reason.strip():
        raise ConfigError("--reason is required: every pipeline change records why.")
    path = config_file(name)
    if not path.exists():
        raise ConfigError(f"config/{name}.yaml does not exist in this workspace "
                          "(it is still on the shipped example) — run /setup first.")
    old = get(name, key)
    if isinstance(old, dict):
        raise ConfigError(f"`{key}` is a block, not a single setting — ask the agent.")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    i = _locate(lines, key)
    raw = lines[i]
    eol = "\n" if raw.endswith("\n") else ""
    head, _, rest = raw.rstrip("\n").partition(":")
    _, comment = _split_comment(rest)
    new_line = f"{head}: {format_value(value)}{comment}{eol}"
    new_text = "".join(lines[:i]) + new_line + "".join(lines[i + 1:])
    reread = packs.parse_simple_yaml(new_text)
    node = reread
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if node != value:
        raise ConfigError(f"Refusing: `{key}` would read back as {node!r}, not {value!r}.")
    change = {"file": f"config/{name}.yaml", "key": key, "from": old, "to": value,
              "reason": reason.strip(), "suggestion": suggestion}
    if dry_run or old == value:
        change["unchanged"] = old == value
        return change
    rev_before = revision()
    path.write_text(new_text, encoding="utf-8")
    change["rev_before"], change["rev_after"] = rev_before, revision()
    log = subprocess.run(
        [sys.executable, str(SCRIPTS / "db.py"), "log", "--run-id", run_id or "config",
         "--command", "config", "--action", "config_changed",
         "--detail", json.dumps({k: v for k, v in change.items() if v is not None})],
        capture_output=True, text=True)
    if log.returncode != 0:
        path.write_text(text, encoding="utf-8")  # no untraced change
        raise ConfigError(f"Could not log the change, reverted: {log.stderr.strip()}")
    return change


def apply_suggestion(sid: str) -> list:
    """Apply an *approved* suggestion's structured `set` ops, then mark it
    applied. Prose-only suggestions are applied by the agent, not here."""
    db = paths.state_db()
    if not db.exists():
        raise ConfigError("No pipeline DB.")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM suggestions WHERE id=?", (sid,)).fetchone()
    conn.close()
    if row is None:
        raise ConfigError(f"Unknown suggestion `{sid}`.")
    if row["status"] != "approved":
        raise ConfigError(f"`{sid}` is `{row['status']}` — only an approved suggestion is applied.")
    ops = json.loads(row["ops"] or "[]")
    if not ops:
        raise ConfigError(f"`{sid}` has no structured ops — the agent applies it.")
    for op in ops:  # check every op first, so a suggestion applies whole or not at all
        set_value(op["file"], op["key"], op["to"], f"{sid}: {row['title']}", sid, dry_run=True)
    changes = [set_value(op["file"], op["key"], op["to"], f"{sid}: {row['title']}", sid)
               for op in ops]
    done = subprocess.run([sys.executable, str(SCRIPTS / "db.py"), "suggestion", "decide", sid,
                           "--status", "applied"], capture_output=True, text=True)
    if done.returncode != 0:
        raise ConfigError(f"Applied, but could not mark {sid} applied: {done.stderr.strip()}")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="Print one setting as JSON: `get pipeline thresholds.x`, "
                       "or `get thresholds.x` to find the file that sets it.")
    g.add_argument("parts", nargs="+", metavar="[FILE] KEY",
                   help=f"Optional file ({', '.join(FILES)}), then a dotted path, "
                        "e.g. thresholds.ats_min_score")
    s = sub.add_parser("set", help="Change one existing setting (scalar or inline list).")
    s.add_argument("file", choices=FILES)
    s.add_argument("key")
    s.add_argument("value", nargs="?", help="New value, read like YAML: 78, true, [a, b], text.")
    s.add_argument("--json-value", help="New value as JSON instead (exact types).")
    s.add_argument("--reason", required=True, help="Why — recorded with the change.")
    s.add_argument("--suggestion", help="The suggestion id this change implements.")
    s.add_argument("--run-id")
    s.add_argument("--dry-run", action="store_true", help="Validate and show; write nothing.")
    sub.add_parser("rev", help="Print the current config revision (content hash).")
    a = sub.add_parser("apply-suggestion", help="Apply an approved suggestion's set ops.")
    a.add_argument("id")
    args = parser.parse_args()
    try:
        if args.cmd == "get":
            print(json.dumps(get_any(*args.parts)))
        elif args.cmd == "rev":
            print(revision())
        elif args.cmd == "set":
            if (args.value is None) == (args.json_value is None):
                raise ConfigError("Pass exactly one of VALUE or --json-value.")
            value = json.loads(args.json_value) if args.json_value is not None \
                else parse_cli_value(args.value)
            ch = set_value(args.file, args.key, value, args.reason, args.suggestion,
                           args.run_id, args.dry_run)
            verb = "unchanged" if ch.get("unchanged") else ("would set" if args.dry_run else "set")
            print(f"{ch['file']} {ch['key']}: {ch['from']!r} -> {ch['to']!r} ({verb})")
        elif args.cmd == "apply-suggestion":
            for ch in apply_suggestion(args.id):
                print(f"{ch['file']} {ch['key']}: {ch['from']!r} -> {ch['to']!r}")
            print(f"{args.id}: applied")
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
