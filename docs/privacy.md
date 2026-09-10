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

It is a tripwire, not a guarantee — review your diffs before publishing a
fork regardless.

## If you fork and publish

Never graft this project's private predecessor history, and never commit your
own `config/` or `profile/`. Keep the two `.gitignore` rules. Run
`scrub_check.py --all` before your first push.
