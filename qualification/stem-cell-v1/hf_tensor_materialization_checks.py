"""Real Torch/safetensors regressions for exact read-only materialization."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import torch
from safetensors.torch import save_file

from hf_joint_decision_runner import (
    validate_encoder_loading_info,
    verify_loaded_safetensors,
)


def cloned_state(model):
    return {name: value.detach().cpu().contiguous().clone()
            for name, value in model.state_dict().items()}


def snapshot_hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).glob("*.safetensors")}


class ExactMaterializationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        torch.manual_seed(194)
        self.model = torch.nn.Linear(3, 2)
        self.state = cloned_state(self.model)

    def save(self, state=None, name="model.safetensors"):
        save_file(self.state if state is None else state, str(self.root / name))

    def verify(self, model=None):
        return verify_loaded_safetensors(torch, self.model if model is None else model,
                                         self.root)

    def test_all_parameters_compared_with_no_buffer_exception(self):
        self.save()
        receipt = self.verify()
        self.assertTrue(receipt["complete"])
        self.assertTrue(receipt["all_state_dict_tensors_compared"])
        self.assertTrue(receipt["all_safetensors_tensors_compared"])
        self.assertEqual(receipt["tensor_count"], 2)
        self.assertEqual(receipt["tensor_elements"], 8)
        self.assertEqual(receipt["state_dict_tensor_count"], 2)
        self.assertEqual(receipt["verified_nonpersistent_buffer_keys"], [])
        self.assertFalse(receipt["production_authorization"])

    def test_requested_float_dtype_conversion_retained(self):
        self.save()
        self.model.to(dtype=torch.bfloat16)
        self.assertTrue(self.verify()["complete"])

    def test_float64_exact_values_retained(self):
        self.model.double()
        self.save(cloned_state(self.model))
        self.assertTrue(self.verify()["complete"])

    def test_changed_loaded_weight_rejected(self):
        self.save()
        with torch.no_grad():
            self.model.weight[0, 0] += 1
        with self.assertRaisesRegex(ValueError, "differs"):
            self.verify()

    def test_randomly_initialized_replacement_rejected(self):
        self.save()
        with self.assertRaisesRegex(ValueError, "differs"):
            self.verify(torch.nn.Linear(3, 2))

    def test_missing_weight_rejected(self):
        self.save({"weight": self.state["weight"]})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.verify()

    def test_unknown_tensor_rejected(self):
        self.save(dict(self.state, unrelated=torch.ones(1)))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_duplicate_shard_rejected(self):
        self.save()
        self.save(name="duplicate.safetensors")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_nonpersistent_buffer_not_blanket_allowlisted(self):
        self.model.register_buffer("extra", torch.arange(4), persistent=False)
        self.save(dict(self.state, extra=self.model.extra.clone()))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_bert_named_tensor_on_nonbert_model_rejected(self):
        self.save({**self.state, "embeddings.position_ids": torch.arange(16)[None]})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_position_ids_suffix_is_not_authorization(self):
        self.save({**self.state, "other.position_ids": torch.arange(16)[None]})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_meta_state_rejected(self):
        self.save()
        with self.assertRaisesRegex(ValueError, "materialization"):
            self.verify(torch.nn.Linear(3, 2, device="meta"))

    def test_shape_mismatch_rejected(self):
        self.save(dict(self.state, weight=torch.zeros(3, 2)))
        with self.assertRaisesRegex(ValueError, "shape"):
            self.verify()

    def test_nan_does_not_count_as_equal_materialization(self):
        with torch.no_grad():
            self.model.weight[0, 0] = float("nan")
        self.save(cloned_state(self.model))
        with self.assertRaisesRegex(ValueError, "differs"):
            self.verify()

    def test_empty_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.verify()

    def test_excessive_shards_rejected_before_opening(self):
        for i in range(65):
            (self.root / f"{i}.safetensors").touch()
        with self.assertRaisesRegex(ValueError, "excessive"):
            self.verify()

    def test_empty_model_inventory_rejected(self):
        self.save()
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.verify(torch.nn.Module())

    def test_verification_never_changes_files_or_parameters(self):
        self.save()
        before = snapshot_hashes(self.root)
        self.verify()
        self.assertEqual(snapshot_hashes(self.root), before)
        for key, value in self.model.state_dict().items():
            self.assertTrue(torch.equal(value, self.state[key]))
        self.save(dict(self.state, unknown=torch.ones(1)), "unknown.safetensors")
        before_failure = snapshot_hashes(self.root)
        with self.assertRaises(ValueError):
            self.verify()
        self.assertEqual(snapshot_hashes(self.root), before_failure)

    def test_loading_report_gate_remains_strict(self):
        clean = {key: [] for key in
                 ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")}
        self.assertTrue(validate_encoder_loading_info(clean)["complete"])
        for key in clean:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_encoder_loading_info({**clean, key: ["tensor"]})
                with self.assertRaises(ValueError):
                    validate_encoder_loading_info({k: v for k, v in clean.items() if k != key})


if __name__ == "__main__":
    unittest.main()
