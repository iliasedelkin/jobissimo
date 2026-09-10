# Cover Letter Playbook

How the Generator produces a cover letter that is tailored, honest, short, and
reads like a human who actually wanted this specific role wrote it.

---

## Governing principles — humanising an accurate cover letter

These outrank the structure below. If a structural rule and a principle
conflict, the principle wins.

- **Find the human centre:** why this particular company, problem, or role
  genuinely matters to the candidate. If the candidate supplied driving factors
  (§ Driving factors), that IS the human centre — use it. Never invent a
  motivation the candidate has not expressed.
- **Plain language, concrete examples.** Replace polished abstractions with one
  or two real decisions and results. Let the evidence carry the argument.
- **Cut anything copied from the JD, overly defensive, or written to impress.**
  Keep the confidence; make it conversational and credible.
- **Every sentence earns its place** by adding motivation, evidence, or
  personality. Cut the rest.
- **Read-aloud test:** the final letter must sound natural read aloud and leave
  the reader with one clear impression of the candidate.

---

## Length

- **150–220 words.** Hard max 250. Shorter is fine if it is complete.
- 3 short paragraphs. Recruiters skim; brevity reads as confidence.

---

## Structure — three beats (a shape, not a template)

Hit these beats; do not pad to a word budget. Vary them to fit the role and the
candidate's voice.

### 1. The human centre + the specific role
Open on why this company / problem / role genuinely matters to the candidate —
ideally in the candidate's own words (§ Driving factors). Name the role. Do NOT
open by paraphrasing the JD back at the reader, and never with "I'm excited to
apply". One or two sentences.

### 2. The proof
One or two concrete things the candidate has actually done that matter for THIS
role — real decisions and results, as narrative, not a CV in prose. Choose the
proof that demonstrates fit; there is no separate "fit" paragraph. Each factual
claim carries `<!-- claims:BULLET_ID -->` at paragraph end. Use numbers where
they exist; do not force them.

### 3. The close
Logistics in one line if relevant (location, remote-readiness, timezone). One
line of direct, specific interest — never "I look forward to hearing from you".
Sign off simply: "Best, {first name}" or "Best regards, {full name}", matching
tone (names from `applicant_profile.yaml`).

---

## Driving factors (the human-centre input)

The candidate's genuine motivation is the one thing the pipeline must never
invent. It comes from the candidate, via one of:

- **Per-job file `jd_texts/{job_id}_motivation.md`** — 1–3 sentences on why this
  company / problem / role pulls the candidate. Used as the basis for
  paragraph 1. This is the source of truth and persists with the job, so any
  regeneration reuses it.
- **Standing file `positioning/motivations.md`** (optional) — recurring,
  user-authored authentic themes. When no per-job file exists, the Generator MAY
  draw a human centre from here, but only if it honestly fits this specific
  company, and only from content the user wrote. Never auto-populate this file.
- **In-chat, after assets are prepared** — the user may hand the Generator a
  driving factor in conversation and ask to regenerate. The Generator first
  writes it to `jd_texts/{job_id}_motivation.md` (so it joins the record and
  future runs use it), then regenerates the cover letter and re-audits /
  re-exports. See `.claude/commands/prepare.md`.

If none exists, fall back to a role/problem-based human centre grounded in a
real, specific fact about the company — never fabricated admiration, never a JD
paraphrase.

Truth boundary: motivations are the candidate's opinions and preferences, which
the guardrails permit. Facts (employers, roles, dates, numbers, skills) still
come only from `knowledge/`.

---

## Tone registers

Pick from `jd_analysis.md` § Company signals. All registers must still pass the
read-aloud test.

### Startup / scale-up informal
- Contractions allowed ("I've", "can't"). First-person direct. Shorter, punchier
  sentences. May reference concrete tech stack or frameworks directly.

### Scale-up balanced (default)
- Professional but not stiff. Contractions sparingly. Warm.

### Corporate formal
- No contractions. No first-name-only references to the company. Complete
  sentences. Still avoid corporate-ese ("synergy", "leverage", "drive
  stakeholder value").

---

## Handling gaps

**Do not raise gaps in the cover letter.** The letter sells the human and the
strongest genuine fit; a gap belongs in `gap_suggestions.md`, not here. The old
"acknowledge and bridge" lines ("I don't have formal X, but…") read as
defensive and are removed.

**Only exception:** a gap that is (a) critical to the role AND (b) certain to be
the recruiter's first objection. Then one confident sentence, framed as
trajectory — never "I don't have X but". If the gap is genuinely disqualifying,
the Evaluator should have returned REJECT; the letter must not paper over it.

**Never:** claim experience the candidate lacks; imply skills via adjacent
phrasing ("familiar with X ecosystem" when untouched); contradict
`master_experience.md`.

---

## Anti-patterns

- Opening by paraphrasing the JD back ("The mandate you describe…", "The scope
  described – X, Y, Z…"). The reader wrote the JD; tell them something new.
- Abstraction dumps ("driver posture: one owner, minimal delegation").
- Defensive gap lines ("I don't have a formal X background, but…").
- "I'm excited to apply for…", "I've long admired [Company]…", "Your mission to
  [platitude] resonates with me…".
- Restating the CV in paragraph form.
- Opening with "My name is…" / "I am a highly motivated individual with a
  passion for…".
- Paragraphs over 120 words, or a letter that could be sent to any company in
  the cluster (swap the name and it still works → not tailored).

---

## Trace comments

- Every factual claim carries a `<!-- claims:BULLET_ID -->` trace at paragraph
  end (comma-separated if multiple bullets).
- Skill claims not tied to a specific bullet: omit the trace, or reference the
  nearest evidencing bullet ID.
- Company claims trace to the source: `<!-- claims:company:{url or "JD text"} -->`.
- The Auditor validates every trace. Any unverifiable claim halts the pipeline.
- The human-centre / motivation sentence is user-authored opinion and needs no
  factual trace, but must not contain an unevidenced factual claim.

---

## Output file structure

```markdown
# Cover Letter – {Company}, {Role}

{Date}

{Hiring manager name or "Hiring team"},

{Paragraph 1 — human centre + role}
<!-- claims:... if it carries a factual claim -->

{Paragraph 2 — proof}
<!-- claims:... -->

{Paragraph 3 — close}

Best, {first name}
```

Use the hiring manager's name if known; otherwise "Hiring team" beats "Dear
Sir/Madam". Sign-off may be "Best, {first name}" or "Best regards, {full name}"
per register.
