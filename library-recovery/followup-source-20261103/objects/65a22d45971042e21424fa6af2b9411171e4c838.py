"""Synthetic-source/unit guards, never genuine Laya/Ettin weights or efficacy."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from types import SimpleNamespace
import gate
import physical_forward
import review_bytes
import source_bytes
from test_source_bytes import harness


class PhysicalForwardGuards(unittest.TestCase):
    def receipt(self, model="ettin400"):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name) / "stage"
        lookup, downloader, _ = harness(model)
        return source_bytes.acquire(model, lookup, downloader, base), base

    def test_probe_is_immutable_and_no_raw_labels(self):
        self.assertLessEqual(physical_forward.MAX_PROBE_TOKENS, 128)
        self.assertIn("Options: not_supported; supported", physical_forward.PROBE_TEXT)
        self.assertNotIn("gold", physical_forward.PROBE_TEXT.lower())
        self.assertNotIn("training", physical_forward.PROBE_TEXT.lower())

    def test_accepts_only_rehashed_original_test_fixture(self):
        receipt, stage = self.receipt()
        proof = physical_forward.checked_receipt(receipt, stage, "ettin400")
        self.assertEqual(proof["file_count"], len(receipt["files"]))
        self.assertTrue(proof["independently_rehashed_exact_physical_bytes"])

    def test_requires_complete_matching_registered_identity(self):
        receipt, stage = self.receipt()
        for name, value in (("model", "laya421"), ("revision", "0" * 40),
                            ("repo", "not-the-real-repo"), ("authority", "PERMIT"),
                            ("production_promotion_permitted", True),
                            ("tensor_model_loaded", True),
                            ("selected_source_bytes_verified", False)):
            with self.subTest(name=name):
                modified = dict(receipt, **{name: value})
                with self.assertRaises((gate.Denied, review_bytes.Rejected)):
                    physical_forward.checked_receipt(modified, stage, "ettin400")

    def test_disk_mutation_before_loader_is_rejected(self):
        receipt, stage = self.receipt()
        (stage / "config.json").write_text("malicious")
        with self.assertRaises(review_bytes.Rejected):
            physical_forward.checked_receipt(receipt, stage, "ettin400")

    def test_denies_other_checkpoint_families(self):
        receipt, stage = self.receipt()
        with self.assertRaises(gate.Denied):
            physical_forward.checked_receipt(receipt, stage, "openjev434")

    class FakeTensor:
        def __init__(self, shape, dtype="f32", device="cpu", layout="strided"):
            self.shape = shape
            self.dtype = dtype
            self.device = SimpleNamespace(type=device)
            self.layout = layout
        def numel(self):
            count = 1
            for n in self.shape:
                count *= n
            return count

    class FakeTorch:
        strided = "strided"
        Tensor = None

    def fake_net(self):
        f = self.FakeTensor
        self.FakeTorch.Tensor = f
        state = {"weight": f((2, 4)), "bias": f((2,))}
        return SimpleNamespace(state_dict=lambda:state), state

    def test_safe_state_inventory_exact_tensor_shape(self):
        net, state = self.fake_net()
        self.assertEqual(physical_forward.safe_state_inventory(net, state, self.FakeTorch), 10)

    def test_safe_state_inventory_denies_partial_extra_or_non_tensor(self):
        net, state = self.fake_net()
        examples = [dict(state, extra=self.FakeTensor((1,))),
                    {"weight": state["weight"]},
                    dict(state, bias="not a tensor")]
        for entry in examples:
            with self.assertRaises(gate.Denied):
                physical_forward.safe_state_inventory(net, entry, self.FakeTorch)

    def test_safe_state_inventory_denies_wrong_dtype_and_shape(self):
        net, state = self.fake_net()
        for mutation in ({"weight": self.FakeTensor((2, 4), dtype="int32")},
                         {"weight": self.FakeTensor((4, 2))},
                         {"weight": self.FakeTensor((2, 4), device="cuda")},
                         {"weight": self.FakeTensor((2, 4), layout="sparse")},
                         {"weight": self.FakeTensor((0, 4))}):
            with self.assertRaises(gate.Denied):
                physical_forward.safe_state_inventory(net, dict(state, **mutation), self.FakeTorch)

    def test_safe_state_inventory_denies_unbounded_mapping(self):
        net, state = self.fake_net()
        with self.assertRaises(gate.Denied):
            physical_forward.safe_state_inventory(net, {}, self.FakeTorch)

    def test_no_unsafe_torch_load_or_fallback_in_pilot_source(self):
        code = Path(physical_forward.__file__).read_text()
        tree = ast.parse(code)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        load = [n for n in calls if isinstance(n.func, ast.Attribute)
                and n.func.attr == "load" and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "torch"]
        self.assertEqual(len(load), 1)
        self.assertTrue(any(k.arg == "weights_only" and isinstance(k.value, ast.Constant)
                            and k.value.value is True for k in load[0].keywords))
        self.assertNotIn("trust_remote_code=True", code)
        self.assertNotIn("from_pretrained(\"jhu-clsp", code)

    def test_laya_original_pretrained_copy_not_mutated_by_native_loader(self):
        code = Path(physical_forward.__file__).read_text()
        self.assertIn("tempfile.TemporaryDirectory", code)
        self.assertIn("shutil.copyfile", code)
        self.assertIn("original_staged_tokenizer_was_not_modified", code)

    def test_no_fake_promotion_succeeds_without_model_execution(self):
        receipt, stage = self.receipt()
        with mock.patch.object(physical_forward, "_ettin_forward", side_effect=gate.Denied("no physical weights")):
            with self.assertRaises(gate.Denied):
                physical_forward.run("ettin400", receipt, stage)


if __name__ == "__main__":
    unittest.main()
