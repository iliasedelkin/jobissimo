# The local UI

```bash
python3 scripts/launcher.py open   # what the Jobissimo app runs: reuse or start, then open
python3 scripts/ui.py              # the same from a terminal: prints a one-time link and opens it
python3 scripts/ui.py --no-open --port 8765
```

A small web app for the parts of Jobissimo that are easier to see than to ask
about: where every application stands, what the system knows about you, how
the pipeline is configured, and how your search converts. It runs on
`127.0.0.1` from the standard library — no install, no build, no network.

Agents still do the work (`/hunt`, `/prepare`, `/cycle` in Claude Code or
Codex) — started from the chat or from the UI. The UI shows the state,
explains it, and takes the decisions that are yours: recording what
happened, accepting or rejecting knowledge, approving suggestions, changing a
setting with a reason, and answering a run's questions.

## Screens

| Screen | For |
|---|---|
| **Get started** | Shown until /setup is complete: your agent and its sign-in, tools, your documents (drag them in), /setup in the run panel, a first /hunt |
| **Overview** | What needs you now (offers, follow-ups, the ready queue, inbox), three numbers for the week, live processes, the top insights |
| **Applications** | Every posting by stage, with a detail panel: properties, rounds, the requirements matched, the knowledge each CV cited, the timeline, and the actions (mark applied, record a reply or round, settle a round, close) |
| **Knowledge** | *Inbox* of agent proposals; *Experience* — every achievement with its source, its usage across applications and, once 8+ sent applications cite it, its reply rate vs your average; *Skills*; *Gaps* — requirements jobs keep asking for that you have no evidence for |
| **Pipeline** | The stages and the command that moves each, suggested changes, recent runs (including runs that never logged an end), the settings with their reasons, sources, change history, and the guarantees that are not settings |
| **Analytics** | The funnel as a story, applications per week, reply rates by source / fit / ATS score / positioning / language with 95% intervals, time to reply, rounds |
| **Settings** | Agents and their sign-in, what runs may do without asking, run preferences, local tools — each problem with its fix |

## Opening it without a terminal

`install.sh` (or `python3 scripts/launcher.py install-app`, or *Settings →
This computer*) adds a **Jobissimo app**: `~/Applications/Jobissimo.app` on
macOS, an app-menu entry on Linux. Opening it reuses the UI already serving
your workspace, or starts one in the background, and opens the browser
signed in. A UI the app started stops by itself after 30 minutes with no page
open and no run going (an open page pings once a minute). *Quit* in the
sidebar stops it — and any runs, after asking. *Start at login* (Settings)
keeps one running in the background from login.

The app is generated on your machine, so macOS has nothing to quarantine. It
carries the Python and PATH of the shell that created it, and
`JOBISSIMO_HOME`/`JOBISSIMO_CONFIG` if that shell set them (a scratch copy);
otherwise the engine's `.jobissimo` pointer finds your workspace. Re-add it
after moving things. Its state — the running server's port, pid and sign-in
token, run preferences, the log — lives in the workspace's `config/local/`,
owner-only and never synced.

## Running commands

The UI can start a command in **your own** Claude Code or Codex — the CLI you
already use, logged in with your account, on this machine (pick one under
*Run with* in the sidebar, or on Settings). Wherever the UI shows a command —
`/prepare <job>`, `/hunt`, `/enrich`, an insight's lever — the chip runs it.
`/sync` stays a chip you copy into the chat.

**Applying.** Each posting in Applications shows its next action: *Prepare*
(runs `/prepare`) until its application folder exists, then *Assets* (opens
the folder in Finder / your file manager), and *Apply* once it is ready. The
Ready list and the Overview's ready card offer *Apply to these* — one run,
up to ten postings, oldest first. `/apply` runs in Claude Code with your
Chrome: it fills each form from your verified answers, then stops and asks in
the run panel with a field-by-field summary — *I'll click submit myself*,
*Click submit for me*, *Change something*, *Don't submit*. Only your answer
submits; a skipped or unanswered question leaves the posting ready. After a
run that prepared or applied, the panel links each application folder. `/setup` runs from *Get started*:
documents you drag in there are converted by `intake.py` into `_intake/`
before it starts, so it begins with your files already read.

A panel in the corner shows the runs. Collapsed, it is a status line.
Expanded, it is each run's activity as it happens — its thinking (folded),
its messages, every command it ran and file it read or edited, each with its
output one click away, links you can open — with a tab per run.

**When the agent needs you, it asks in the panel.**

| | Claude Code | Codex |
|---|---|---|
| A question (an audit's fix / bypass / halt, a missing fact) | asked live: options to pick, or type your own answer | ends its turn with the question; you reply |
| A permission it doesn't have (a web page, a command outside the allowlist, a file outside the workspace) | asked live: *Allow once*, *Always allow* (saved to `.claude/settings.local.json`), *Deny* with an optional note | the sandbox decides: network and web search are settings |
| After the run | reply to continue the same session (`claude --resume`) | reply to continue (`codex exec resume`) |

A question nobody answers times out (30 minutes by default) to the safe
default — halt the item, never bypass, never submit, never accept a
knowledge proposal — and the run carries on. Some requests are refused
without asking: starting another agent, opening the UI, editing agent
settings. Edits without asking stop at the workspace; anything else asks.

**Several runs can go at once** (three by default). Commands that touch the
same things never overlap — two `/hunt`s, `/hunt` and `/refresh` (one
browser), `/cycle` and anything it runs, two `/prepare`s of the same job — so
a second one is refused with the reason; everything else runs side by side.
Stop ends a run and its child processes. Each turn logs `agent_run_started` /
`agent_run_finished` and keeps its raw transcript in `state/agent_runs/`
(git-ignored).

## Settings

What runs can use on this machine, checked live (`scripts/agent_setup.py
check`), with a fix next to each problem:

- **Agents** — installed, signed in (Claude's plan and the connectors it
  sees: Chrome, Gmail — read from the CLI without spending a token), Codex
  login and whether it trusts this repo (*Trust* adds it to
  `~/.codex/config.toml`).
- **What runs may do without asking** — reading web pages (ask / job sites /
  any site), web search, your Chrome, reading Gmail (never sending). These
  are Claude Code permission rules in its own `.claude/settings.local.json`,
  so they apply in the chat too.
- **Run preferences** — Claude model and effort, whether browser commands
  start with Chrome, Codex reasoning effort, network and web search, runs at
  once, how long a question waits. Stored per machine in
  `config/local/agents.json`, never synced.
- **Tools** — Pandoc, a PDF engine, Poppler, Tesseract; a missing one installs
  with Homebrew, its output shown in the run panel.

Codex reads `~/.codex/config.toml` for its model; a high reasoning effort
makes even a short command take minutes — Settings can lower it for UI runs
only.

## How it stays honest

- **Reads** go through `scripts/readmodel.py`, which opens the database
  read-only and reuses db.py's own funnel functions — the UI and
  `db.py dashboard` cannot disagree.
- **Writes** are subprocess calls to `db.py`, `knowledge.py` and `config.py`,
  the same CLIs the agents use. A transition db.py refuses is refused in the
  UI with db.py's message. There is no submit, no audit bypass, no forced
  transition (AGENTS.md invariant 12).
- **Knowledge** changes you make are written through the inbox and accepted
  in the same step, so every change has a record (`knowledge/_inbox.json`)
  and provenance (`<!-- from:USER#INB-… -->`). Agent proposals wait for you.
  Retiring an achievement keeps it for the applications that used it; the
  audit stops new CVs citing it. Marking a duplicate never merges text.
- **Settings** change one value at a time and need a reason; the change, the
  reason and the config revision before/after are logged (`config_changed`).
- **Statistics** carry their sample size. Rates come with a Wilson 95%
  interval; groups under 8 are muted; a per-achievement reply comparison only
  appears when its interval excludes your average, and is labelled a
  correlation.

## Security

The server binds to `127.0.0.1` only and refuses requests for any other
`Host` (DNS rebinding). The printed link carries a per-launch token that is
exchanged for an `HttpOnly`, `SameSite=Strict` cookie; every API call needs
it, every write also needs a CSRF token and a same-origin `Origin`. A strict
Content-Security-Policy allows only the app's own scripts and styles. It logs
no requests.
