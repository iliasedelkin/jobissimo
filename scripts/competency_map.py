#!/usr/bin/env python3
"""competency_map.py — deterministic competency map from knowledge/.

Reads $JOBISSIMO_HOME/knowledge/master_experience.md and skills_inventory.md
and writes $JOBISSIMO_HOME/competency_map.md: per competency tag — evidence
count, bullet IDs, whether any evidence carries a metric, most recent use,
declared skill level where one maps, and a derived tier.

Tiers come from evidence weight, not self-assessment:
- core        3+ evidenced bullets, at least one metric-bearing, used within
              the last two years
- supporting  2+ bullets, or 1 metric-bearing bullet used recently
- contextual  1 bullet
- gap         declared somewhere but zero evidencing bullets

Run after any knowledge edit; /setup S7 and /enrich call it automatically.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_roles(master: str) -> list:
    """[(role_id, period_end_year, [ (bullet_id, tags, has_metric) ])]"""
    roles = []
    role_blocks = re.split(r"^## ROLE:\s*", master, flags=re.MULTILINE)[1:]
    for block in role_blocks:
        header = block.splitlines()[0]
        role_id = header.split("—")[0].strip().split()[0]
        m = re.search(r"\*\*Period:\*\*\s*(.+)", block)
        end_year = 0
        if m:
            period = m.group(1)
            if "present" in period.lower():
                end_year = date.today().year
            else:
                years = re.findall(r"(19|20)\d{2}", period)
                if years:
                    end_year = int(re.findall(r"\b((?:19|20)\d{2})\b", period)[-1])
        bullets = []
        for bm in re.finditer(r"^#### ([A-Z0-9-]+)\s*\n(.*?)(?=^#### |\Z)",
                              block, flags=re.MULTILINE | re.DOTALL):
            bullet_id, body = bm.group(1), bm.group(2)
            tm = re.search(r"\*\*Tags:\*\*\s*(.+)", body)
            tags = [t.strip() for t in (tm.group(1).split(",") if tm else []) if t.strip()]
            # strip provenance comments first: their SRC-NNN ids carry digits
            # that would otherwise register as a (false) metric
            metric_body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
            has_metric = bool(re.search(r"\d+(?:\.\d+)?%|\b\d+[xk]\b|\b\d+\b", metric_body))
            bullets.append((bullet_id, tags, has_metric))
        roles.append((role_id, end_year, bullets))
    return roles


def parse_declared_skills(skills: str) -> dict:
    """{skill_name: (proficiency, recency, [evidence refs])}"""
    out, current = {}, None
    for line in skills.splitlines():
        m = re.match(r"- \*\*(.+?)\*\*", line.strip())
        if m:
            current = m.group(1).strip()
            out[current] = {"proficiency": None, "recency": None, "evidence": []}
            continue
        if current is None:
            continue
        pm = re.match(r"-\s*Proficiency:\s*(.+)", line.strip())
        if pm:
            out[current]["proficiency"] = pm.group(1).strip()
        rm = re.match(r"-\s*Recency:\s*(\d{4})", line.strip())
        if rm:
            out[current]["recency"] = int(rm.group(1))
        em = re.match(r"-\s*Evidence:\s*(.+)", line.strip())
        if em and "[confirm]" not in em.group(1):
            out[current]["evidence"] = [e.strip() for e in em.group(1).split(",") if e.strip()]
    return out


def build_map() -> str:
    master = read(paths.knowledge() / "master_experience.md")
    skills = read(paths.knowledge() / "skills_inventory.md")
    roles = parse_roles(master)
    declared = parse_declared_skills(skills)
    this_year = date.today().year

    # competency := tag on bullets, plus declared skills as their own rows
    comp: dict = {}
    for role_id, end_year, bullets in roles:
        for bullet_id, tags, has_metric in bullets:
            for tag in tags:
                c = comp.setdefault(tag, {"bullets": [], "metric": 0, "recent": 0})
                c["bullets"].append(bullet_id)
                c["metric"] += 1 if has_metric else 0
                c["recent"] = max(c["recent"], end_year)

    bullet_index = {b for _, _, bs in roles for b, _, _ in bs}

    def tier(entry, declared_only=False):
        if declared_only:
            return "gap"
        n = len(entry["bullets"])
        recent = entry["recent"] >= this_year - 2
        if n >= 3 and entry["metric"] >= 1 and recent:
            return "core"
        if n >= 2 or (entry["metric"] >= 1 and recent):
            return "supporting"
        if n >= 1:
            return "contextual"
        return "gap"

    lines = ["# Competency Map", "",
             "_Generated deterministically by scripts/competency_map.py from "
             "knowledge/ — do not hand-edit; edit knowledge/ and re-run._", "",
             "| competency | tier | evidence | metric-bearing | last used | bullet IDs |",
             "|---|---|---|---|---|---|"]
    order = {"core": 0, "supporting": 1, "contextual": 2, "gap": 3}
    rows = []
    for tag, entry in comp.items():
        rows.append((tag, tier(entry), len(entry["bullets"]), entry["metric"],
                     entry["recent"] or "-", ", ".join(entry["bullets"][:8])))
    for name, info in declared.items():
        refs = [r for r in info["evidence"] if r in bullet_index]
        if refs:
            metric = 0  # skill rows report evidence, not metrics
            recent = info["recency"] or "-"
            t = "core" if len(refs) >= 3 else ("supporting" if len(refs) >= 2 else "contextual")
            rows.append((f"{name} (skill)", t, len(refs), metric, recent, ", ".join(refs[:8])))
        elif not info["evidence"]:
            rows.append((f"{name} (skill)", "gap", 0, 0, info["recency"] or "-", "—"))
    rows.sort(key=lambda r: (order.get(r[1], 9), -r[2], str(r[0])))
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
    lines += ["",
              f"_Roles: {len(roles)} · bullets: {len(bullet_index)} · "
              f"competencies: {len(rows)}._", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdout", action="store_true",
                        help="Print instead of writing profile/competency_map.md")
    args = parser.parse_args()
    if not (paths.knowledge() / "master_experience.md").exists():
        print(f"ERROR: {paths.knowledge() / 'master_experience.md'} not found — "
              "run /setup first.", file=sys.stderr)
        return 1
    text = build_map()
    if args.stdout:
        print(text)
    else:
        out = paths.home() / "competency_map.md"
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
