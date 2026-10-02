# Running Jobissimo with Codex

Jobissimo was built in Claude Code, but nothing in the pipeline depends on it:
the judgement lives in plain-markdown command files, and everything that must
be exact lives in stdlib Python scripts. Codex runs the same files. This page is
the Codex-specific detail; for the full first-time walkthrough (either agent)
start with [getting-started.md](getting-started.md).

## How Codex finds the pipeline

| Claude Code | Codex | Same content? |
|---|---|---|
| `CLAUDE.md` (a one-line `@AGENTS.md` import) | `AGENTS.md`, loaded automatically | yes — `AGENTS.md` is the contract |
| `/hunt` → `.claude/commands/hunt.md` | `$hunt` → `.agents/skills/hunt/SKILL.md` → reads `.claude/commands/hunt.md` | yes — the skill is a pointer, not a copy |
| `.claude/settings.json` allowlist | `.codex/rules/jobissimo.rules` (shipped; loads once the project is trusted) | yes — kept in sync by a test |
| `claude-in-chrome` browse adapter | `codex-chrome` browse adapter | same capabilities and field notes |

The command files stay the single source of truth. Codex skill wrappers never
hold logic, so a change to a command reaches both agents at once.

## One-time setup

### 1. Install and open the repo

Use the Codex CLI (`npm install -g @openai/codex`, `brew install --cask codex`,
or `curl -fsSL https://chatgpt.com/codex/install.sh | sh`) or Codex in the
ChatGPT desktop app. **Only the desktop app has the browser integration**, so
pick it if you want logged-in browsing. Work **from the repo root** so that
`AGENTS.md` and `.agents/skills/` are picked up:

```sh
cd jobissimo
codex
```

Trust the project when Codex asks. Project-local rules under `.codex/` load
only for a trusted project.

### 2. Let Codex write to your workspace and reach the network

Codex's default sandbox (`workspace-write`) allows writes only inside the
current directory and blocks network access from the shell. Jobissimo needs
both of those in two cases:

- **Your workspace is outside the repo.** That is the case after `/sync init`,
  which writes the `.jobissimo` pointer. Run `python3 scripts/paths.py` to see
  the resolved `$JOBISSIMO_HOME`. A workspace left at the default
  `./profile` is inside the repo and needs no extra write access.
- **Network from the shell.** The `webfetch` adapter (`curl` against the
  public Ashby / Greenhouse / Lever APIs), `/refresh` against those APIs, and
  `/sync push|pull` all need it.

Add this to your **personal** `~/.codex/config.toml`:

```toml
[sandbox_workspace_write]
writable_roots = ["/absolute/path/to/your/jobissimo-workspace"]
network_access = true
```

Or grant the workspace for a single session: `codex --add-dir /absolute/path/to/workspace`.
Restart Codex after editing the config. On macOS, if `curl` still fails inside
Codex with `network_access = true`, see
[openai/codex#10390](https://github.com/openai/codex/issues/10390). `/setup`
probes the network and falls back to pasted URLs when it is unreachable.

On a brand-new install the workspace does not exist yet: `$setup` creates it
first, through `/sync init`, as a sibling directory by default. Put that
intended path in `writable_roots` **before** running `$setup`. Otherwise Codex
asks for approval on every write into it.

Do **not** commit a `.codex/config.toml` with the path into this repo. The
path is per-machine, and `scrub_check.py` treats home-directory paths as
personal data.

### 3. Approval prompts for the pipeline scripts — already handled

`.codex/rules/jobissimo.rules` ships with the repo. It mirrors the
`.claude/settings.json` allowlist (`python3 scripts/db.py`, `audit.py`, … —
`sync.py` deliberately excluded, since it pushes to a remote), and Codex loads
it once you trust the project. `tests/test_agents.py` fails if the two lists
drift.

### 4. Browser (optional, desktop app only)

The Codex browser integration is not available in the Codex CLI or IDE
extension. In the ChatGPT desktop app:

1. Open **Computer Use**, select your browser (Chrome, Edge, Brave, Opera, or
   Vivaldi), choose **Install**, add the ChatGPT extension from the store
   page, and accept its permission prompts.
2. Back in **Computer Use**, the browser should show **Manage**.
3. In the chat, @-mention the browser (e.g. `$hunt @Chrome`) so Codex drives
   it. Use the browser profile the extension is installed in.

That is the `codex-chrome` adapter (`engine/adapters/browse/codex-chrome.md`).
A domain the extension refuses is logged as `permission_denied`, never as a
dead board. Docs: [Browser extension](https://developers.openai.com/codex/app/chrome-extension).

Headless alternative (also works in the CLI, no logged-in sessions):
`codex mcp add playwright npx "@playwright/mcp@latest"` (Node.js 18+).

No browser is fine. `/setup` records `webfetch` (if the shell has network) or
`manual`, and the whole prepare → audit → score → export chain works the same.

### 5. Mail (optional)

The mail adapters are read-only by contract, and the account guard checks the
connected mailbox against `config/pipeline.yaml → mail.account` before reading
anything.

- **Gmail plugin** (`gmail-mcp` contract): install **Gmail** from the plugin
  directory (desktop app, or "Install plugin" in the CLI) and connect the
  mailbox that gets your job alerts. The plugin can also archive or trash
  mail; the pipeline never asks it to.
- `imap` — only if the session already has IMAP tooling; no helper ships yet.
- `none` — job-alert digests are skipped, and everything else runs.

## Using it

Type the command with a `$` instead of a `/`. Arguments work the same way:

```
$setup                         # first run: documents first, then a first result
$hunt                          # find, score, record
$prepare 0123                  # evidence map → drafts → audit → ATS → export
$apply 0123                    # assisted form-fill; stops before submit
$track got a rejection from Acme
$cycle                         # the daily pass: reconcile → hunt → prepare → report
$dashboard  $enrich  $refresh  $optimise  $doctor  $sync
```

Plain language works too ("prepare job 0123"): every skill's description names
its command, so Codex can match the request to a skill without the `$`.

### Unattended runs

```sh
codex exec --sandbox workspace-write '$cycle'
```

Run it from the repo root. A CLI run has no browser integration, so
`/cycle`'s browser probe fails fast: the hunt runs on `webfetch` and mail, and
preparation is unaffected. `/cycle`'s lock, time budget, and starvation checks
work the same way under any scheduler. Read `docs/scheduling.md` before you
cron it.

## Differences from Claude Code

- **Questions arrive as plain chat.** Codex has no multiple-choice question
  tool. Commands that ask (`/setup`, `/enrich`, `/optimise`, `/apply`) ask in
  chat and wait for your answer.
- **The browser plugin has its own confirmations.** The Codex Chrome plugin
  asks before it types personal data into a form. `/apply` still stops before
  submit with a screenshot and a field-by-field summary. **No autonomous
  submission in either agent** (invariant 5).
- **Field notes are shared.** The LinkedIn and alert-digest recipes are
  written once, in `claude-in-chrome.md`. `codex-chrome.md` maps its tool
  names onto that file.
- **The guardrails are identical.** `audit.py` is the same hard gate, the
  same scripts write the DB, and none of this is configurable in either agent.

## For contributors

A new command needs both `.claude/commands/<name>.md` and a wrapper at
`.agents/skills/<name>/SKILL.md`. Copy an existing wrapper and change the name,
description, and path. `tests/test_agents.py` fails if either one is missing.
