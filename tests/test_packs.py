"""Pack loader and config layering.

Covers the contract packs.py states in its own docstring — "engine defaults →
pack → config, last wins… a pack is never edited in place, a user override
lands in config/" — which the loader previously documented without
implementing (issues #10, #11).
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from helpers import REPO

sys.path.insert(0, str(REPO / "scripts"))
import packs         # noqa: E402


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


class TestWrappedInlineLists(unittest.TestCase):
    """The mini-YAML subset has to survive the pack files the repo ships:
    every competency list in packs/product/roles.yaml wraps across lines."""

    def test_wrapped_inline_list_parses_as_a_list(self):
        parsed = packs.parse_simple_yaml(textwrap.dedent("""
            clusters:
              PO:
                competencies: [backlog ownership, user stories,
                               sprint planning, prioritisation]
        """))
        comps = parsed["clusters"]["PO"]["competencies"]
        self.assertIsInstance(comps, list)
        self.assertEqual(comps[-1], "prioritisation")
        self.assertIn("sprint planning", comps)

    def test_single_line_list_still_parses(self):
        parsed = packs.parse_simple_yaml("adjacent: [PM, BA]\n")
        self.assertEqual(parsed["adjacent"], ["PM", "BA"])

    def test_shipped_product_pack_competencies_are_lists(self):
        roles = packs.load_yaml(packs.pack_dir("product") / "roles.yaml")
        for cid, body in (roles.get("clusters") or {}).items():
            with self.subTest(cluster=cid):
                self.assertIsInstance(body.get("competencies"), list)


class TestConfigLayer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = root / "config"
        self.cfg.mkdir()
        write(self.cfg / "pipeline.yaml", "pack: product\n")
        self._prev = {k: os.environ.get(k) for k in ("JOBISSIMO_CONFIG", "JOBISSIMO_HOME")}
        os.environ["JOBISSIMO_CONFIG"] = str(self.cfg)
        os.environ["JOBISSIMO_HOME"] = str(root / "profile")

    def tearDown(self):
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    # --- issue #10: overrides were documented but never read ---------------

    def test_config_keywords_file_is_read_and_extends_the_pack(self):
        names = [f.name for f in packs.keywords_files()]
        self.assertEqual(len(names), 1, "no override yet — pack only")
        write(self.cfg / "ats_keywords.yaml", """
            hard_skills:
              - figma
        """)
        self.assertEqual(len(packs.keywords_files()), 2)

    def test_config_synonyms_file_is_read(self):
        before = len(packs.synonym_files())
        write(self.cfg / "ats_synonyms.yaml", "spa: [single-page application]\n")
        self.assertEqual(len(packs.synonym_files()), before + 1)
        self.assertEqual(packs.synonym_files()[-1].parent, self.cfg.resolve())

    def test_config_cluster_carries_competencies_not_just_an_id(self):
        write(self.cfg / "roles.yaml", """
            clusters:
              Design:
                title: Product Designer
                competencies: [interaction design, design systems]
        """)
        self.assertIn("Design", packs.role_clusters())
        self.assertEqual(packs.cluster_competencies("Design"),
                         ["interaction design", "design systems"])

    def test_config_extends_a_pack_cluster_without_dropping_pack_terms(self):
        write(self.cfg / "roles.yaml", """
            clusters:
              PO:
                competencies: [domain modelling]
        """)
        comps = packs.cluster_competencies("PO")
        self.assertIn("domain modelling", comps, "config term missing")
        self.assertIn("backlog ownership", comps, "pack term was replaced, not extended")

    def test_restating_a_pack_term_in_config_does_not_duplicate_it(self):
        write(self.cfg / "roles.yaml", """
            clusters:
              PO:
                competencies: [Backlog Ownership]
        """)
        comps = [c.lower() for c in packs.cluster_competencies("PO")]
        self.assertEqual(comps.count("backlog ownership"), 1)

    def test_extra_role_clusters_still_registers_a_bare_id(self):
        write(self.cfg / "pipeline.yaml", "pack: product\nextra_role_clusters: [Design]\n")
        self.assertIn("Design", packs.role_clusters())
        self.assertEqual(packs.cluster_competencies("Design"), [])

    # --- issue #11: shared competencies across overlapping clusters --------

    def test_common_competencies_merge_into_every_cluster(self):
        write(self.cfg / "roles.yaml", """
            common:
              competencies: [written communication]
            clusters:
              Design:
                competencies: [interaction design]
        """)
        for cid in packs.role_clusters():
            with self.subTest(cluster=cid):
                self.assertIn("written communication", packs.cluster_competencies(cid))

    def test_common_is_not_itself_a_cluster(self):
        write(self.cfg / "roles.yaml", """
            common:
              competencies: [written communication]
        """)
        self.assertNotIn("common", packs.role_clusters())

    def test_common_precedes_cluster_specific_terms(self):
        write(self.cfg / "roles.yaml", """
            common:
              competencies: [written communication]
            clusters:
              Design:
                competencies: [interaction design]
        """)
        self.assertEqual(packs.cluster_competencies("Design"),
                         ["written communication", "interaction design"])


if __name__ == "__main__":
    unittest.main()
