# Privacy

Jobissimo is a single-user, local tool. Your career data never leaves your
machine except to the job boards and mailbox you explicitly point it at.

## Where personal data lives

Everything personal is under two gitignored roots:

- **`config/`** — this install's identity, targets, languages, boards (only
  `config/*.example.yaml` is committed).
- **`profile/` (`$JOBISSIMO_HOME`)** — the entire knowledge base, positioning,
  JDs, application folders, run reports, and the SQLite DB.

`.gitignore` enforces this with two rules (`/profile/` and `/config/*.yaml`
except examples), so the personal-data boundary is mechanical, not a habit.

## No uploads, no telemetry

The pipeline makes no network call the user did not initiate. There is no
analytics, no phone-home, no external service. Mail is **read-only** by
contract — nothing is sent, replied to, labelled, or deleted — and the mail
account guard verifies the connected mailbox matches your configured account
before reading a single message.

## The scrub gate

`scripts/scrub_check.py` is installed as a `.git/hooks/pre-commit` hook
(`scrub_check.py --install-hook`) and refuses any commit containing
personal-looking data: emails outside allowlisted example domains,
phone-shaped numbers (except reserved fictional `555` ranges), LinkedIn
profile handles, and pipeline job-ids. It also carries a hashed denylist (the
repo stores only SHA-256 hashes of known-personal tokens, never the strings).
CI re-runs `scrub_check.py --all` over the whole working tree **and the full
git history** on every push.

### Outbound text: issues, PRs, comments

Identifier patterns cannot see the main risk in an issue or PR body: true
numbers with the names stripped out ("64 applied → 28 responded", a pass-rate
table, an offer figure). They describe your job search as surely as your name
would. The rule (AGENTS.md invariant 11) is absolute: nothing derived from
your workspace goes out, anonymised or not. Evidence is the engine `file:line`
plus a synthetic-fixture reproduction with obviously fictional values.

`scrub_check.py --outbound <body-file>` enforces this with two more layers:

- **Workspace fingerprint.** The real values on this machine, read through
  `db.py export-csv`: every pipeline date, the companies you applied to or
  heard from, aggregate job counts (>= 10), and amounts (>= 1000) from stage
  logs, notes, `applicant_profile.yaml` and `config/targets.yaml`. A true
  value is caught however it is dressed. Commits get the company-name and
  amount checks too, for names they newly introduce.
- **Telemetry signatures.** The *shape* of real evidence, whatever the
  values: "in one install", `N of M`, percentages, `n = N`, numeric funnels,
  and tables of bare counts. A deliberately synthetic illustration goes
  between `<!-- synthetic -->` and `<!-- /synthetic -->`. The fingerprint
  still runs inside, so the marker can never launder a real value.

In Claude Code, `.claude/settings.json` registers `scrub_check.py --gh-hook`
as a PreToolUse hook. Every `gh issue|pr create|edit|comment` (and `gh api`
write) has its title and body scanned, and the call is blocked on a finding.
A create or comment without `--body-file`/`--body` is blocked too, since an
editor-typed body cannot be checked. Codex has no hook, so there the rule and
the manual `--outbound` run carry it.

Small counts (below 10) cannot be fingerprinted without flagging every digit.
Outside a synthetic block the signatures catch their usual shapes; inside
one, the rule is the guard.

It is a tripwire, not a guarantee — review your diffs before publishing a
fork regardless.

## If you fork and publish

Never graft this project's private predecessor history, and never commit your
own `config/` or `profile/`. Keep the two `.gitignore` rules. Run
`scrub_check.py --all` before your first push.
