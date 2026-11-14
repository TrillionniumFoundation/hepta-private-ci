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



class E0ProjectionDiagnosticsTests(unittest.TestCase):
    """Synthetic encoder doubles exercise failure records, never model execution."""

    class Feature(list):
        ndim = 1

        def tolist(self):
            return list(self)

    def invoke(self, output, vectors, snapshot_error=None):
        self.forward = mock.Mock(
            side_effect=[(self.Feature(vector), 12) for vector in vectors])
        self.guard = mock.Mock()
        checkpoint = types.SimpleNamespace(
            head=types.SimpleNamespace(
                register_forward_pre_hook=mock.Mock(return_value=self.guard)))
        encoder = types.SimpleNamespace(config=types.SimpleNamespace(hidden_size=768))
        modules = {
            "torch": types.SimpleNamespace(
                __version__="2.10.0", set_num_threads=mock.Mock()),
            "transformers": types.SimpleNamespace(
                __version__="4.57.1",
                AutoTokenizer=types.SimpleNamespace(
                    from_pretrained=mock.Mock(return_value=object()))),
            "hf_encoder_kernel": types.SimpleNamespace(
                snapshot_digest=mock.Mock(return_value=e0.SNAPSHOT_SHA256),
                vectorize_case=self.forward,
                verify_loaded_safetensors=mock.Mock()),
            "hf_complete_checkpoint": types.SimpleNamespace(
                TIED_ALIASES={},
                load_complete_mlm=mock.Mock(return_value=(
                    checkpoint, encoder,
                    {"checkpoint_parameters": 1, "feature_parameters": 1}))),
        }
        sources = types.SimpleNamespace(
            modules={"hf_encoder_kernel": {
                "snapshot": output.parent / "synthetic" / "hf_encoder_kernel.py"}},
            loaded_sources=lambda: [])

        def pinned_file(path):
            return (e0.MODEL_WEIGHT_SHA256 if path.name == "model.safetensors"
                    else "b" * 64)

        with mock.patch.dict(sys.modules, modules), \
                mock.patch.object(e0, "ensure_snapshot",
                                  return_value=output.parent / "synthetic-snapshot",
                                  side_effect=snapshot_error), \
                mock.patch.object(e0, "file_sha256", side_effect=pinned_file):
            return e0._run_bound(output=output, sources=sources)

    def expected_diagnostic(self, vector, completed, **observed):
        return {
            "schema": "hepta.e0.projection-input-diagnostic.v1",
            "input_index": completed,
            "completed_inputs": completed,
            "feature_shape": [768],
            "feature_f32_sha256": e0.feature_hash(vector),
            "q24_input_limit": 8,
            **observed,
        }

    def test_projection_rejection_retains_bounded_current_input_diagnostic(self):
        vector = [0.0] * 768
        vector[7], vector[767] = -9.0, 10.0
        for completed in (0, 1):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as td:
                output = Path(td) / "attempt"
                with self.assertRaisesRegex(ValueError, r"Q24 input outside \[-8,8\]"):
                    self.invoke(output, [[0.0] * 768] * completed + [vector])
                raw = (output / "FAILED.json").read_bytes()
                record = json.loads(raw)
                self.assertEqual(record.get("projection_input_diagnostic"),
                                 self.expected_diagnostic(
                                     vector, completed, finite_values=768,
                                     nonfinite_values=0, finite_minimum=-9.0,
                                     finite_maximum=10.0, first_nonfinite_index=None,
                                     outside_input_bound_count=2,
                                     first_outside_input_bound={
                                         "index": 7, "value": -9.0}))
                self.assertEqual(
                    {key: record[key] for key in (
                        "schema", "completed", "error_type",
                        "e0_accepted", "production_authorized")},
                    {"schema": e0.SCHEMA, "completed": False,
                     "error_type": "ValueError", "e0_accepted": False,
                     "production_authorized": False})
                self.assertLess(len(raw), 2048)
                self.assertFalse((output / "shadow.json").exists())
                self.assertEqual(self.forward.call_count, completed + 1)
                self.guard.remove.assert_called_once()

    def test_nonfinite_rejection_record_contains_no_nonfinite_json_number(self):
        vector = [0.0] * 768
        vector[17] = float("nan")
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "attempt"
            with self.assertRaisesRegex(ValueError, "non-finite numeric feature"):
                self.invoke(output, [vector])
            raw = (output / "FAILED.json").read_text()
            record = json.loads(raw)
            self.assertEqual(record.get("projection_input_diagnostic"),
                             self.expected_diagnostic(
                                 vector, 0, finite_values=767, nonfinite_values=1,
                                 finite_minimum=0.0, finite_maximum=0.0,
                                 first_nonfinite_index=17,
                                 outside_input_bound_count=0,
                                 first_outside_input_bound=None))
            self.assertNotIn("NaN", raw)
            self.assertFalse((output / "shadow.json").exists())

    def test_failure_before_projection_does_not_invent_feature_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "attempt"
            failure = ValueError("synthetic checkpoint preparation failed")
            with self.assertRaises(ValueError) as raised:
                self.invoke(output, [], snapshot_error=failure)
            self.assertIs(raised.exception, failure)
            record = json.loads((output / "FAILED.json").read_text())
            self.assertIsNone(record.get("projection_input_diagnostic"))
            self.assertFalse(record["completed"])
            self.forward.assert_not_called()
            self.assertFalse((output / "shadow.json").exists())

    def test_successful_synthetic_route_keeps_original_shadow_semantics(self):
        vectors = [[0.0] * 768, [0.125] * 768, [0.0] * 768]
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "attempt"
            result = self.invoke(output, vectors)
            self.assertEqual(result, json.loads((output / "shadow.json").read_text()))
            self.assertEqual(result["actual_hf_forward_calls"], 3)
            self.assertTrue(result["repeat_input_exact"])
            self.assertTrue(result["distinct_input_survived"])
            self.assertFalse(result["e0_accepted"])
            self.assertFalse(result["production_authorized"])
            self.assertNotIn("projection_input_diagnostic", result)
            self.assertFalse((output / "FAILED.json").exists())
            self.guard.remove.assert_called_once()


if __name__ == "__main__":
    unittest.main()
