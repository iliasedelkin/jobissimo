# Getting started

Everything a brand-new user needs, from an empty machine to a first audited
CV, in either agent. Steps 1–3 and 6 are required; the browser (4) and mail (5)
are optional — without them discovery runs on public ATS job-board APIs and
pasted URLs, and preparing applications is unaffected.

Each agent-specific step is split into **Claude Code** and **Codex**. Use the
one you run.

## 1. Install the basics

**Python 3** (standard library only) and **git** are required. For DOCX
export you also need **pandoc**, plus an optional PDF engine:

| Platform | DOCX | PDF (optional) |
|---|---|---|
| macOS | `brew install pandoc` | `brew install tectonic` |
| Debian/Ubuntu | `sudo apt install pandoc` | `sudo apt install texlive-xetex` |
| Windows | `winget install JohnMacFarlane.Pandoc` | `winget install tectonic` |

`/setup` checks these itself and repeats the install line if anything is
missing, so you can also skip this and let it tell you.

## 2. Install your agent

**Claude Code** — needs a Pro, Max, Team, Enterprise, or Console account:

```sh
curl -fsSL https://claude.ai/install.sh | bash      # macOS / Linux / WSL
# or: brew install --cask claude-code   ·   winget install Anthropic.ClaudeCode
claude --version
```

Then run `claude` once and log in. **Log in with your claude.ai account,
not an API key**, if you want the browser or Gmail connector: both work only
with a claude.ai subscription login.

**Codex** — needs a ChatGPT plan with Codex:

```sh
npm install -g @openai/codex
# or: brew install --cask codex   ·   curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
```

Or install the **ChatGPT desktop app** and use Codex from there. **The
browser integration works only in the desktop app, not in the Codex CLI**
(step 4). Pick the desktop app if you want logged-in browsing.

## 3. Get the engine and start it

```sh
git clone https://github.com/iliasedelkin/jobissimo.git
cd jobissimo
python3 scripts/scrub_check.py --install-hook          # PII pre-commit gate
python3 -m unittest discover -s tests -p 'test_*.py'   # optional: offline check
```

**Claude Code:** run `claude` from the repo root. The repo ships its
permissions in `.claude/settings.json` (the pipeline scripts run without
prompts), and the commands appear as `/setup`, `/hunt`, …

**Codex:** run `codex` from the repo root (or open the folder as a project
in the desktop app) and **trust the project** when asked. Trust is what loads
the repo's own rules in `.codex/rules/jobissimo.rules`, the equivalent of
`.claude/settings.json`. The commands are skills: `$setup`, `$hunt`, …
(type `$` to see them, or `/skills`).

### Codex only: give it your workspace and the network

Your personal data lives in a **workspace** separate from this repo. `/setup`
creates it as its first step, by running `/sync init`. The recommended layout
is a sibling directory, e.g. `../jobissimo-workspace`. Codex's default sandbox
writes only inside the folder you opened and blocks network access from the
shell, so before `$setup`, add this to your personal `~/.codex/config.toml`
(never commit it — the path is yours):

```toml
[sandbox_workspace_write]
writable_roots = ["/absolute/path/to/jobissimo-workspace"]   # where your workspace will live
network_access = true                                        # ATS-API fetches, /sync push
```

Restart Codex after editing it. Without it Codex still works, but asks for
approval every time it writes into the workspace. On macOS, if `curl` still
fails inside Codex with `network_access = true`, see
[openai/codex#10390](https://github.com/openai/codex/issues/10390). `/setup`
probes the network and falls back to pasted URLs when it is unreachable.

## 4. Browser (optional, recommended for discovery)

A browser adapter means **you, driving your own logged-in Chrome** — it can
read LinkedIn and other login-walled boards the way you see them. No captcha
bypass, ever.

**Claude Code — Claude in Chrome**
1. Install the [Claude in Chrome extension](https://chromewebstore.google.com/detail/claude/fcoeoabgfenejglbffodgkkbkcdhcgfn)
   (Chrome, Edge, or another Chromium browser).
2. Start with `claude --chrome`, or run `/chrome` and pick **Enabled by
   default**. `/chrome` shows "Status: Enabled" and "Extension: Installed"
   when it works.
3. Site access is managed in the extension's settings. A board the extension
   refuses is logged as `permission_denied` and named in the run report.
   Grant the domain and re-run.

Adapter: `claude-in-chrome`. Docs:
[Use Claude Code with Chrome](https://code.claude.com/docs/en/chrome).

**Codex — Chrome extension (desktop app only)**
1. In the ChatGPT desktop app, open **Computer Use**, select your browser,
   and choose **Install**. Add the ChatGPT extension from the store page and
   accept its permission prompts.
2. Back in **Computer Use**, the browser should show **Manage**.
3. In a Codex chat, @-mention your browser (e.g. `@Chrome`) so Codex uses it.
   Use the browser profile where the extension is installed.

Adapter: `codex-chrome`. Docs:
[Browser extension](https://developers.openai.com/codex/app/chrome-extension).

**Headless alternative (either agent): Playwright MCP.** This needs Node.js
18+. It has no logged-in sessions, so login-walled boards degrade.

```sh
claude mcp add playwright npx @playwright/mcp@latest        # Claude Code
codex mcp add playwright npx "@playwright/mcp@latest"       # Codex
```

No browser at all is a first-class path. `/setup` records `webfetch`, which
uses the public Ashby / Greenhouse / Lever APIs and company career pages. If
there is no network either, it records `manual` (you paste URLs or posting
text).

## 5. Mail (optional)

Job-alert digests are the highest-yield free source. Mail is **read-only by
contract**: the pipeline never sends, replies, labels, or deletes. Before
reading a single message, it checks that the connected mailbox is the one set
in `config/pipeline.yaml → mail.account`.

**Claude Code — Gmail connector.** Add Gmail at
[claude.ai/customize/connectors](https://claude.ai/customize/connectors) and
authenticate there; Gmail can't be connected from inside Claude Code. It then
appears in Claude Code's `/mcp` list, as long as you logged in with your
claude.ai account. Adapter: `gmail-mcp`.

**Codex — Gmail plugin.** Open the plugin directory (the desktop app, or
"Install plugin" in the CLI), install **Gmail**, and connect your account when
prompted. Adapter: `gmail-mcp` (same read-only contract and account guard).
The plugin can also archive and trash mail, but the pipeline never asks it to.

**Connect the mailbox that receives your job alerts.** A dedicated mailbox
that you forward job mail to works well. `/setup` writes it to `mail.account`.

**IMAP** (`imap` adapter) is for hosts with no Gmail tool. No IMAP helper
ships with the engine yet, so it only works if your agent session already has
IMAP tooling. Otherwise choose `none`: mail phases are skipped and everything
else runs.

## 6. First run

```
/setup        # Claude Code
$setup        # Codex
```

`/setup` does the rest, in order:

1. Establishes your private workspace via `/sync init`.
2. Probes what this session can do and records it in
   `config/capabilities.yaml`.
3. Asks for your documents (every CV you have, a LinkedIn export, old cover
   letters).
4. Shows what it extracted and asks you only to correct it.
5. Generates a truth-audited, ATS-scored CV and cover letter against a sample
   posting.

That takes about fifteen minutes with one decent CV.

## 7. Check it works

```
/doctor   ·   $doctor          # config health, recorded capabilities, drift
/dashboard   ·   $dashboard    # the (empty) pipeline
```

If the browser or mail tool was set up after `/setup`, ask `/doctor` to
re-record capabilities. Then the daily loop is `/hunt` → `/prepare <job_id>`
→ `/apply <job_id>` → `/track …`, or `/cycle` for all of it in one pass (the
`$` forms in Codex).

## What lives where

| Thing | Location | Committed to |
|---|---|---|
| Engine (this repo) | your clone | the public repo (contributions only) |
| Your data, config, generated CVs | the workspace (`python3 scripts/paths.py`) | your own private repo, via `/sync` |
| Claude Code permissions | `.claude/settings.json` (shipped), `.claude/settings.local.json` (yours) | shipped / never |
| Codex rules and sandbox | `.codex/rules/` (shipped), `~/.codex/config.toml` (yours) | shipped / never |

More: [codex.md](codex.md) (Codex specifics) · [sync.md](sync.md) (workspace
and backup) · [adapters.md](adapters.md) · [scheduling.md](scheduling.md).
