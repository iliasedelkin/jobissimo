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
from unittest import mock

from helpers import REPO

sys.path.insert(0, str(REPO / "scripts"))
import packs         # noqa: E402
import paths         # noqa: E402


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


class TestWorkspacePacks(unittest.TestCase):
    """A pack the install owns lives in the workspace, so it travels with
    /sync and a `git clean -xfd` in the engine checkout cannot eat it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "profile"
        self.cfg = self.home / "config"
        self.cfg.mkdir(parents=True)
        self.engine_packs = root / "engine_packs"
        write(self.cfg / "pipeline.yaml", "pack: product\n")
        self._prev = {k: os.environ.get(k) for k in ("JOBISSIMO_CONFIG", "JOBISSIMO_HOME")}
        os.environ["JOBISSIMO_CONFIG"] = str(self.cfg)
        os.environ["JOBISSIMO_HOME"] = str(self.home)

    def tearDown(self):
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _fake_pack(self, name: str, scaffold: bool = False, competencies: str = "[a, b]"):
        d = self.home / "packs" / name
        write(d / "pack.yaml", f"""
            name: {name}
            figure_nouns: [months, weeks]
            {'scaffold: true' if scaffold else ''}
        """)
        write(d / "roles.yaml", f"clusters:\n  X:\n    competencies: {competencies}\n")
        for f in ("evaluation.md", "ats_keywords.yaml", "ats_synonyms.yaml"):
            write(d / f, "\n")
        return d

    def test_workspace_pack_shadows_a_shipped_pack_of_the_same_name(self):
        self.assertEqual(packs.pack_origin("product"), "engine")
        self._fake_pack("product")
        self.assertEqual(packs.pack_origin("product"), "workspace")
        self.assertEqual(packs.pack_dir("product").parent.resolve(),
                         (self.home / "packs").resolve())

    def test_unknown_pack_reports_missing(self):
        self.assertEqual(packs.pack_origin("nosuchpack"), "missing")

    def test_available_packs_lists_workspace_first(self):
        self._fake_pack("uxd")
        names = dict(packs.available_packs())
        self.assertEqual(names["uxd"], "workspace")
        self.assertEqual(names["product"], "engine")

    # --- fork ----------------------------------------------------------

    def test_fork_copies_a_shipped_pack_into_the_workspace(self):
        dest = packs.fork_pack("product", "myproduct")
        self.assertTrue((dest / "roles.yaml").exists())
        self.assertEqual(dest.parent.resolve(), (self.home / "packs").resolve())
        self.assertEqual(packs.pack_origin("myproduct"), "workspace")

    def test_fork_renames_the_manifest(self):
        dest = packs.fork_pack("product", "myproduct")
        self.assertIn("name: myproduct", (dest / "pack.yaml").read_text())

    def test_fork_clears_the_scaffold_flag(self):
        """generic is a scaffold; a fork of it is the user's real pack."""
        dest = packs.fork_pack("generic", "uxd")
        body = (dest / "pack.yaml").read_text()
        self.assertNotIn("scaffold:", body)
        self.assertIn("figure_nouns:", body, "fork must not truncate the manifest")

    def test_fork_refuses_to_clobber_an_existing_workspace_pack(self):
        packs.fork_pack("product", "myproduct")
        with self.assertRaises(SystemExit):
            packs.fork_pack("product", "myproduct")

    def test_fork_of_an_unknown_pack_fails(self):
        with self.assertRaises(SystemExit):
            packs.fork_pack("nosuchpack")

    # --- validate ------------------------------------------------------

    def test_shipped_packs_are_well_formed(self):
        for name in ("product", "generic"):
            with self.subTest(pack=name):
                errors, _ = packs.validate_pack(name)
                self.assertEqual(errors, [])

    def test_scaffold_is_exempt_from_finished_pack_checks(self):
        self._fake_pack("bare", scaffold=True, competencies="[]")
        errors, warnings = packs.validate_pack("bare")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_empty_competencies_are_an_error_for_a_real_pack(self):
        self._fake_pack("bare", scaffold=False, competencies="[]")
        errors, _ = packs.validate_pack("bare")
        self.assertTrue(any("competencies" in e for e in errors))

    # --- export --------------------------------------------------------

    def test_export_copies_into_the_engine_checkout(self):
        self._fake_pack("uxd")
        with mock.patch.object(paths, "packs_dir", return_value=self.engine_packs):
            dest = packs.export_pack("uxd")
        self.assertTrue((dest / "pack.yaml").exists())
        self.assertEqual(dest, self.engine_packs / "uxd")

    def test_export_refuses_a_scaffold(self):
        self._fake_pack("uxd", scaffold=True)
        with mock.patch.object(paths, "packs_dir", return_value=self.engine_packs):
            with self.assertRaises(SystemExit):
                packs.export_pack("uxd")

    def test_export_refuses_a_malformed_pack(self):
        self._fake_pack("uxd", competencies="[]")
        with mock.patch.object(paths, "packs_dir", return_value=self.engine_packs):
            with self.assertRaises(SystemExit):
                packs.export_pack("uxd")

    def test_export_scrub_gate_blocks_personal_data(self):
        d = self._fake_pack("uxd")
        # A pipeline job-id is exactly the leak this gate exists for: a pack
        # grown from real applications picking up board-specific ids. Split so
        # this file does not trip the repo's own scrub scan (see test_scrub).
        leak = "linkedin" + "042"
        (d / "evaluation.md").write_text(f"seen in {leak}\n")
        with mock.patch.object(paths, "packs_dir", return_value=self.engine_packs):
            with self.assertRaises(SystemExit) as cm:
                packs.export_pack("uxd")
        self.assertIn("scrub", str(cm.exception).lower())
        self.assertFalse((self.engine_packs / "uxd").exists(), "nothing may be copied")

    def test_export_refuses_to_overwrite_without_force(self):
        self._fake_pack("uxd")
        with mock.patch.object(paths, "packs_dir", return_value=self.engine_packs):
            packs.export_pack("uxd")
            with self.assertRaises(SystemExit):
                packs.export_pack("uxd")
            self.assertTrue(packs.export_pack("uxd", force=True).exists())
