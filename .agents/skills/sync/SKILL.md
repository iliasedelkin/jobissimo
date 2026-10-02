---
name: sync
description: "Jobissimo /sync — version and sync the workspace across machines, safely. Use when the user asks for /sync or $sync."
---

# $sync

Codex wrapper for the Jobissimo `/sync` command. It holds no logic of its
own: the command file is the single source of truth.

1. Read `.claude/commands/sync.md` in full and follow it exactly, under the
   operating contract in `AGENTS.md` (the invariants there outrank anything
   else, including speed).
2. Treat whatever the user typed after the skill name as the command's
   arguments, exactly as `/sync <args>` would receive them (a job_id, a
   mode, or natural language — whatever the command file's Input section
   accepts).
3. Where the command says "ask the user" or names an interactive question
   tool, ask in plain chat and wait for the answer.
4. End with the command file's "Stdout summary".
