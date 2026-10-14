"""docs/upgrading.md stays true as the engine moves.

- every schema version db.py can import has a notes entry, newest first, and
  the newest is the version db.py writes — a schema bump without upgrade
  notes fails here;
- every script command, subcommand, slash command and CSV file the notes
  name still exists;
- the page stays linked from the places people look;
- machine-local files are git-ignored by the workspace template, so an
  upgrade never syncs them;
- `sync.py pull` points at the notes when the engine moved, and explains the
  merged-and-deleted-branch case instead of calling it a divergence.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, make_workspace, run_script

sys.path.insert(0, str(REPO / "scripts"))
import db  # noqa: E402
import paths  # noqa: E402
import sync  # noqa: E402

NOTES = REPO / "docs" / "upgrading.md"


def code_spans(text: str) -> list:
    """Inline `code` and fenced blocks: where commands are named."""
    blocks = re.findall(r"```.*?\n(.*?)```", text, re.S)
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S))
    return blocks + inline


class TestNotesMatchTheCode(unittest.TestCase):
    def setUp(self):
        self.text = NOTES.read_text(encoding="utf-8")

    def test_every_importable_schema_has_notes_newest_first(self):
        self.assertEqual(max(db.IMPORTABLE_SCHEMAS), db.SCHEMA_VERSION,
                         "db.py must be able to import what it writes")
        found = [int(v) for v in re.findall(r"(?m)^### Schema v(\d+)\b", self.text)]
        self.assertEqual(sorted(found, reverse=True), found, "notes are newest first")
        missing = set(db.IMPORTABLE_SCHEMAS) - set(found)
        self.assertFalse(missing, f"docs/upgrading.md has no '### Schema v…' entry for {sorted(missing)}")
        self.assertEqual(found[0], db.SCHEMA_VERSION,
                         f"schema v{db.SCHEMA_VERSION} is current: give it the first upgrade-notes entry")

    def test_named_script_commands_exist(self):
        checked = 0
        for span in code_spans(self.text):
            for m in re.finditer(r"(?:scripts/)?\b([a-z_]+)\.py((?: [a-z][a-z-]*)*)", span):
                script = REPO / "scripts" / f"{m.group(1)}.py"
                self.assertTrue(script.exists(), f"upgrading.md names scripts/{m.group(1)}.py")
                words = m.group(2).split()
                res = subprocess.run([sys.executable, str(script), *words, "--help"],
                                     capture_output=True, text=True, cwd=REPO, timeout=60)
                self.assertEqual(res.returncode, 0,
                                 f"`{m.group(1)}.py {' '.join(words)}` no longer exists:\n{res.stderr[-400:]}")
                checked += 1
        self.assertGreater(checked, 5, "the parser found the commands")

    def test_named_slash_commands_exist(self):
        names = set()
        for span in code_spans(self.text):
            names |= set(re.findall(r"(?:^|\s)/([a-z]+)\b", span))
        names |= set(re.findall(r"`/([a-z]+)", self.text))
        self.assertIn("sync", names)
        for n in names:
            self.assertTrue((REPO / ".claude" / "commands" / f"{n}.md").exists(), f"/{n}")

    def test_named_csv_files_are_written_by_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_workspace(Path(tmp), with_apps=False)
            run_script("db.py", "init", env=env)
            res = run_script("db.py", "export-csv", env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            written = {p.name for p in (Path(env["JOBISSIMO_HOME"]) / "state" / "backup").iterdir()}
        named = set(re.findall(r"\b([a-z_]+\.csv)\b", self.text))
        self.assertTrue(named)
        self.assertFalse(named - written, f"upgrading.md names CSVs export-csv does not write: {named - written}")

    def test_the_page_is_linked_where_people_look(self):
        for rel in ("README.md", "docs/getting-started.md", "docs/sync.md", ".claude/commands/sync.md",
                    "AGENTS.md"):
            self.assertIn("upgrading.md", (REPO / rel).read_text(encoding="utf-8"), rel)


class TestMachineLocalFilesStayLocal(unittest.TestCase):
    def test_local_dir_is_ignored_by_the_workspace_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: os.environ.get(k) for k in ("JOBISSIMO_HOME", "JOBISSIMO_CONFIG")}
            os.environ["JOBISSIMO_HOME"] = tmp
            os.environ.pop("JOBISSIMO_CONFIG", None)
            try:
                rel = paths.local_dir().relative_to(paths.home()).as_posix()
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        ignore = (REPO / "templates" / "workspace.gitignore").read_text(encoding="utf-8")
        self.assertIn(f"{rel}/", ignore.splitlines(), "the UI's state file and run preferences would be synced")
        self.assertIn("state/*.db", ignore.splitlines())


class TestPullPointsAtTheNotes(unittest.TestCase):
    """sync.py pull against a real (local, bare) remote."""

    def git(self, repo, *args, check=True):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.origin, self.engine, self.other = t / "origin.git", t / "engine", t / "other"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        for clone in (self.other, self.engine):
            subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True, capture_output=True)
            for k, v in (("user.name", "T"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
                self.git(clone, "config", k, v)
        (self.other / "docs").mkdir()
        (self.other / "docs" / "upgrading.md").write_text("# Upgrading\n")
        self.git(self.other, "add", "-A")
        self.git(self.other, "commit", "-q", "-m", "seed")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")
        self.git(self.engine, "pull", "-q", "origin", "main")
        self.git(self.engine, "branch", "-q", "--set-upstream-to=origin/main", "main")
        self._save = (sync.ENGINE, sync.WORKSPACE, sync.DB_PATH)
        sync.ENGINE, sync.WORKSPACE, sync.DB_PATH = self.engine, t / "no-workspace", t / "no.db"

    def tearDown(self):
        sync.ENGINE, sync.WORKSPACE, sync.DB_PATH = self._save
        self.tmp.cleanup()

    def pull(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sync.cmd_pull(object())
        return code, out.getvalue()

    def push_change(self, path, text):
        f = self.other / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        self.git(self.other, "add", "-A")
        self.git(self.other, "commit", "-q", "-m", f"change {path}")
        self.git(self.other, "push", "-q", "origin", "HEAD:main")

    def test_engine_update_says_whether_the_notes_changed(self):
        self.push_change("scripts/x.py", "print(1)\n")
        code, out = self.pull()
        self.assertEqual(code, 0, out)
        self.assertIn("no new upgrade notes", out)
        self.push_change("docs/upgrading.md", "# Upgrading\n\n### Schema v9\n")
        code, out = self.pull()
        self.assertEqual(code, 0, out)
        self.assertIn("upgrade notes changed", out)

    def test_merged_and_deleted_branch_is_explained(self):
        self.git(self.engine, "checkout", "-q", "-b", "feat/x")
        self.git(self.engine, "push", "-q", "-u", "origin", "feat/x")
        self.git(self.other, "push", "-q", "origin", "--delete", "feat/x")
        code, out = self.pull()
        self.assertEqual(code, 1)
        self.assertIn("gone from the remote", out)
        self.assertIn("checkout main", out)
        self.assertNotIn("Divergence", out)


if __name__ == "__main__":
    unittest.main()
