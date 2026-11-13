"""Only synthetic control-gate tests; never proof of pretrained model execution."""
from __future__ import annotations

import hashlib
import importlib
import json
import py_compile
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import public_e0_shadow as e0
from stem_projection import LowRankProjectionQ24, Q
import native_bridge


class E0ShadowContractTests(unittest.TestCase):
    def test_width_and_final_coordinate_survive_existing_projection(self):
        proj = e0.make_diagnostic_projection(
            LowRankProjectionQ24, encoder="a" * 64,
            preprocessor="b" * 64, runtime="c" * 64, normalizer="d" * 64)
        self.assertEqual((proj.input_width, proj.output_width, proj.rank), (768, 256, 2))
        base = proj.project_float32((0.0,) * 768)
        changed = proj.project_float32((0.0,) * 767 + (0.25,))
        self.assertEqual(len(changed), 256)
        self.assertNotEqual(base[1], changed[1])
        self.assertGreater(len(proj.digest), 0)
        self.assertTrue(all(isinstance(x, int) and -8 * Q <= x <= 8 * Q for x in changed))

    def test_diagnostic_q24_readout_is_real_integer_math_not_lm(self):
        proj = e0.make_diagnostic_projection(
            LowRankProjectionQ24, encoder="a" * 64,
            preprocessor="b" * 64, runtime="c" * 64, normalizer="d" * 64)
        actual = proj.project_float32((0.25,)*768)
        self.assertEqual(e0.control_readout(native_bridge, actual),
                         [actual[0] / Q, actual[1] / Q])
        with self.assertRaisesRegex(ValueError, "wrong real HF feature width"):
            e0.feature_hash([0.0] * 512)

    def test_feature_byte_digest_is_sensitive_to_last_coordinate(self):
        one = [0.0] * 768
        two = one.copy()
        two[-1] = 0.25
        self.assertNotEqual(e0.feature_hash(one), e0.feature_hash(two))
        self.assertEqual(e0.feature_hash(one), e0.feature_hash(one))

    def test_fake_checkout_rejected_before_any_network_or_model_loading(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test",
                            "-c", "user.email=test@example.org", "commit",
                            "--allow-empty", "-qm", "fixture"], check=True)
            with self.assertRaisesRegex(ValueError, "source checkout SHA/tree mismatch"):
                e0.source_checkout(root, e0.HF_SOURCE_COMMIT, e0.HF_SOURCE_TREE)

    def test_existing_directory_is_not_eligible_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "attempt"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                e0.run(hf_checkout=root, projection_checkout=root, output=output)


class ProjectSourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.source = self.repo / "qualification" / "stem-cell-v1"
        self.source.mkdir(parents=True)
        self.payload = b"VALUE = 41\n"
        (self.source / "e0_fixture_leaf.py").write_bytes(self.payload)
        (self.source / "e0_fixture_entry.py").write_text(
            "from e0_fixture_leaf import VALUE\nRESULT = VALUE + 1\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "-qm", "pure Python source fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.specifications = ((self.repo, self.commit, self.tree, None),)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_compile_uses_git_bytes_despite_mutable_source_and_bytecode(self):
        leaf = self.source / "e0_fixture_leaf.py"
        self.git("update-index", "--assume-unchanged", "qualification/stem-cell-v1/e0_fixture_leaf.py")
        leaf.write_text("VALUE = 0\n")
        py_compile.compile(str(leaf), cfile=str(leaf.with_suffix(".pyc")), doraise=True)
        (self.source / "e0_fixture_untracked.py").write_text("VALUE = 99\n")
        before_finders = list(sys.meta_path)
        with mock.patch.object(sys, "path", [str(self.source), *sys.path]):
            with e0.bound_project_sources(self.specifications) as loader:
                module = importlib.import_module("e0_fixture_entry")
                self.assertEqual(module.RESULT, 42)
                snapshot = Path(sys.modules["e0_fixture_leaf"].__file__)
                self.assertNotEqual(snapshot, leaf)
                self.assertEqual(snapshot.read_bytes(), self.payload)
                loaded = {row["module"]: row for row in loader.loaded_sources()}
                self.assertEqual(set(loaded), {"e0_fixture_entry", "e0_fixture_leaf"})
                self.assertEqual(loaded["e0_fixture_leaf"]["sha256"],
                                 hashlib.sha256(self.payload).hexdigest())
                self.assertEqual(loaded["e0_fixture_leaf"]["git_blob"],
                                 self.git("rev-parse", f"{self.commit}:qualification/stem-cell-v1/e0_fixture_leaf.py"))
        self.assertNotIn("e0_fixture_entry", sys.modules)
        self.assertNotIn("e0_fixture_leaf", sys.modules)
        self.assertEqual(sys.meta_path, before_finders)
        self.assertFalse(snapshot.exists())

    def test_preloaded_controlled_module_is_rejected_and_preserved(self):
        existing = types.ModuleType("e0_fixture_leaf")
        before_finders = list(sys.meta_path)
        with mock.patch.dict(sys.modules, {"e0_fixture_leaf": existing}):
            with self.assertRaisesRegex(ValueError, "project module already loaded"):
                with e0.bound_project_sources(self.specifications):
                    self.fail("preloaded source was admitted")
            self.assertIs(sys.modules["e0_fixture_leaf"], existing)
        self.assertEqual(sys.meta_path, before_finders)

    def test_replace_ref_does_not_change_the_fixed_source_tree(self):
        (self.source / "e0_fixture_leaf.py").write_text("VALUE = 7\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "-qm", "replacement metadata fixture")
        replacement = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", self.commit)
        self.git("replace", self.commit, replacement)
        self.assertNotEqual(self.git("rev-parse", "HEAD^{tree}"), self.tree)
        with e0.bound_project_sources(self.specifications):
            self.assertEqual(importlib.import_module("e0_fixture_entry").RESULT, 42)
        self.assertEqual(self.git("replace", "-l"), self.commit)

    def test_regular_blob_and_size_bounds_precede_import(self):
        with mock.patch.object(e0, "MAX_SOURCE_FILE_BYTES", 4):
            with self.assertRaisesRegex(ValueError, "project Python source exceeds bounds"):
                with e0.bound_project_sources(self.specifications):
                    self.fail("oversize source was admitted")
        linked = self.source / "e0_fixture_link.py"
        linked.symlink_to("e0_fixture_leaf.py")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "-qm", "linked source fixture")
        specification = ((self.repo, self.git("rev-parse", "HEAD"),
                          self.git("rev-parse", "HEAD^{tree}"), None),)
        with self.assertRaisesRegex(ValueError, "project Python source must be a regular blob"):
            with e0.bound_project_sources(specification):
                self.fail("linked source was admitted")
        self.assertNotIn("e0_fixture_entry", sys.modules)

    def test_import_failure_cleans_only_this_scope(self):
        (self.source / "e0_fixture_entry.py").write_text(
            "import e0_fixture_leaf\nraise ValueError('ordinary fixture import failure')\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org",
                 "commit", "-qm", "import cleanup fixture")
        specification = ((self.repo, self.git("rev-parse", "HEAD"),
                          self.git("rev-parse", "HEAD^{tree}"), None),)
        before_finders = list(sys.meta_path)
        unrelated = types.ModuleType("e0_fixture_unrelated")
        with mock.patch.dict(sys.modules, {"e0_fixture_unrelated": unrelated}):
            with self.assertRaisesRegex(ValueError, "ordinary fixture import failure"):
                with e0.bound_project_sources(specification) as loader:
                    snapshot = loader.modules["e0_fixture_entry"]["snapshot"]
                    importlib.import_module("e0_fixture_entry")
            self.assertIs(sys.modules["e0_fixture_unrelated"], unrelated)
            self.assertNotIn("e0_fixture_entry", sys.modules)
            self.assertNotIn("e0_fixture_leaf", sys.modules)
            self.assertEqual(sys.meta_path, before_finders)
            self.assertFalse(snapshot.exists())


if __name__ == "__main__":
    unittest.main()
