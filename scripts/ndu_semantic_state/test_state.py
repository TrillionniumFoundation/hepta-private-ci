from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

import numpy as np

from ndu_semantic_state.state import (
    EMPTY_SHA256, MODALITIES, SCHEMA, Prefix, SemanticState, Slot, actor_binding,
    check_actor_binding, check_transition, from_public_encodings, migrate_v3_latents,
)


def prefix(value=b"", version=0):
    return {"sha256": hashlib.sha256(value).hexdigest(), "byte_count": len(value), "content_version": version}


def metadata():
    return {"slots": {name: {"available": [True], "progress": [0.0], "preparation": ["not_required"],
        "version": [0], "committed_prefix": [prefix()]} for name in MODALITIES},
        "remaining_budget": [5.0], "elapsed_seconds": [0.0]}


class PackageImportTests(unittest.TestCase):
    def run_isolated(self, code, *, block_numpy=False):
        prelude = f"import sys\nsys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        if block_numpy:
            prelude += textwrap.dedent("""
                import importlib.abc
                class BlockNumpy(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path, target=None):
                        if fullname == "numpy" or fullname.startswith("numpy."):
                            raise ModuleNotFoundError("NumPy deliberately unavailable", name=fullname)
                sys.meta_path.insert(0, BlockNumpy())
            """)
        result = subprocess.run(
            [sys.executable, "-I", "-c", prelude + textwrap.dedent(code)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unrelated_discovery_does_not_require_numpy(self):
        self.run_isolated("""
            import unittest
            import ndu_semantic_state as package
            assert "ndu_semantic_state.state" not in sys.modules
            assert getattr(package, "load_tests", None) is None
            try:
                package.not_an_export
            except AttributeError:
                pass
            else:
                raise AssertionError("unknown attribute was accepted")
            loader = unittest.TestLoader()
            assert loader.loadTestsFromModule(package).countTestCases() == 0
            assert not loader.errors
            assert "numpy" not in sys.modules
            assert "ndu_semantic_state.state" not in sys.modules
        """, block_numpy=True)

    def test_explicit_state_access_preserves_missing_dependency_error(self):
        self.run_isolated("""
            import ndu_semantic_state as package
            try:
                from ndu_semantic_state import SemanticState
            except ModuleNotFoundError as error:
                assert error.name == "numpy", error
            else:
                raise AssertionError("state API ignored its missing dependency")
            assert "SemanticState" not in vars(package)
            assert "ndu_semantic_state.state" not in sys.modules
        """, block_numpy=True)

    def test_explicit_and_star_imports_preserve_public_objects(self):
        self.run_isolated("""
            import ndu_semantic_state as package
            assert "ndu_semantic_state.state" not in sys.modules
            from ndu_semantic_state import SemanticState, state
            assert SemanticState is state.SemanticState
            namespace = {}
            exec("from ndu_semantic_state import *", namespace)
            assert set(namespace) - {"__builtins__"} == set(package.__all__)
            for name in package.__all__:
                assert namespace[name] is getattr(state, name)
                assert getattr(package, name) is vars(package)[name]
        """)


class PublicStateTests(unittest.TestCase):
    def build(self, meta=None, encodings=None):
        return from_public_encodings([[3.0, 4.0]],
            encodings or {"text": [[1.0, 2.0]], "image": [[5.0, 6.0]]}, meta or metadata())

    def test_same_mean_swapped_output_needs_are_distinguishable(self):
        normal = self.build()
        swapped = self.build(encodings={"text": [[5.0, 6.0]], "image": [[1.0, 2.0]]})
        np.testing.assert_array_equal(np.mean([s.encoding for s in normal.slots], axis=0),
                                      np.mean([s.encoding for s in swapped.slots], axis=0))
        self.assertFalse(np.array_equal(normal.features(), swapped.features()))
        self.assertEqual(normal.features().shape, (1, 3 * 2 + 20))
        self.assertEqual(len(set(normal.feature_names())), normal.features().shape[1])

    def test_input_order_does_not_relabel_a_modality(self):
        a = self.build()
        b = self.build(encodings={"image": [[5.0, 6.0]], "text": [[1.0, 2.0]]})
        np.testing.assert_array_equal(a.features(), b.features())
        self.assertEqual([s.modality for s in a.slots], ["text", "image"])

    def test_all_arms_receive_one_contract_without_arm_labels(self):
        state = self.build()
        bindings = [actor_binding(state) for _ in ("A", "B", "C", "D")]
        self.assertTrue(all(binding == bindings[0] for binding in bindings))
        with self.assertRaises(TypeError):
            from_public_encodings([[1.0]], {"text": [[1.0]], "image": [[1.0]]}, metadata(), arm="D")

    def test_joint_content_latents_do_not_assert_decoded_output_or_delivery(self):
        state = from_public_encodings([[3.0, 4.0]], {"text": [[1.0, 2.0]], "image": [[5.0, 6.0]]},
                                      metadata(), representation="joint_content_latent")
        self.assertEqual(state.representation, "joint_content_latent")
        self.assertTrue(state.slots[0].available[0])
        self.assertEqual(state.slots[0].committed_prefix[0].byte_count, 0)
        self.assertNotEqual(actor_binding(state), actor_binding(self.build()))
        with self.assertRaises(ValueError):
            check_actor_binding(actor_binding(self.build()), state)

    def test_private_or_future_fields_rejected_at_every_structured_boundary(self):
        for forbidden in ("targets", "future", "evaluator", "arm", "quality_label"):
            with self.subTest(field=forbidden):
                meta = metadata(); meta[forbidden] = 1
                with self.assertRaises(ValueError):
                    self.build(meta)
                meta = metadata(); meta["slots"]["text"][forbidden] = 1
                with self.assertRaises(ValueError):
                    self.build(meta)
                meta = metadata(); meta["slots"]["text"]["committed_prefix"][0][forbidden] = 1
                with self.assertRaises(ValueError):
                    self.build(meta)

    def test_missing_output_is_explicit_and_cannot_carry_hidden_encoding(self):
        meta = metadata(); meta["slots"]["image"]["available"] = [False]
        with self.assertRaises(ValueError):
            self.build(meta)
        state = self.build(meta, {"text": [[1.0, 2.0]], "image": [[0.0, 0.0]]})
        available = state.feature_names().index("image.available")
        self.assertEqual(state.features()[0, available], 0.0)
        self.assertEqual(state.slots[1].committed_prefix[0].sha256, EMPTY_SHA256)

    def test_preparation_progress_and_versions_remain_separate(self):
        normal = self.build()
        meta = metadata()
        meta["slots"]["image"].update(preparation=["pending"], progress=[0.5], version=[2])
        state = self.build(meta)
        self.assertFalse(np.array_equal(normal.features(), state.features()))
        self.assertEqual(state.features()[0, state.feature_names().index("image.preparation.pending")], 1.0)
        self.assertEqual(state.features()[0, state.feature_names().index("text.preparation.pending")], 0.0)

    def test_source_arrays_are_copied_and_finite(self):
        encodings = {"text": np.array([[1.0, 2.0]]), "image": np.array([[5.0, 6.0]])}
        state = self.build(encodings=encodings)
        encodings["text"][0, 0] = 900
        self.assertEqual(state.slots[0].encoding[0, 0], 1)
        with self.assertRaises(ValueError):
            state.slots[0].encoding[0, 0] = 8
        for array in (state.shared, state.slots[0].encoding, state.slots[0].progress,
                      state.remaining_budget, state.elapsed_seconds):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.build(encodings={"text": [[bad, 2.0]], "image": [[5.0, 6.0]]})

    def test_strict_numeric_and_prefix_contracts(self):
        for field, value in (("version", [True]), ("progress", [1.1]), ("preparation", ["oracle_ready"]),
                             ("available", [1]), ("committed_prefix", [prefix(b"x", 1)])):
            meta = metadata(); meta["slots"]["text"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(meta)

    def test_prefix_extension_requires_real_witnesses(self):
        a = self.build()
        meta = metadata(); meta["remaining_budget"] = [4.0]; meta["elapsed_seconds"] = [0.3]
        meta["slots"]["text"].update(version=[1], committed_prefix=[prefix("文".encode(), 1)])
        b = self.build(meta)
        with self.assertRaises(ValueError):
            check_transition(a, b)
        check_transition(a, b, {"text": [(b"", "文".encode())]})
        bad = deepcopy(meta)
        bad["slots"]["text"].update(version=[2], committed_prefix=[prefix("字".encode(), 2)])
        c = self.build(bad)
        with self.assertRaises(ValueError):
            check_transition(b, c, {"text": [("文".encode(), "字".encode())]})

    def test_unchanged_receipt_still_validates_every_supplied_witness(self):
        meta = metadata()
        meta["slots"]["text"].update(version=[1], committed_prefix=[prefix(b"abc", 1)])
        state = self.build(meta)
        check_transition(state, state, {"text": [(b"abc", b"abc")]})
        for witness in ([(b"abc", b"xyz")], [(b"xyz", b"abc")], "not-a-witness-list", None,
                        [], [(b"abc",)], [(b"abc", "abc")], [(b"abc", b"abc"), (b"abc", b"abc")]):
            with self.subTest(witness=witness), self.assertRaises(ValueError):
                check_transition(state, state, {"text": witness})
        with self.assertRaises(ValueError):
            check_transition(state, state, {"image": [(b"", b"unexpected")]})

    def test_public_dataclass_construction_cannot_reorder_or_relabel_slots(self):
        state = self.build()
        with self.assertRaisesRegex(ValueError, "identities and order"):
            replace(state, slots=state.slots[::-1])
        with self.assertRaises(ValueError):
            SemanticState(state.shared, (state.slots[0], state.slots[0]),
                          state.remaining_budget, state.elapsed_seconds, state.representation)
        with self.assertRaises(ValueError):
            replace(state, shared=[[1.0, 2.0, 3.0]])
        with self.assertRaises(ValueError):
            replace(state, representation="claimed_real")
        with self.assertRaises(ValueError):
            replace(state.slots[0], modality="evaluator")
        check_actor_binding(actor_binding(state), replace(state))

    def test_direct_prefix_and_slot_construction_enforce_the_same_invariants(self):
        state = self.build()
        with self.assertRaises(ValueError):
            Prefix(EMPTY_SHA256, -1, 0)
        with self.assertRaises(ValueError):
            Prefix("0" * 64, 0, 0)
        with self.assertRaises(ValueError):
            replace(state.slots[0], committed_prefix=(Prefix(hashlib.sha256(b"x").hexdigest(), 1, 1),))
        with self.assertRaises(ValueError):
            replace(state.slots[0], available=(False,))
        with self.assertRaises(ValueError):
            Slot("text", [[float("nan"), 0.0]], (True,), [0.0], ("ready",), (0,),
                 (Prefix(EMPTY_SHA256, 0, 0),))

    def test_budget_clock_encoding_and_prefix_cannot_silently_rewind(self):
        a = self.build()
        meta = metadata(); meta["remaining_budget"] = [6.0]
        with self.assertRaises(ValueError):
            check_transition(a, self.build(meta))
        with self.assertRaises(ValueError):
            check_transition(a, self.build(encodings={"text": [[9.0, 2.0]], "image": [[5.0, 6.0]]}))
        meta = metadata(); meta["slots"]["text"]["version"] = [1]
        b = self.build(meta, {"text": [[9.0, 2.0]], "image": [[5.0, 6.0]]})
        check_transition(a, b)
        with self.assertRaises(ValueError):
            check_transition(b, a)

    def test_v3_migration_is_named_and_rejects_old_actor_and_false_semantics(self):
        old = np.array([[[5., 6.], [11., 12.], [13., 14.], [1., 2.]]], dtype=np.float32)
        state, receipt = migrate_v3_latents(np.array([[3., 4.]], dtype=np.float32), old, metadata())
        np.testing.assert_array_equal(state.features(), self.build().features())
        self.assertEqual(state.representation, "legacy_v3_latent")
        self.assertFalse(receipt["old_actor_compatible"])
        self.assertFalse(receipt["semantic_qualification_migrated"])
        self.assertEqual(receipt["omitted_modalities"], ["audio", "video"])
        for old_binding in ({}, {"input_features": 9}, actor_binding(self.build())):
            with self.assertRaises(ValueError):
                check_actor_binding(old_binding, state)
        check_actor_binding(actor_binding(state), state)


if __name__ == "__main__":
    unittest.main()
