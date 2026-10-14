"""knowledge.py — the inbox is the only way in, edits are surgical, and a
retired bullet can no longer be cited (audit.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import EN_APP, make_workspace, run_script


class TestKnowledge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = make_workspace(Path(self.tmp.name))
        self.home = Path(self.env["JOBISSIMO_HOME"])
        self.master = self.home / "knowledge" / "master_experience.md"
        self.original = self.master.read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def kb(self, *args):
        return run_script("knowledge.py", *args, env=self.env)

    def propose(self, op, target, payload, by="user"):
        res = self.kb("propose", "--op", op, "--target", target, "--payload", json.dumps(payload), "--by", by)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout.split()[1].rstrip(":")

    def test_proposal_changes_nothing_until_accepted(self):
        item = self.propose("add_fact", "FERN-PM-003", {"fact": "Outcome: triage time down from 5 days to 2"},
                            by="20300115_120000_enrich")
        self.assertEqual(self.master.read_text(encoding="utf-8"), self.original)
        pending = json.loads(self.kb("inbox").stdout)
        self.assertEqual([i["id"] for i in pending], [item])
        res = self.kb("decide", item, "accept")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(self.kb("inbox").stdout), [])

    def test_accept_edits_only_the_target_block(self):
        item = self.propose("add_fact", "FERN-PM-003", {"fact": "Outcome: triage time down from 5 days to 2"})
        self.kb("decide", item, "accept")
        before, after = self.original.splitlines(), self.master.read_text(encoding="utf-8").splitlines()
        added = [ln for ln in after if ln not in before]
        self.assertEqual(added, ["  - Outcome: triage time down from 5 days to 2",
                                 f"<!-- from:USER#{item} -->"])
        self.assertTrue(all(ln in after for ln in before), "an existing line was changed or lost")

    def test_reject_needs_a_reason(self):
        item = self.propose("add_phrasing", "FERN-PM-001", {"phrasing": "Something new."})
        self.assertEqual(self.kb("decide", item, "reject").returncode, 1)
        self.assertEqual(self.kb("decide", item, "reject", "--reason", "not my wording").returncode, 0)
        self.assertEqual(self.master.read_text(encoding="utf-8"), self.original)

    def test_add_bullet_gets_next_id_and_provenance(self):
        item = self.propose("add_bullet", "FERN-PM", {"role_id": "FERN-PM", "facts": ["Ran pricing tests",
                                                                                     "Outcome: 3 experiments shipped"],
                                                      "tags": ["PRODUCT"]})
        res = self.kb("decide", item, "accept")
        self.assertIn("FERN-PM-005", res.stdout)
        roles = json.loads(self.kb("list").stdout)
        new = next(b for r in roles for b in r["bullets"] if b["id"] == "FERN-PM-005")
        self.assertEqual(new["provenance"], [f"USER#{item}"])
        self.assertEqual(new["meta"]["status"], "verified")

    def test_mark_duplicate_never_merges_text(self):
        orig = {b["id"]: b for r in json.loads(self.kb("list").stdout) for b in r["bullets"]}
        item = self.propose("mark_duplicate", "FERN-PM-004", {"of": "FERN-PM-002"})
        self.kb("decide", item, "accept")
        bullets = {b["id"]: b for r in json.loads(self.kb("list").stdout) for b in r["bullets"]}
        self.assertEqual(bullets["FERN-PM-004"]["meta"]["status"], "deprecated")
        self.assertEqual(bullets["FERN-PM-004"]["meta"]["merged_into"], "FERN-PM-002")
        self.assertEqual(bullets["FERN-PM-002"]["facts"], orig["FERN-PM-002"]["facts"])
        self.assertEqual(bullets["FERN-PM-004"]["facts"], orig["FERN-PM-004"]["facts"])

    def test_deprecated_bullet_fails_the_audit(self):
        folder = f"applications/{EN_APP}"
        self.assertEqual(run_script("audit.py", "--folder", folder, env=self.env).returncode, 0)
        item = self.propose("deprecate", "FERN-PM-001", {"reason": "superseded"})
        self.kb("decide", item, "accept")
        res = run_script("audit.py", "--folder", folder, env=self.env)
        self.assertEqual(res.returncode, 1)
        self.assertIn("deprecated bullet FERN-PM-001", res.stdout)
        # a historical folder can still be re-audited explicitly
        self.assertEqual(run_script("audit.py", "--folder", folder, "--allow-deprecated",
                                    env=self.env).returncode, 0)
        # and restoring makes it citable again
        item = self.propose("restore", "FERN-PM-001", {})
        self.kb("decide", item, "accept")
        self.assertEqual(run_script("audit.py", "--folder", folder, env=self.env).returncode, 0)
        self.assertEqual(self.master.read_text(encoding="utf-8"), self.original)

    def test_unknown_targets_refused(self):
        res = self.kb("propose", "--op", "add_fact", "--target", "NOPE-001", "--payload", '{"fact":"x"}', "--by", "user")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Unknown bullet", res.stderr)


if __name__ == "__main__":
    unittest.main()
