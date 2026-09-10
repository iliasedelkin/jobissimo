#!/usr/bin/env python3
"""coverage.py — completeness ledger + profile strength score.

Reads the workspace knowledge base and applicant profile and reports what the
pipeline has to work with: roles found, bullets extracted, percentage carrying
a metric, skills evidenced vs claimed, identity fields filled vs missing, and
open queue items. Prints the ledger and a 0–100 profile strength score, and
appends any newly found gaps to knowledge/_queue.yaml (each with an estimated
impact and time to answer) so /enrich can surface them later.

The score is deliberately blunt — it exists to show movement, not to be
gamed:  roles>0 (10) + bullets>=3/role avg (10) + metric density (25) +
skills evidenced ratio (25) + identity completeness (20) + contradictions
resolved (10).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402

IDENTITY_FIELDS = ["full_name", "email", "phone", "location_city", "location_country"]
QUEUE_HEADER = """# Enrichment queue — gaps the pipeline keeps surfacing until answered.
# Written by coverage.py and /setup; consumed by /enrich (top items by impact).
# Each entry: id, kind, prompt (the question to ask), impact (1-5),
# est_minutes, status (open | answered | dismissed).
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _strip_comments(text: str) -> str:
    # provenance comments carry SRC-NNN ids whose digits would fool metric
    # detection — strip all HTML comments before looking for numbers
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse_bullets(master: str) -> list:
    """[(bullet_id, has_metric)]"""
    out = []
    for m in re.finditer(r"^#### ([A-Z0-9-]+)\s*\n(.*?)(?=^#### |^## |\Z)",
                         master, flags=re.MULTILINE | re.DOTALL):
        body = _strip_comments(m.group(2))
        out.append((m.group(1), bool(re.search(r"\d+(?:\.\d+)?%|\b\d+[xk]\b|\b\d+\b", body))))
    return out


def parse_skills(skills: str):
    """Claimed vs evidenced skills. The `## Languages` section lists spoken
    languages, which are legitimately evidence-free (audit.py treats them the
    same way) — they are not counted as claimed-but-unevidenced skills."""
    claimed, evidenced = [], []
    current, section = None, ""
    for line in skills.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue
        if section == "Languages":
            continue
        m = re.match(r"- \*\*(.+?)\*\*", line.strip())
        if m:
            current = m.group(1).strip()
            claimed.append(current)
            continue
        if current and re.match(r"-\s*Evidence:\s*\S", line.strip()) and "[confirm]" not in line:
            if current not in evidenced:
                evidenced.append(current)
    return claimed, evidenced


def read_queue() -> list:
    entries, current = [], None
    for line in read(paths.knowledge() / "_queue.yaml").splitlines():
        if line.startswith("- id:"):
            current = {"id": line.split(":", 1)[1].strip()}
            entries.append(current)
        elif current is not None and line.startswith("  ") and ":" in line:
            k, v = line.strip().split(":", 1)
            current[k.strip()] = v.strip()
    return entries


def write_queue(entries: list) -> None:
    lines = [QUEUE_HEADER]
    for e in entries:
        lines.append(f"- id: {e['id']}")
        for key in ("kind", "prompt", "impact", "est_minutes", "status"):
            if key in e:
                v = e[key]
                if key == "prompt":
                    v = '"' + str(v).strip('"').replace('"', "'") + '"'
                lines.append(f"  {key}: {v}")
    (paths.knowledge() / "_queue.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def queue_gap(entries: list, gap_id: str, kind: str, prompt: str,
              impact: int, minutes: int) -> bool:
    if any(e["id"] == gap_id for e in entries):
        return False
    entries.append({"id": gap_id, "kind": kind, "prompt": prompt,
                    "impact": str(impact), "est_minutes": str(minutes),
                    "status": "open"})
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-queue", action="store_true",
                        help="Report only; do not append gaps to knowledge/_queue.yaml.")
    args = parser.parse_args()

    master = read(paths.knowledge() / "master_experience.md")
    skills = read(paths.knowledge() / "skills_inventory.md")
    unevidenced = read(paths.knowledge() / "unevidenced.md")
    if not master:
        print(f"ERROR: {paths.knowledge() / 'master_experience.md'} not found — "
              "run /setup first.", file=sys.stderr)
        return 1

    roles = re.findall(r"^## ROLE:\s*(\S+)", master, flags=re.MULTILINE)
    bullets = parse_bullets(master)
    metric_bullets = [b for b, has in bullets if has]
    claimed, evidenced = parse_skills(skills)
    unev_count = len(re.findall(r"^- ", unevidenced, flags=re.MULTILINE))
    contradictions = len(re.findall(r"CONTRADICTION", master + skills, flags=re.IGNORECASE))

    profile = packs.load_yaml(paths.applicant_profile())
    identity = profile.get("identity") or {}
    filled = [f for f in IDENTITY_FIELDS if identity.get(f)]
    missing = [f for f in IDENTITY_FIELDS if not identity.get(f)]

    queue = read_queue()
    added = 0
    if not args.no_queue and paths.knowledge().exists():
        for b_id, has in bullets:
            if not has and queue_gap(queue, f"metric-{b_id}", "metric_rescue",
                                     f"Bullet {b_id} has no number. What changed, and by how much? "
                                     "('No number exists' is a valid answer and marks it qualitative.)",
                                     impact=3, minutes=2):
                added += 1
        # skills claimed in skills_inventory.md without an Evidence line, PLUS
        # skills parked in unevidenced.md (the highest-value enrichment target:
        # most CVs lose 20-30% of claimed skills here)
        unev_names = [re.split(r"\s+[—-]\s+", line.strip()[2:], 1)[0].strip()
                      for line in unevidenced.splitlines()
                      if line.strip().startswith("- ")]
        for skill in [s for s in claimed if s not in evidenced] + unev_names:
            if queue_gap(
                    queue, f"skill-{re.sub(r'[^a-z0-9]+', '-', skill.lower()).strip('-')}",
                    "skill_evidence",
                    f"Skill '{skill}' is claimed but cites no bullet. Which role/project proves it?",
                    impact=4, minutes=3):
                added += 1
        for f in missing:
            if queue_gap(queue, f"identity-{f}", "identity",
                         f"Identity field '{f}' is empty in applicant_profile.yaml.",
                         impact=5, minutes=1):
                added += 1
        write_queue(queue)

    open_items = [e for e in queue if e.get("status") == "open"]

    # ----- strength score -------------------------------------------------
    score = 0.0
    score += 10 if roles else 0
    avg_bullets = (len(bullets) / len(roles)) if roles else 0
    score += 10 * min(1.0, avg_bullets / 3)
    metric_ratio = (len(metric_bullets) / len(bullets)) if bullets else 0
    score += 25 * min(1.0, metric_ratio / 0.6)  # 60%+ metric-bearing = full credit
    ev_ratio = (len(evidenced) / len(claimed)) if claimed else 0
    score += 25 * ev_ratio
    score += 20 * (len(filled) / len(IDENTITY_FIELDS))
    score += 10 if contradictions == 0 else 0
    strength = round(score)

    print("# Completeness ledger\n")
    print(f"- Roles found:            {len(roles)}")
    print(f"- Bullets extracted:      {len(bullets)}"
          + (f"  (avg {avg_bullets:.1f}/role)" if roles else ""))
    print(f"- Bullets with a metric:  {len(metric_bullets)}/{len(bullets)}"
          + (f"  ({100 * metric_ratio:.0f}%)" if bullets else ""))
    print(f"- Skills evidenced:       {len(evidenced)}/{len(claimed)} claimed"
          + (f"  (+{unev_count} in unevidenced.md, CV-ineligible)" if unev_count else ""))
    print(f"- Identity fields:        {len(filled)}/{len(IDENTITY_FIELDS)} filled"
          + (f"  (missing: {', '.join(missing)})" if missing else ""))
    print(f"- Contradictions flagged: {contradictions}")
    print(f"- Queue items open:       {len(open_items)}"
          + (f"  ({added} newly added)" if added else ""))
    print(f"\nPROFILE STRENGTH: {strength}/100")
    if open_items:
        top = sorted(open_items, key=lambda e: -int(e.get("impact", 0)))[:3]
        print("\nHighest-impact next answers (run /enrich):")
        for e in top:
            print(f"  [{e.get('impact','?')}] {e.get('prompt','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
