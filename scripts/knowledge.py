#!/usr/bin/env python3
"""knowledge.py — the knowledge base as records, and the only mechanical way
to change it.

`knowledge/master_experience.md` stays the source of truth (agents read it,
git diffs it). This script parses it into roles and bullets, and applies
changes to it *only* through an inbox:

    propose  → an item lands in knowledge/_inbox.json (status pending)
    decide   → the user accepts (the change is written) or rejects it

Nothing becomes part of the knowledge base without an explicit accept, and an
agent never accepts on the user's behalf. That is the truth guardrail in UI
form: the system may reorganise and rephrase verified evidence; it never
quietly adds a claim.

Each change edits only its own `#### <BULLET_ID>` block; every other byte of
the file is preserved. Lifecycle state lives in one hidden comment directly
under the bullet heading:

    #### ACME-PM-004
    <!-- kb: status=deprecated; on=2030-01-15; by=user; reason=superseded -->

No comment means `verified` (the bullet came from the user's own documents
and was confirmed at /setup). A `deprecated` bullet stays in the file so the
applications that cited it keep their history, but audit.py fails any new
CV that cites it. Merging never combines text or metrics: `mark_duplicate`
deprecates one bullet in favour of another.

Ops: add_bullet, add_phrasing, add_fact, deprecate, mark_duplicate, restore.

    python3 scripts/knowledge.py list                  # roles + bullets (JSON)
    python3 scripts/knowledge.py inbox                 # pending items
    python3 scripts/knowledge.py propose --op add_fact --target FERN-PM-003 \\
        --payload '{"fact": "Outcome: triage time down from 5 days to 2"}' --by user
    python3 scripts/knowledge.py decide INB-20300115-1 accept
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

OPS = ("add_bullet", "add_phrasing", "add_fact", "deprecate", "mark_duplicate", "restore")
BULLET_STATUSES = ("verified", "deprecated")
BULLET_ID_RE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")
KB_RE = re.compile(r"^<!--\s*kb:(.*?)-->\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^#### ([A-Z0-9-]+)\s*$", re.MULTILINE)
ROLE_RE = re.compile(r"^## ROLE:\s*(.+)$", re.MULTILINE)
# a bullet block ends at the next bullet, the next H2, or a horizontal rule
BLOCK_END_RE = re.compile(r"^(?:#### |## |---\s*$)", re.MULTILINE)


class KnowledgeError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def master_path() -> Path:
    return paths.knowledge() / "master_experience.md"


def inbox_path() -> Path:
    return paths.knowledge() / "_inbox.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- parsing

def parse_meta(block: str) -> dict:
    m = KB_RE.search(block)
    meta = {"status": "verified"}
    if not m:
        return meta
    for part in m.group(1).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            meta[k.strip()] = v.strip()
    if meta.get("status") not in BULLET_STATUSES:
        meta["status"] = "verified"
    return meta


def strip_meta(text: str) -> str:
    """The text without kb lifecycle comments — for numeric checks that must
    not mistake a deprecation date for a metric."""
    return KB_RE.sub("", text)


def _list_after(label: str, body: str) -> list:
    """Items of a `- **Label:**` list: indented `- ` lines until the next
    top-level field."""
    out, inside = [], False
    for line in body.splitlines():
        if re.match(rf"-\s*\*\*{re.escape(label)}:\*\*", line.strip()) and not line.startswith(" "):
            inside = True
            inline = line.split(":**", 1)[1].strip()
            if inline:
                out.append(inline)
            continue
        if inside:
            if re.match(r"\s+-\s", line):
                out.append(re.sub(r"^\s+-\s+", "", line).strip())
            elif line.strip() and not line.startswith(" "):
                inside = False
    return out


def bullet_spans(text: str) -> list:
    """[(bullet_id, start, end)] — character spans of each bullet block,
    from its `####` heading up to (not including) the next boundary."""
    spans = []
    for m in HEADING_RE.finditer(text):
        nxt = BLOCK_END_RE.search(text, m.end())
        spans.append((m.group(1), m.start(), nxt.start() if nxt else len(text)))
    return spans


def parse_master(text: str) -> list:
    """Roles with their header fields and bullets, in file order."""
    roles = []
    role_marks = list(ROLE_RE.finditer(text))
    spans = bullet_spans(text)
    for i, rm in enumerate(role_marks):
        start = rm.start()
        end = role_marks[i + 1].start() if i + 1 < len(role_marks) else len(text)
        header = rm.group(1).strip()
        role_id = header.split("—")[0].strip().split()[0]
        rest = header.split("—", 1)[1].strip() if "—" in header else ""
        company, _, title = rest.partition(",")
        block = text[start:end]
        first_bullet = HEADING_RE.search(block)
        head = block[:first_bullet.start()] if first_bullet else block
        fields = {}
        for fm in re.finditer(r"^- \*\*(.+?):\*\*\s*(.+)$", head, re.MULTILINE):
            fields[fm.group(1).strip()] = fm.group(2).strip()
        bullets = []
        for bid, bs, be in spans:
            if not (start <= bs < end):
                continue
            body = text[bs:be]
            prov = []
            for pm in re.finditer(r"<!--\s*from:([^>]+?)-->", body):
                prov += [p.strip() for p in pm.group(1).split(",") if p.strip()]
            tags_line = re.search(r"\*\*Tags:\*\*\s*(.+)", body)
            bullets.append({
                "id": bid,
                "role_id": role_id,
                "tags": [t.strip() for t in tags_line.group(1).split(",")] if tags_line else [],
                "facts": _list_after("Facts", body),
                "phrasings": [p.strip().strip('"“”') for p in _list_after("Phrasings", body)],
                "provenance": prov,
                "contradiction": "CONTRADICTION:" in body,
                "meta": parse_meta(body),
            })
        roles.append({"id": role_id, "company": company.strip() or fields.get("Company", ""),
                      "title": title.strip() or fields.get("Title (canonical)", ""),
                      "period": fields.get("Period", ""), "fields": fields,
                      "bullets": bullets})
    return roles


def all_bullets(text: str | None = None) -> dict:
    text = _read(master_path()) if text is None else text
    return {b["id"]: b for r in parse_master(text) for b in r["bullets"]}


def deprecated_ids(text: str | None = None) -> dict:
    """{bullet_id: meta} for every deprecated bullet."""
    return {bid: b["meta"] for bid, b in all_bullets(text).items()
            if b["meta"]["status"] == "deprecated"}


# ---------------------------------------------------------------- editing

def _clean(value: str) -> str:
    """Make a value safe inside the kb comment: no separators, no comment end."""
    return re.sub(r"\s+", " ", str(value).replace(";", ",").replace("--", "–")).strip()


def _set_meta(text: str, bullet_id: str, meta: dict | None) -> str:
    """Replace (or insert, or with None remove) the kb comment of one bullet."""
    span = next((s for s in bullet_spans(text) if s[0] == bullet_id), None)
    if span is None:
        raise KnowledgeError(f"Unknown bullet `{bullet_id}`.")
    _, bs, be = span
    block = text[bs:be]
    heading_end = block.index("\n") + 1 if "\n" in block else len(block)
    body = KB_RE.sub("", block[heading_end:], count=1)
    if body.startswith("\n") and KB_RE.search(block[heading_end:]):
        body = body[1:]  # the removed comment's own newline
    line = ""
    if meta:
        line = "<!-- kb: " + "; ".join(f"{k}={_clean(v)}" for k, v in meta.items()
                                       if v not in (None, "")) + " -->\n"
    return text[:bs] + block[:heading_end] + line + body + text[be:]


def _insert_list_item(text: str, bullet_id: str, label: str, item: str, prov: str) -> str:
    """Append `  - item` to a bullet's `- **Label:**` list and a provenance
    comment at the block end."""
    span = next((s for s in bullet_spans(text) if s[0] == bullet_id), None)
    if span is None:
        raise KnowledgeError(f"Unknown bullet `{bullet_id}`.")
    _, bs, be = span
    lines = text[bs:be].split("\n")
    idx = next((i for i, ln in enumerate(lines)
                if re.match(rf"-\s*\*\*{re.escape(label)}:\*\*", ln)), None)
    if idx is None:
        raise KnowledgeError(f"`{bullet_id}` has no **{label}:** list to extend.")
    j = idx + 1
    while j < len(lines) and re.match(r"\s+-\s", lines[j]):
        j += 1
    lines.insert(j, f"  - {item}")
    # provenance after the last non-blank line of the block
    k = len(lines)
    while k > 0 and not lines[k - 1].strip():
        k -= 1
    lines.insert(k, f"<!-- from:{prov} -->")
    return text[:bs] + "\n".join(lines) + text[be:]


def _next_bullet_id(text: str, role_id: str) -> str:
    n = 0
    for bid, _, _ in bullet_spans(text):
        if bid.startswith(role_id + "-"):
            tail = bid[len(role_id) + 1:]
            if tail.isdigit():
                n = max(n, int(tail))
    return f"{role_id}-{n + 1:03d}"


def _add_bullet(text: str, role_id: str, payload: dict, prov: str, meta: dict) -> tuple:
    marks = list(ROLE_RE.finditer(text))
    idx = next((i for i, m in enumerate(marks)
                if m.group(1).strip().split("—")[0].strip().split()[0] == role_id), None)
    if idx is None:
        raise KnowledgeError(f"Unknown role `{role_id}`.")
    role_end = marks[idx + 1].start() if idx + 1 < len(marks) else len(text)
    # insert after the role's last bullet block (before a trailing --- rule)
    spans = [s for s in bullet_spans(text) if marks[idx].start() <= s[1] < role_end]
    insert_at = spans[-1][2] if spans else role_end
    new_id = _next_bullet_id(text, role_id)
    facts = [f for f in payload.get("facts", []) if str(f).strip()]
    phrasings = [p for p in payload.get("phrasings", []) if str(p).strip()]
    if not facts:
        raise KnowledgeError("add_bullet needs at least one fact.")
    tags = ", ".join(t.strip() for t in payload.get("tags", []) if t.strip()) or "UNTAGGED"
    lines = [f"#### {new_id}",
             "<!-- kb: " + "; ".join(f"{k}={_clean(v)}" for k, v in meta.items() if v) + " -->",
             f"- **Tags:** {tags}", "- **Facts:**"]
    lines += [f"  - {str(f).strip()}" for f in facts]
    if phrasings:
        lines.append("- **Phrasings:**")
        lines += ['  - "' + str(p).strip().strip('"') + '"' for p in phrasings]
    lines.append(f"<!-- from:{prov} -->")
    block = "\n".join(lines) + "\n\n"
    before = text[:insert_at]
    if not before.endswith("\n\n"):
        block = ("\n" if before.endswith("\n") else "\n\n") + block
    return text[:insert_at] + block + text[insert_at:], new_id


def apply_item(text: str, item: dict, today: str) -> tuple:
    """Apply one accepted inbox item to the master text. Returns (text, id)."""
    op, target, payload = item["op"], item.get("target_id"), item.get("payload") or {}
    prov = f"USER#{item['id']}"
    accepted = {"status": "verified", "on": today, "by": "user", "inbox": item["id"]}
    bullets = all_bullets(text)
    if op != "add_bullet" and target not in bullets:
        raise KnowledgeError(f"Unknown bullet `{target}`.")
    if op == "add_bullet":
        return _add_bullet(text, payload.get("role_id") or target or "", payload, prov, accepted)
    if op == "add_phrasing":
        phr = str(payload.get("phrasing", "")).strip().strip('"')
        if not phr:
            raise KnowledgeError("add_phrasing needs payload.phrasing.")
        return _insert_list_item(text, target, "Phrasings", f'"{phr}"', prov), target
    if op == "add_fact":
        fact = str(payload.get("fact", "")).strip()
        if not fact:
            raise KnowledgeError("add_fact needs payload.fact.")
        return _insert_list_item(text, target, "Facts", fact, prov), target
    if op == "deprecate":
        return _set_meta(text, target, {"status": "deprecated", "on": today, "by": "user",
                                        "reason": payload.get("reason") or item.get("note"),
                                        "inbox": item["id"]}), target
    if op == "mark_duplicate":
        keep = payload.get("of")
        if keep not in bullets or keep == target:
            raise KnowledgeError("mark_duplicate needs payload.of: another existing bullet id.")
        return _set_meta(text, target, {"status": "deprecated", "on": today, "by": "user",
                                        "reason": f"duplicate of {keep}",
                                        "merged_into": keep, "inbox": item["id"]}), target
    if op == "restore":
        return _set_meta(text, target, None), target
    raise KnowledgeError(f"Unknown op `{op}`.")


# ---------------------------------------------------------------- inbox

def load_inbox() -> list:
    raw = _read(inbox_path())
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"{inbox_path()} is not valid JSON: {exc}")
    return data.get("items", []) if isinstance(data, dict) else []


def save_inbox(items: list) -> None:
    _atomic_write(inbox_path(), json.dumps(
        {"_about": "Knowledge inbox. Written by scripts/knowledge.py only. "
                   "Items change the knowledge base only when the user accepts them.",
         "items": items}, indent=2, ensure_ascii=False) + "\n")


def _next_inbox_id(items: list) -> str:
    stem = f"INB-{date.today().strftime('%Y%m%d')}-"
    n = max((int(i["id"][len(stem):]) for i in items
             if i["id"].startswith(stem) and i["id"][len(stem):].isdigit()), default=0)
    return f"{stem}{n + 1}"


def propose(op: str, target: str | None, payload: dict, by: str, note: str | None = None) -> dict:
    if op not in OPS:
        raise KnowledgeError(f"Unknown op `{op}`. Allowed: {', '.join(OPS)}")
    text = _read(master_path())
    bullets = all_bullets(text)
    if op == "add_bullet":
        role = payload.get("role_id") or target
        if role not in {r["id"] for r in parse_master(text)}:
            raise KnowledgeError(f"add_bullet needs an existing role id (payload.role_id), got `{role}`.")
        if not [f for f in payload.get("facts", []) if str(f).strip()]:
            raise KnowledgeError("add_bullet needs payload.facts (at least one).")
    elif target not in bullets:
        raise KnowledgeError(f"Unknown bullet `{target}`.")
    if op == "restore" and bullets[target]["meta"]["status"] != "deprecated":
        raise KnowledgeError(f"`{target}` is not deprecated.")
    if op in ("deprecate", "mark_duplicate") and bullets[target]["meta"]["status"] == "deprecated":
        raise KnowledgeError(f"`{target}` is already deprecated.")
    items = load_inbox()
    item = {"id": _next_inbox_id(items), "op": op, "target_id": target, "payload": payload,
            "note": note, "proposed_by": by, "proposed_at": now_iso(), "status": "pending"}
    items.append(item)
    save_inbox(items)
    return item


def decide(item_id: str, decision: str, reason: str | None = None,
           payload: dict | None = None) -> dict:
    if decision not in ("accept", "reject"):
        raise KnowledgeError("decision must be accept or reject.")
    items = load_inbox()
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        raise KnowledgeError(f"Unknown inbox item `{item_id}`.")
    if item["status"] != "pending":
        raise KnowledgeError(f"`{item_id}` is already {item['status']}.")
    if payload is not None:  # the user edited the proposal before accepting
        item["payload"] = payload
        item["edited"] = True
    if decision == "accept":
        text = _read(master_path())
        new_text, result_id = apply_item(text, item, date.today().isoformat())
        _atomic_write(master_path(), new_text)
        item["result_id"] = result_id
        item["status"] = "accepted"
    else:
        if not reason:
            raise KnowledgeError("--reason is required to reject (so it is not proposed again).")
        item["status"] = "rejected"
    item["decided_at"] = now_iso()
    item["reason"] = reason
    save_inbox(items)
    return item


# ---------------------------------------------------------------- usage

def usage_index(job_rows: list | None = None) -> dict:
    """{bullet_id: {"folders": [...], "jobs": [...]}} from the `src:` traces in
    every application's cv_draft.md. `job_rows` (dicts with job_id and
    application_folder) maps folders to jobs; without it, folders only."""
    import assets
    by_folder = {}
    for row in job_rows or []:
        if row.get("application_folder"):
            by_folder[Path(row["application_folder"]).name] = row["job_id"]
    out: dict = {}
    apps = paths.applications()
    if not apps.is_dir():
        return out
    for folder in sorted(apps.iterdir()):
        draft = folder / "cv_draft.md"
        if not draft.is_file():
            continue
        for sid in assets.trace_ids(draft.read_text(encoding="utf-8")):
            entry = out.setdefault(sid, {"folders": [], "jobs": []})
            entry["folders"].append(folder.name)
            if folder.name in by_folder:
                entry["jobs"].append(by_folder[folder.name])
    return out


# ---------------------------------------------------------------- CLI

def _json_arg(raw: str | None, name: str) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        raise KnowledgeError(f"{name} must be a JSON object.")
    if not isinstance(val, dict):
        raise KnowledgeError(f"{name} must be a JSON object.")
    return val


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="Roles and bullets with lifecycle state, as JSON.")
    sub.add_parser("index", help="Bullet usage across application folders, as JSON.")
    ib = sub.add_parser("inbox", help="Inbox items (default: pending), as JSON.")
    ib.add_argument("--all", action="store_true", help="Include decided items.")
    pp = sub.add_parser("propose", help="Add an item to the inbox (changes nothing yet).")
    pp.add_argument("--op", required=True, choices=OPS)
    pp.add_argument("--target", help="Bullet id (or role id for add_bullet).")
    pp.add_argument("--payload", help='JSON, e.g. {"fact": "..."} / {"phrasing": "..."} / '
                    '{"role_id": "...", "facts": [...], "phrasings": [...], "tags": [...]} / '
                    '{"reason": "..."} / {"of": "<bullet id>"}')
    pp.add_argument("--by", required=True, help="`user`, or the proposing run id.")
    pp.add_argument("--note", help="Why — shown to the user beside the proposal.")
    dc = sub.add_parser("decide", help="Accept (writes the change) or reject an inbox item. "
                        "Only on the user's explicit instruction.")
    dc.add_argument("id")
    dc.add_argument("decision", choices=("accept", "reject"))
    dc.add_argument("--reason", help="Required for reject.")
    dc.add_argument("--payload", help="Edited payload JSON to apply instead of the proposal.")
    args = parser.parse_args()
    try:
        if args.cmd == "list":
            print(json.dumps(parse_master(_read(master_path())), indent=2, ensure_ascii=False))
        elif args.cmd == "index":
            print(json.dumps(usage_index(), indent=2))
        elif args.cmd == "inbox":
            items = load_inbox()
            if not args.all:
                items = [i for i in items if i["status"] == "pending"]
            print(json.dumps(items, indent=2, ensure_ascii=False))
        elif args.cmd == "propose":
            item = propose(args.op, args.target, _json_arg(args.payload, "--payload"),
                           args.by, args.note)
            print(f"Proposed {item['id']}: {item['op']} {item['target_id'] or ''}".rstrip())
        elif args.cmd == "decide":
            payload = _json_arg(args.payload, "--payload") if args.payload else None
            item = decide(args.id, args.decision, args.reason, payload)
            extra = f" -> {item['result_id']}" if item.get("result_id") else ""
            print(f"{item['id']}: {item['status']}{extra}")
    except KnowledgeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
