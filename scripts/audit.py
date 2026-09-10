#!/usr/bin/env python3
"""audit.py — deterministic truth audit of an application folder.

Checks (per engine/rules/truth_guardrails.md):
- trace IDs in cv_draft.md / cover_letter_draft.md resolve to knowledge files
- every CV bullet has exactly one `<!-- src:ID -->` trace
- skills in the CV Skills section exist in skills_inventory.md with Evidence
- numeric values in each traced bullet appear in that single source bullet
  (no metric recombination)
- evidence_map.md REQ rows are well-formed; `no_evidence` terms absent from CV
- gap_suggestions.md exists when the evidence map has no_evidence rows
- contact block: `# {candidate name}` + headline + contact line, then `## Summary`
  (the name comes from config/pipeline.yaml identity.name)
- date formats: `Mon YYYY to Mon YYYY` / `Mon YYYY to Present` (en dash still
  accepted for legacy assets), no `--`, no ASCII hyphen year ranges
- WARN (not FAIL): repeated figures across Summary/Experience beyond the one
  allowed Summary headline echo (engine/rules/tailoring_rules.md §5a)

`--library <file>` runs library mode instead: validates the `claims:` traces of
a generated positioning file against knowledge/ before it reaches disk.

Exit 0 = PASS, 1 = FAIL. FAIL items must be adjudicated by the user as
fix / bypass / halt — never silently fixed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402

VALID_STATUSES = {"explicit_match", "implicit_match", "no_evidence"}
VALID_ACTIONS = {"use_summary", "use_experience", "use_skills",
                 "cover_letter_only", "gap_only", "omit"}
PLACEHOLDERS = {"TBD", "TODO", "None", "[confirm]"}
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# Canonical range connector is " to " (parenthetical style, zero dashes).
# The en dash " – " is still accepted for backward-compat with already-submitted
# applications generated under the old format.
RANGE_SEP = r"(?:to|–)"
DATE_RANGE = re.compile(rf"({MONTHS}) \d{{4}} {RANGE_SEP} (({MONTHS}) \d{{4}}|Present)")
YEAR_RANGE = re.compile(rf"\d{{4}} {RANGE_SEP} (\d{{4}}|Present)")
BAD_HYPHEN_RANGE = re.compile(r"\b(19|20)\d{2}\s+-\s+((19|20)\d{2}|Present)\b")

NUMBER_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def figure_re() -> re.Pattern:
    """Generic quantity pattern plus the pack-supplied figure-noun list:
    percentages, `Nk+` counts, and `<number|number-word> <noun>` phrases."""
    nouns = "|".join(re.escape(n.rstrip("s")) + "s?" for n in packs.figure_nouns())
    words = "|".join(NUMBER_WORDS)
    return re.compile(
        rf"\+?\d+(?:\.\d+)?%|\b\d+k\+|\b(?:\d+|{words})[\s-]+(?:{nouns})\b",
        re.IGNORECASE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def find_bullet_ids(text: str) -> set:
    return set(re.findall(r"#### ([A-Z0-9-]+)", text))


def parse_education_ids(text: str) -> set:
    return set(re.findall(r"^###\s+([A-Z]+-[A-Z0-9-]+)\s+—", text, re.MULTILINE))


def find_trace_ids(text: str, trace_name: str) -> list:
    results = []
    for match in re.finditer(rf"<!--\s*{re.escape(trace_name)}:([^>]+)-->", text):
        for part in match.group(1).strip().split(","):
            cleaned = part.strip()
            if cleaned and not cleaned.startswith("company:"):
                results.append(cleaned)
    return results


def parse_skill_inventory(text: str):
    skill_names, evidence_backed = set(), set()
    current_skill, current_section = None, ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            current_skill = None
            continue
        m = re.match(r"- \*\*(.+?)\*\*(?:\s*—.*)?$", line)
        if m:
            current_skill = m.group(1).strip()
            skill_names.add(current_skill)
            if current_section == "Languages":
                evidence_backed.add(current_skill)
            continue
        if current_skill and "Evidence:" in line and "[confirm]" not in line:
            evidence_backed.add(current_skill)
    return skill_names, evidence_backed


def parse_cv_skills(text: str) -> list:
    in_skills, found = False, []
    for line in text.splitlines():
        if line.startswith("## "):
            in_skills = line.strip() == "## Skills"
            continue
        if not in_skills:
            continue
        m = re.match(r"\*\*.+?:\*\*\s*(.+)$", line.strip())
        if m:
            found.extend(p.strip() for p in m.group(1).split(",") if p.strip())
    return found


def source_blocks(text: str) -> dict:
    blocks = {}
    matches = list(re.finditer(r"^####\s+([A-Z0-9-]+)\s*$", text, re.MULTILINE))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks[m.group(1)] = text[m.end():end]
    return blocks


def numeric_tokens(text: str) -> list:
    return re.findall(r"(?<![A-Za-z])(?:\d+(?:\.\d+)?%?|\d+x)(?![A-Za-z])", text, re.IGNORECASE)


def parse_evidence_map(text: str) -> list:
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("| REQ-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 7:
            rows.append({"requirement_id": cells[0] if cells else "UNKNOWN", "parse_error": raw_line})
            continue
        rows.append(dict(zip(
            ["requirement_id", "jd_wording", "kind", "priority", "status", "evidence_refs", "cv_action"],
            cells)))
    return rows


def ref_parts(raw: str) -> list:
    if raw.lower() in {"", "none", "n/a"}:
        return []
    return [p.strip(" `") for p in re.split(r"[,;]", raw) if p.strip()]


def contains_term(text: str, term: str) -> bool:
    term = term.strip()
    if not term or term.lower() in {"none", "n/a"} or len(term) < 4:
        return False
    return term.lower() in text.lower()


def check_structure_and_dates(cv_text: str, issues: list) -> None:
    """Contact-block + date-normalization pre-audit checks."""
    name = packs.candidate_name()
    lines = [l for l in cv_text.splitlines()]
    if len(lines) < 4:
        issues.append("CV too short to contain the mandatory contact block.")
        return
    if name:
        if lines[0].strip() != f"# {name}":
            issues.append(f"CV line 1 must be `# {name}` (name header from config/pipeline.yaml).")
    elif not lines[0].startswith("# "):
        issues.append("CV line 1 must be `# <candidate name>` (name header; set identity.name in config/pipeline.yaml).")
    nonempty = [l for l in lines[1:6] if l.strip()]
    if len(nonempty) < 2:
        issues.append("CV must have headline + contact line before ## Summary.")
    else:
        contact = nonempty[1]
        if "@" not in contact or "|" not in contact:
            issues.append("CV line 3 (contact line) must contain email and `|`-separated fields.")
    summary_idx = next((i for i, l in enumerate(lines) if l.strip() == "## Summary"), None)
    if summary_idx is None:
        issues.append("CV is missing `## Summary` section.")
    else:
        between = [l for l in lines[1:summary_idx] if l.strip()]
        if len(between) != 2:
            issues.append("`## Summary` must come immediately after the 3-line contact block "
                          f"(found {len(between)} non-empty lines between name and Summary).")
    for n, line in enumerate(lines, start=1):
        visible = re.sub(r"<!--.*?-->", "", line)
        if line.startswith("### ") and " -- " in visible:
            issues.append(f"`--` used in role header at CV line {n}.")
        if BAD_HYPHEN_RANGE.search(visible):
            issues.append(f"ASCII hyphen date range at CV line {n}: use `Mon YYYY to Mon YYYY`.")
        if line.startswith("### "):
            tail = visible.split("—")[-1]
            if re.search(r"\d{4}", tail) and not (DATE_RANGE.search(tail) or YEAR_RANGE.search(tail)):
                issues.append(f"Date range at CV line {n} not normalized "
                              "(`Mon YYYY to Mon YYYY` or `Mon YYYY to Present`).")


def check_no_em_dash(text: str, label: str, issues: list) -> None:
    """style_and_ats_rules.md — em dashes and `--` are forbidden in generated
    candidate-facing content (an AI-writing tell). Use en dash (–) with spaces.
    Internal knowledge files keep their em dashes and are not passed here."""
    for n, line in enumerate(text.splitlines(), start=1):
        visible = re.sub(r"<!--.*?-->", "", line)
        if "—" in visible:
            issues.append(f"Em dash forbidden at {label} line {n}: use en dash "
                          "(–) with spaces (style_and_ats_rules.md).")
        elif " -- " in visible:
            issues.append(f"Double hyphen `--` forbidden at {label} line {n}: "
                          "use en dash (–) with spaces.")


def normalize_figure(token: str) -> str:
    t = token.lower().replace("-", " ")
    for word, digit in NUMBER_WORDS.items():
        t = re.sub(rf"\b{word}\b", digit, t)
    return re.sub(r"\s+", " ", t).strip().rstrip("s")


def check_repeated_figures(cv_text: str, warnings: list) -> None:
    """tailoring_rules.md §5a: a figure may appear at most twice, and the
    second occurrence only as the single Summary headline echo — never in two
    Experience bullets."""
    fig_re = figure_re()
    section, seen = None, {}
    for n, line in enumerate(cv_text.splitlines(), start=1):
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section not in {"Summary", "Experience"} or line.startswith("### "):
            continue
        visible = re.sub(r"<!--.*?-->", "", line)
        kind = "summary" if section == "Summary" else "bullet"
        for token in fig_re.findall(visible):
            seen.setdefault(normalize_figure(token), []).append((n, kind))
    for token, occ in sorted(seen.items()):
        summary_count = sum(1 for _, kind in occ if kind == "summary")
        bullet_count = len(occ) - summary_count
        if len(occ) == 1 or (summary_count == 1 and bullet_count == 1):
            continue
        lines_str = ", ".join(str(n) for n, _ in occ)
        warnings.append(f"repeated figure `{token}` appears {len(occ)} times "
                        f"(lines {lines_str}); §5a allows one Summary echo at most.")


def load_knowledge():
    master_text = read(paths.knowledge() / "master_experience.md")
    education_text = read(paths.knowledge() / "education_credentials.md")
    skills_text = read(paths.knowledge() / "skills_inventory.md")
    bullet_ids = find_bullet_ids(master_text)
    education_ids = parse_education_ids(education_text)
    skill_names, evidence_backed = parse_skill_inventory(skills_text)
    return {
        "allowed_trace_ids": bullet_ids | education_ids,
        "skill_names": skill_names,
        "evidence_backed": evidence_backed,
        "blocks": source_blocks(master_text),
    }


def validate(folder: Path):
    issues, warnings = [], []
    jd_analysis = folder / "jd_analysis.md"
    evidence_map = folder / "evidence_map.md"
    cv_draft = folder / "cv_draft.md"
    cover_draft = folder / "cover_letter_draft.md"
    gap_suggestions = folder / "gap_suggestions.md"

    for path in (jd_analysis, evidence_map, cv_draft):
        if not path.exists():
            issues.append(f"Missing required file: {path.name}")

    kb = load_knowledge()
    allowed_trace_ids = kb["allowed_trace_ids"]
    skill_names, evidence_backed = kb["skill_names"], kb["evidence_backed"]
    blocks = kb["blocks"]

    cv_text = read(cv_draft)
    cover_text = read(cover_draft)
    rows = parse_evidence_map(read(evidence_map))

    if evidence_map.exists() and not rows:
        issues.append("evidence_map.md has no REQ rows.")

    for row in rows:
        req_id = row.get("requirement_id", "UNKNOWN")
        if "parse_error" in row:
            issues.append(f"{req_id}: malformed evidence-map row: {row['parse_error']}")
            continue
        if row["status"] not in VALID_STATUSES:
            issues.append(f"{req_id}: invalid status `{row['status']}`.")
        bad_actions = [a for a in ref_parts(row["cv_action"]) if a not in VALID_ACTIONS]
        if bad_actions:
            issues.append(f"{req_id}: invalid cv_action values: {', '.join(bad_actions)}.")
        refs_value = row["evidence_refs"].strip().lower()
        for ph in PLACEHOLDERS:
            if ph.lower() in row["status"].lower():
                issues.append(f"{req_id}: placeholder remains in evidence map.")
            elif ph.lower() in refs_value and refs_value not in {"none", "n/a", "", "-", "—"}:
                issues.append(f"{req_id}: placeholder remains in evidence map.")
        refs = ref_parts(row["evidence_refs"])
        if row["status"] in {"explicit_match", "implicit_match"} and not refs:
            issues.append(f"{req_id}: matched requirement has no evidence_refs.")
        if row["status"] == "no_evidence" and refs and refs != ["none"]:
            issues.append(f"{req_id}: no_evidence row should not cite evidence refs.")
        if row["status"] == "no_evidence" and contains_term(cv_text, row["jd_wording"]):
            issues.append(f"{req_id}: no_evidence term appears in cv_draft.md: `{row['jd_wording']}`.")
        for ref in refs:
            if ref not in allowed_trace_ids and ref not in skill_names:
                issues.append(f"{req_id}: unknown evidence ref `{ref}`.")

    cv_src_ids = find_trace_ids(cv_text, "src")
    cv_claim_ids = find_trace_ids(cv_text, "claims")
    if cv_text and not cv_src_ids:
        issues.append("CV is missing src trace comments.")
    for trace_id in cv_src_ids + cv_claim_ids:
        if trace_id not in allowed_trace_ids:
            issues.append(f"Unknown CV trace ID: {trace_id}")

    for n, line in enumerate(cv_text.splitlines(), start=1):
        if line.startswith("- ") and "<!-- src:" not in line:
            issues.append(f"CV bullet missing src trace at line {n}.")
        for ph in PLACEHOLDERS:
            if re.search(rf"\b{re.escape(ph)}\b", line):
                issues.append(f"Placeholder `{ph}` appears in CV at line {n}.")

    for skill in parse_cv_skills(cv_text):
        if skill not in skill_names:
            issues.append(f"Skill not found in skills inventory: {skill}")
        elif skill not in evidence_backed:
            issues.append(f"Skill lacks evidence in skills inventory: {skill}")

    for n, line in enumerate(cv_text.splitlines(), start=1):
        m = re.search(r"<!--\s*src:([^>]+)-->", line)
        if not m:
            continue
        ids = ref_parts(m.group(1))
        if len(ids) != 1:
            issues.append(f"CV bullet at line {n} must cite exactly one src ID.")
            continue
        if ids[0] not in blocks:
            continue
        visible = re.sub(r"<!--.*?-->", "", line)
        for token in numeric_tokens(visible):
            if token not in blocks[ids[0]]:
                issues.append(f"Number `{token}` at CV line {n} is not present in {ids[0]}.")

    if cover_text:
        cover_claims = find_trace_ids(cover_text, "claims")
        if not cover_claims:
            issues.append("Cover letter is missing claims trace comments.")
        for trace_id in cover_claims:
            if trace_id not in allowed_trace_ids and trace_id not in skill_names:
                issues.append(f"Unknown cover letter trace ID: {trace_id}")
        words = len(re.sub(r"<!--.*?-->", "", cover_text).split())
        if not 200 <= words <= 430:
            warnings.append(f"Cover letter is {words} words; target 250–400.")
        check_no_em_dash(cover_text, "cover letter", issues)

    if any(r.get("status") == "no_evidence" for r in rows) and not gap_suggestions.exists():
        issues.append("gap_suggestions.md is required because evidence_map.md contains no_evidence rows.")

    if cv_text:
        check_structure_and_dates(cv_text, issues)
        check_repeated_figures(cv_text, warnings)
        check_no_em_dash(cv_text, "CV", issues)
    if len(cv_text.split()) > 1100:
        warnings.append("CV draft is over 1100 words; check rendered length manually.")

    return ("FAIL" if issues else "PASS"), issues, warnings


def validate_library(path: Path):
    """Library mode: audit a generated positioning file at birth. Every
    `claims:` trace must resolve to knowledge/; a library that fails its own
    audit poisons every application downstream and must not reach disk."""
    issues, warnings = [], []
    text = read(path)
    if not text:
        issues.append(f"Library file is missing or empty: {path}")
        return "FAIL", issues, warnings
    kb = load_knowledge()
    claim_ids = find_trace_ids(text, "claims") + find_trace_ids(text, "src")
    if not claim_ids:
        issues.append("Library file carries no claims/src traces — generated "
                      "positioning must trace every factual line.")
    for trace_id in claim_ids:
        if trace_id not in kb["allowed_trace_ids"] and trace_id not in kb["skill_names"]:
            issues.append(f"Unknown library trace ID: {trace_id}")
    for n, line in enumerate(text.splitlines(), start=1):
        m = re.search(r"<!--\s*(?:src|claims):([^>]+)-->", line)
        if not m:
            continue
        ids = [i for i in ref_parts(m.group(1)) if i in kb["blocks"]]
        visible = re.sub(r"<!--.*?-->", "", line)
        for token in numeric_tokens(visible):
            if ids and not any(token in kb["blocks"][i] for i in ids):
                issues.append(f"Number `{token}` at library line {n} is not present in any cited bullet.")
    return ("FAIL" if issues else "PASS"), issues, warnings


def audit_log(overall, issues, warnings) -> str:
    lines = ["# Audit Log", "", f"OVERALL: {overall}", ""]
    if issues:
        lines.append("## Failures")
        for i, issue in enumerate(issues, start=1):
            lines.append(f"{i}. FAIL: {issue}")
            lines.append("   Disposition: pending user decision")
        lines.append("")
    else:
        lines += [
            "- PASS: Structural integrity and trace references validated.",
            "- PASS: Skills evidence validated against skills_inventory.md.",
            "- PASS: Evidence map statuses and no-evidence keyword discipline validated.",
            "- PASS: Numeric values in traced experience bullets are present in source blocks.",
            "- PASS: Contact block and date-format normalization validated.",
            "",
        ]
    if warnings:
        lines.append("## Warnings")
        lines += [f"- WARN: {w}" for w in warnings]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic truth audit of an application folder. "
                    "Exit 0 = PASS, 1 = FAIL (adjudicate fix/bypass/halt).")
    parser.add_argument("--folder", help="Application folder to audit.")
    parser.add_argument("--library", help="Audit a positioning/library file instead (library mode).")
    parser.add_argument("--write-log", action="store_true", help="Write audit_log.md into the folder.")
    args = parser.parse_args()
    if bool(args.folder) == bool(args.library):
        print("ERROR: pass exactly one of --folder or --library.", file=sys.stderr)
        return 1
    if args.library:
        overall, issues, warnings = validate_library(paths.resolve_folder(args.library))
        print(audit_log(overall, issues, warnings), end="")
        return 0 if overall == "PASS" else 1
    folder = paths.resolve_folder(args.folder)
    if not folder.exists():
        print(f"ERROR: folder does not exist: {folder}", file=sys.stderr)
        return 1
    overall, issues, warnings = validate(folder)
    text = audit_log(overall, issues, warnings)
    if args.write_log:
        (folder / "audit_log.md").write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
