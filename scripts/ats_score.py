#!/usr/bin/env python3
"""ats_score.py — deterministic ATS scorer (0–100) for an application folder.

Scores the CV (cv_draft.md — the live iteration artifact — falling back to
cv_final.md) against the JD's requirements as captured in the folder's
evidence_map.md.

Dimensions (weights):
- must-have requirement coverage 25  (evidence_map rows with priority=must)
- nice-to-have coverage           5  (priority=preferred/nice)
- JD hard-skill keyword coverage 20  (taxonomy terms found in the JD text)
- JD soft-skill keyword coverage 10  (taxonomy terms found in the JD text)
- section structure              10  (name+contact block, Summary, Experience, Skills, Education)
- date-format compliance         10
- quantified-bullet density      10
- title alignment                 5  (JD title tokens in headline)
- length band                     3  (350–1100 words)
- contact completeness            2  (email, phone, linkedin)

Two complementary keyword layers:
1. Requirement layer — the evidence_map REQ rows (what the JD *demands*).
2. JD-vocabulary layer — salient uni/bigrams EXTRACTED FROM the JD text itself
   (frequency >= 2, boilerplate removed), classified hard/soft via the active
   pack's ats_keywords.yaml lexicon and normalised via its ats_synonyms.yaml
   (plus locale bridge files for the configured languages).
   Taxonomy terms present in the JD are unioned in as a known-skill booster.
   This mirrors how a real ATS scanner extracts skills from the posting with
   no prior knowledge of the candidate — the taxonomy is a normaliser, NOT the
   candidate source (a curated list intersected with the JD understates the
   domain vocabulary the candidate lacks and inflates coverage toward 100%).
Both are matched case-insensitively with light stemming plus the synonym
tables.

IMPORTANT: keywords whose evidence_map status is `no_evidence` still count
against coverage but are flagged BLOCKED in the report — truth guardrails
outrank ATS score; they must never be inserted into the CV. Record them in
gap_suggestions.md instead.

Outputs ats_report.md in the folder and prints it. Exit code is always 0 on a
successful run; read the score from the output.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packs  # noqa: E402
import paths  # noqa: E402

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# Canonical range connector is " to "; en dash " – " still accepted for legacy assets.
RANGE_SEP = r"(?:to|–)"
DATE_RANGE = re.compile(rf"({MONTHS}) \d{{4}} {RANGE_SEP} (({MONTHS}) \d{{4}}|Present)")
YEAR_RANGE = re.compile(rf"\d{{4}} {RANGE_SEP} (\d{{4}}|Present)")
BAD_HYPHEN_RANGE = re.compile(r"\b(19|20)\d{2}\s+-\s+((19|20)\d{2}|Present)\b")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def load_synonyms(files: list) -> dict:
    """Minimal reader for the flat `key: [a, b, c]` format of the pack's
    synonym tables. Multiple files merge: the same canonical may appear in
    several files (e.g. English morphology + a locale's bridges)."""
    groups: dict = {}
    for path in files:
        for line in read(path).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(.+?):\s*\[(.*)\]\s*$", line)
            if not m:
                continue
            canonical = m.group(1).strip().lower()
            syns = [s.strip().lower() for s in m.group(2).split(",") if s.strip()]
            groups.setdefault(canonical, {canonical}).update(syns)
    return groups


def load_taxonomy(path: Path) -> dict:
    """Reader for ats_keywords.yaml: `section:` headers + `- term` items."""
    sections, current = {}, None
    for line in read(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            current = stripped[:-1].strip()
            sections[current] = []
        elif stripped.startswith("- ") and current:
            sections[current].append(stripped[2:].strip().lower())
    return sections


def stem(token: str) -> str:
    token = token.lower()
    for suffix in ("ing", "es", "ed", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list:
    """Tokens plus the parts of any /- or -- compound (agile/scrum -> agile, scrum)."""
    raw = re.findall(r"[a-z0-9&/+.#-]+", text.lower())
    out = []
    for t in raw:
        t = t.strip(".-/")          # keep .net / c# / a/b intact, drop edge punctuation
        if not t:
            continue
        out.append(t)
        parts = [p.strip(".") for p in re.split(r"[/-]", t) if p.strip(".")]
        if len(parts) > 1:
            out.extend(parts)
    return out


def normalize_text(text: str) -> set:
    tokens = tokenize(text)
    return {stem(t) for t in tokens} | set(tokens)


STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "with", "for", "on", "at",
    "as", "by", "from", "via", "into", "across", "years", "year", "yrs",
    "experience", "experiences", "strong", "proven", "solid", "excellent",
    "good", "ability", "abilities", "skills", "skill", "knowledge", "track",
    "record", "background", "working", "demonstrated", "hands", "minimum",
    "plus", "least",
}


def content_words(phrase: str) -> list:
    words = []
    for w in re.findall(r"[a-z][a-z&/+.#-]*", phrase.lower()):
        parts = [p for p in re.split(r"[/]", w) if p]
        words.extend(parts if len(parts) > 1 else [w])
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def word_covered(word: str, text_lower: str, token_set: set, synonyms: dict) -> bool:
    if word in token_set or stem(word) in token_set:
        return True
    for group in synonyms.values():
        if word in group or stem(word) in {stem(g) for g in group}:
            if any(s in text_lower for s in group):
                return True
    return False


def phrase_present(words: list, text_lower: str) -> bool:
    """True if the content words appear as an actual phrase — same order, each
    stem-matched, with at most one filler word between consecutive terms. This
    replaces scattered-word credit, which let common carrier words fake a match
    (e.g. 'product vision' credited because 'product' is everywhere and 'vision'
    appears in an unrelated context)."""
    atoms = [re.escape(stem(w)) + r"[a-z]*" for w in words]
    sep = r"[^a-z0-9]+(?:[a-z0-9]+[^a-z0-9]+)?"  # gap, optionally one filler token
    return re.search(r"\b" + sep.join(atoms), text_lower) is not None


def keyword_covered(keyword: str, text_lower: str, token_set: set, synonyms: dict) -> bool:
    """A keyword counts as covered when the exact phrase appears, a synonym-group
    member appears, a single-word term (or its stem/synonym) appears, or — for a
    multiword phrase — its words appear adjacently as a phrase (see phrase_present).
    Scattered-word credit was removed: it over-credited phrases whose only present
    word was a generic carrier."""
    kw = keyword.lower().strip()
    if not kw:
        return False
    if kw in text_lower:
        return True
    # a synonym-group member present as a literal substring, or (for multiword
    # members) present as an adjacent phrase, bridges the wording
    for group in synonyms.values():
        if kw not in group:
            continue
        for s in group:
            s_words = content_words(s)
            if s in text_lower or (len(s_words) > 1 and phrase_present(s_words, text_lower)):
                return True
    words = content_words(kw)
    if not words:
        return True  # phrase was only numbers/stopwords (e.g. "3-5+ years")
    if len(words) == 1:
        return word_covered(words[0], text_lower, token_set, synonyms)
    # Short keyword phrases (the taxonomy/extraction layer, e.g. "product
    # vision") demand adjacency — that is where carrier-word false positives
    # live. Long requirement sentences (evidence_map jd_wording, e.g. a full
    # localized requirement) legitimately match by concept coverage, so keep
    # the overlap rule there — many distinctive words make carriers
    # non-distorting.
    if len(words) <= 3:
        return phrase_present(words, text_lower)
    hits = sum(1 for w in words if word_covered(w, text_lower, token_set, synonyms))
    return hits / len(words) >= 0.6


def canonical_form(term: str, synonyms: dict) -> str:
    """Map a surface term to its synonym-group canonical (else a stemmed key),
    so 'product management'/'product manager' and locale bridges collapse to
    one candidate. This is the taxonomy-as-normaliser half of the hybrid."""
    t = term.lower().strip()
    for canonical, group in synonyms.items():
        if t in group or stem(t) in {stem(g) for g in group}:
            return canonical
    return " ".join(stem(w) for w in t.split())


# Hiring/JD boilerplate stripped only during JD keyword extraction (not from
# the requirement layer). Kept modest so real skill words survive.
EXTRACT_STOP = STOPWORDS | {
    "role", "roles", "company", "companies", "team", "teams", "join", "looking",
    "seeking", "candidate", "candidates", "ideal", "responsibilities",
    "opportunity", "position", "help", "make", "want", "need", "you", "your",
    "our", "we", "us", "they", "them", "their", "will", "would", "can", "may",
    "should", "this", "that", "these", "those", "who", "what", "which", "how",
    "why", "when", "where", "day", "days", "week", "weeks", "month", "months",
    "time", "well", "also", "etc", "including", "include", "includes", "using",
    "use", "used", "within", "about", "around", "over", "under", "per", "such",
    "more", "most", "many", "some", "any", "all", "both", "each", "other",
    "than", "then", "there", "here", "very", "just", "not", "own", "new", "like",
    "stated", "understanding", "ensure", "ensuring", "provide", "providing",
    "related", "based", "remote", "location", "url", "http", "https",
    "www", "com", "meta", "inferable", "signals",
    # portal/meta boilerplate that leaked into extraction
    "posted", "salary", "hybrid", "size", "job", "jobs", "fully", "full",
    "senior", "junior", "mid", "level", "europe", "emea", "verbatim",
    "term", "insurance", "opportunities", "policy", "type",
    "employment", "context", "date", "found", "language", "industry", "stage",
}


def company_stopwords(jd_text: str) -> set:
    """The employer name is high-frequency JD boilerplate, never a skill —
    strip its tokens (from the JD's own Company field) before extraction."""
    m = re.search(r"\*\*Company:\*\*\s*(.+)", jd_text)
    if not m:
        return set()
    return {w for w in re.findall(r"[a-z0-9]+", m.group(1).lower()) if len(w) > 2}


def extract_jd_keywords(jd_text, taxonomy, synonyms, hard_cap=45, soft_cap=12):
    """Extract the JD's salient keywords FROM the posting (freq>=2 uni/bigrams,
    boilerplate removed), normalise via synonyms, classify hard/soft via the
    taxonomy lexicon, and union in any taxonomy terms present in the JD. Returns
    (hard_terms, soft_terms) bounded by salience. Replaces the old taxonomy∩JD
    candidate set, which was blind to domain vocabulary the taxonomy never listed."""
    stop = EXTRACT_STOP | company_stopwords(jd_text)
    toks = re.findall(r"[a-z][a-z0-9+#.]*", jd_text.lower())
    uni, bi = Counter(), Counter()
    for i, t in enumerate(toks):
        if len(t) > 2 and t not in stop:
            uni[t] += 1
        if i + 1 < len(toks):
            a, b = t, toks[i + 1]
            if len(a) > 2 and len(b) > 2 and a not in stop and b not in stop:
                bi[f"{a} {b}"] += 1
    cand = [w for w, c in uni.items() if c >= 2] + [w for w, c in bi.items() if c >= 2]
    # known-skill booster: taxonomy terms that actually appear in the JD
    jd_lower = jd_text.lower()
    jd_tokens = normalize_text(jd_text)
    for sec in ("hard_skills", "soft_skills"):
        for term in taxonomy.get(sec, []):
            if keyword_covered(term, jd_lower, jd_tokens, synonyms):
                cand.append(term)
    # dedup by canonical form, keeping the first surface form seen
    seen, terms = set(), []
    for w in cand:
        key = canonical_form(w, synonyms)
        if key not in seen:
            seen.add(key)
            terms.append(w)
    soft_canon = {canonical_form(t, synonyms) for t in taxonomy.get("soft_skills", [])}
    hard, soft = [], []
    for w in terms:
        (soft if canonical_form(w, synonyms) in soft_canon else hard).append(w)

    def salience(w):
        return bi.get(w, uni.get(w, 1))
    hard = sorted(hard, key=salience, reverse=True)[:hard_cap]
    soft = sorted(soft, key=salience, reverse=True)[:soft_cap]
    return hard, soft


def parse_evidence_map(text: str) -> list:
    rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("| REQ-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 7:
            rows.append(dict(zip(
                ["requirement_id", "jd_wording", "kind", "priority", "status", "evidence_refs", "cv_action"],
                cells)))
    return rows


def jd_title(jd_text: str) -> str:
    m = re.search(r"Role title.*?:\s*\**\s*(.+)", jd_text)
    return m.group(1).strip().strip("*") if m else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", required=True, help="Application folder.")
    parser.add_argument("--jd", required=True, help="JD file, e.g. jd_texts/sample001.md")
    args = parser.parse_args()

    folder = paths.resolve_folder(args.folder)
    jd_path = paths.resolve_folder(args.jd)
    if not folder.exists():
        print(f"ERROR: folder does not exist: {folder}", file=sys.stderr)
        return 1
    if not jd_path.exists():
        print(f"ERROR: JD file does not exist: {jd_path}", file=sys.stderr)
        return 1

    # Score the working draft (trace comments are stripped below). cv_final.md
    # is only a fallback — during the /prepare iteration loop the draft is the
    # live artifact and a previously exported final may be stale.
    cv_path = folder / "cv_draft.md"
    if not cv_path.exists():
        cv_path = folder / "cv_final.md"
    cv_raw = read(cv_path)
    if not cv_raw:
        print(f"ERROR: no cv_final.md or cv_draft.md in {folder}", file=sys.stderr)
        return 1
    cv = strip_comments(cv_raw)
    cv_lower = cv.lower()
    tokens = normalize_text(cv)
    synonyms = load_synonyms(packs.synonym_files())
    rows = parse_evidence_map(read(folder / "evidence_map.md"))
    if not rows:
        print(f"ERROR: evidence_map.md missing or has no REQ rows in {folder}", file=sys.stderr)
        return 1
    jd_text = read(jd_path)

    report = ["# ATS Report", "", f"CV: `{cv_path.name}`  JD: `{jd_path.name}`", ""]

    # Condensed-JD guard: scoring against a summarized JD understates missing
    # keywords (engine/rules/jd_template.md § Raw text requires the full posting).
    raw_match = re.search(r"^## Raw text.*$", jd_text, re.MULTILINE)
    raw_words = len(jd_text[raw_match.end():].split()) if raw_match else 0
    if raw_words < 200:
        state = "missing" if raw_match is None else f"stub, {raw_words} words"
        warning = (f"WARNING: JD raw text is {state} — score computed against "
                   "possibly condensed text; re-extract verbatim from "
                   "original_url before trusting this score.")
        print(warning, file=sys.stderr)
        report += [f"**{warning}**", ""]
    breakdown = []

    # --- keyword coverage --------------------------------------------------
    # Rows the evidence map deliberately routes outside the CV are not part of
    # CV keyword coverage. no_evidence/gap_only rows STAY in the denominator —
    # the JD wants them and the CV truthfully lacks them, which costs points.
    scoreable = [r for r in rows if r["cv_action"] not in ("cover_letter_only", "omit")]
    must = [r for r in scoreable if r["priority"] == "must"]
    nice = [r for r in scoreable if r["priority"] in ("preferred", "nice")]
    missing_rows = []

    def coverage(rows_, weight, label):
        if not rows_:
            return weight, f"{label}: no rows — full credit"
        hits = 0
        for r in rows_:
            covered = keyword_covered(r["jd_wording"], cv_lower, tokens, synonyms)
            if covered:
                hits += 1
            else:
                missing_rows.append((r, label))
        pts = round(weight * hits / len(rows_), 1)
        return pts, f"{label}: {hits}/{len(rows_)} covered"
    must_pts, must_note = coverage(must, 25, "must-have requirements")
    nice_pts, nice_note = coverage(nice, 5, "nice-to-have requirements")
    breakdown.append(("Must-have requirement coverage", must_pts, 25, must_note))
    breakdown.append(("Nice-to-have requirement coverage", nice_pts, 5, nice_note))

    # --- JD-vocabulary layer: hard/soft skill terms extracted from the JD ----
    taxonomy = load_taxonomy(packs.keywords_file())
    jd_hard_terms, jd_soft_terms = extract_jd_keywords(jd_text, taxonomy, synonyms)
    no_evidence_terms = {r["jd_wording"].lower() for r in rows if r["status"] == "no_evidence"}

    def term_coverage(terms, weight, label):
        if not terms:
            return weight, f"{label}: none extracted from JD — full credit", [], []
        hit, miss = [], []
        for t in terms:
            (hit if keyword_covered(t, cv_lower, tokens, synonyms) else miss).append(t)
        pts = round(weight * len(hit) / len(terms), 1)
        return pts, f"{label}: {len(hit)}/{len(terms)} JD terms covered", hit, miss

    hard_pts, hard_note, hard_hit, hard_miss = term_coverage(jd_hard_terms, 20, "hard skills")
    soft_pts, soft_note, soft_hit, soft_miss = term_coverage(jd_soft_terms, 10, "soft skills")
    breakdown.append(("JD hard-skill keyword coverage", hard_pts, 20, hard_note))
    breakdown.append(("JD soft-skill keyword coverage", soft_pts, 10, soft_note))

    # --- section structure ---------------------------------------------------
    lines = cv.splitlines()
    checks = {
        "name header (`# `)": bool(lines and lines[0].startswith("# ")),
        "## Summary": "## Summary" in cv,
        "## Experience": "## Experience" in cv,
        "## Skills": "## Skills" in cv,
        "## Education": "## Education" in cv,
    }
    struct_pts = round(10 * sum(checks.values()) / len(checks), 1)
    breakdown.append(("Section structure", struct_pts, 10,
                      ", ".join(k for k, v in checks.items() if not v) or "all present"))

    # --- date-format compliance ----------------------------------------------
    headers = [l for l in lines if l.startswith("### ")]
    dated = [h for h in headers if re.search(r"\d{4}", h)]
    good = [h for h in dated if DATE_RANGE.search(h) or YEAR_RANGE.search(h)]
    bad_ranges = len(BAD_HYPHEN_RANGE.findall(cv)) + cv.count(" -- ")
    date_pts = 10.0
    if dated:
        date_pts = round(10 * len(good) / len(dated), 1)
    if bad_ranges:
        date_pts = max(0.0, date_pts - 5)
    breakdown.append(("Date-format compliance", date_pts, 10,
                      f"{len(good)}/{len(dated)} headers normalized, {bad_ranges} bad ranges"))

    # --- quantified-bullet density ---------------------------------------------
    bullets = [l for l in lines if l.startswith("- ") and "## Skills" not in l]
    exp_section = re.search(r"## Experience(.*?)(?=^## |\Z)", cv, re.DOTALL | re.MULTILINE)
    exp_bullets = [l for l in (exp_section.group(1).splitlines() if exp_section else []) if l.strip().startswith("- ")]
    target = exp_bullets or bullets
    quantified = [b for b in target if re.search(r"\d", b)]
    quant_ratio = len(quantified) / len(target) if target else 0
    quant_pts = round(10 * min(1.0, quant_ratio / 0.6), 1)  # 60%+ quantified = full credit
    breakdown.append(("Quantified-bullet density", quant_pts, 10,
                      f"{len(quantified)}/{len(target)} bullets carry a number"))

    # --- title alignment ----------------------------------------------------
    title = jd_title(jd_text)
    headline = lines[1].strip() if len(lines) > 1 else ""
    title_words = [w for w in re.findall(r"[a-zA-Z]+", title.lower()) if len(w) > 2
                   and w not in {"the", "and", "for", "with"}]
    matched_words = [w for w in title_words if w in cv_lower]
    title_pts = round(5 * len(matched_words) / len(title_words), 1) if title_words else 5.0
    breakdown.append(("Title alignment", title_pts, 5,
                      f"JD title `{title}` vs headline `{headline}`: {len(matched_words)}/{len(title_words)} words"))

    # --- length band --------------------------------------------------------
    words = len(cv.split())
    length_pts = 3.0 if 350 <= words <= 1100 else (1.5 if 250 <= words <= 1300 else 0.0)
    breakdown.append(("Length band", length_pts, 3, f"{words} words (target 350–1100)"))

    # --- contact completeness -------------------------------------------------
    contact_bits = {"email": "@" in cv, "phone": bool(re.search(r"\+\d{7,}|\+\d+ [\d ]{6,}", cv)),
                    "linkedin": "linkedin.com" in cv_lower}
    contact_pts = round(2 * sum(contact_bits.values()) / 3, 1)
    breakdown.append(("Contact completeness", contact_pts, 2,
                      ", ".join(k for k, v in contact_bits.items() if not v) or "all present"))

    total = round(sum(p for _, p, _, _ in breakdown))
    report.append(f"## Score: {total}/100\n")
    report.append("| dimension | points | max | note |")
    report.append("|---|---|---|---|")
    for name, pts, mx, note in breakdown:
        report.append(f"| {name} | {pts} | {mx} | {note} |")
    report.append("")

    report.append("## Missing / weak requirements (evidence-map layer)\n")
    if missing_rows:
        report.append("| REQ | keyword | priority | status | actionable |")
        report.append("|---|---|---|---|---|")
        for r, label in missing_rows:
            blocked = r["status"] == "no_evidence"
            action = ("BLOCKED — no_evidence; never insert; record in gap_suggestions.md"
                      if blocked else "insert via cited evidence (see evidence_map)")
            report.append(f"| {r['requirement_id']} | {r['jd_wording']} | {r['priority']} | {r['status']} | {action} |")
    else:
        report.append("None — all evidence-map keywords covered.")
    report.append("")

    def term_status(term: str) -> str:
        for ne in no_evidence_terms:
            if term in ne or ne in term:
                return "BLOCKED — no_evidence in evidence_map; gap_suggestions.md only"
        return "insert ONLY if evidenced (check evidence_map / skills_inventory first)"

    report.append("## Missing JD-vocabulary terms (taxonomy layer)\n")
    if hard_miss or soft_miss:
        report.append("| kind | term | actionable |")
        report.append("|---|---|---|")
        for t in hard_miss:
            report.append(f"| hard | {t} | {term_status(t)} |")
        for t in soft_miss:
            report.append(f"| soft | {t} | {term_status(t)} |")
    else:
        report.append("None — all JD taxonomy terms covered.")
    report.append("")
    report.append(f"_JD vocabulary covered: hard {len(hard_hit)}/{len(hard_hit) + len(hard_miss)}, "
                  f"soft {len(soft_hit)}/{len(soft_hit) + len(soft_miss)}._")
    report.append("")
    report.append("_Truth guardrails outrank this score: a `no_evidence` keyword is never "
                  "inserted, even if it costs points._")

    text = "\n".join(report) + "\n"
    (folder / "ats_report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"SCORE: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
