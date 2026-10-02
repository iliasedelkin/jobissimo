"""Agent-host parity — Claude Code and Codex run the same command files.

Claude Code loads `CLAUDE.md` (which imports `AGENTS.md`) and the slash
commands in `.claude/commands/`; Codex loads `AGENTS.md` and the skill
wrappers in `.agents/skills/`. The wrappers hold no logic, so the only thing
that can drift is the pairing itself — that is what these tests pin.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMANDS = REPO / ".claude" / "commands"
SKILLS = REPO / ".agents" / "skills"


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip().strip('"')
    return out


class TestAgentParity(unittest.TestCase):
    def test_every_command_has_a_codex_skill_and_vice_versa(self):
        commands = {p.stem for p in COMMANDS.glob("*.md")}
        skills = {p.parent.name for p in SKILLS.glob("*/SKILL.md")}
        self.assertTrue(commands, "no command files found")
        self.assertEqual(commands - skills, set(),
                         "commands without a .agents/skills wrapper")
        self.assertEqual(skills - commands, set(),
                         "skill wrappers without a .claude/commands file")

    def test_wrappers_point_at_their_command_file(self):
        for skill in SKILLS.glob("*/SKILL.md"):
            name = skill.parent.name
            with self.subTest(skill=name):
                text = skill.read_text(encoding="utf-8")
                fm = frontmatter(text)
                self.assertEqual(fm.get("name"), name)
                self.assertTrue(fm.get("description"), "empty description")
                self.assertIn(f".claude/commands/{name}.md", text)
                self.assertTrue((COMMANDS / f"{name}.md").exists())

    def test_codex_rules_mirror_the_claude_allowlist(self):
        settings = json.loads(
            (REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
        claude = set()
        for entry in settings["permissions"]["allow"]:
            m = re.fullmatch(r"Bash\((.*?)(?: \*)?\)", entry)
            if m:
                claude.add(tuple(m.group(1).split()))
        rules = (REPO / ".codex" / "rules" / "jobissimo.rules").read_text(
            encoding="utf-8")
        codex = {tuple(json.loads(p)) for p in re.findall(
            r'prefix_rule\(pattern = (\[.*?\]), decision = "allow"\)', rules)}
        self.assertTrue(claude, "no Bash allowlist entries parsed")
        self.assertEqual(claude, codex,
                         ".codex/rules and .claude/settings.json drifted")

    def test_claude_md_imports_the_agents_contract(self):
        claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("@AGENTS.md", claude)
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## Invariants (non-negotiable)", agents)


if __name__ == "__main__":
    unittest.main()
