"""Real safetensors materialization, including legacy regenerated position IDs."""
from pathlib import Path
import tempfile
import unittest

import torch
from safetensors.torch import save_file

from experiments.shared_stem_cell import execution as e


class BufferedModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(3, 2)
        self.embeddings = torch.nn.Module()
        self.embeddings.register_buffer("position_ids", torch.arange(7).reshape(1, -1), persistent=False)
        self.register_buffer("persistent", torch.tensor([0.125]), persistent=True)
        self.unregistered = torch.tensor([2.0])


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = BufferedModel().eval()
        self.info = {key: [] for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")}

    def tearDown(self):
        self.temp.cleanup()

    def saved(self, state):
        path = self.root / "model.safetensors"
        save_file({k: v.detach().clone().contiguous() for k, v in state.items()}, str(path))
        return {"files": {path.name: e.sha(path.read_bytes())}}

    def legacy(self):
        return {**self.model.state_dict(), "embeddings.position_ids": self.model.embeddings.position_ids}

    def test_legacy_buffer_values_are_verified_not_discarded(self):
        before = e.parameters(self.model)
        report = e.verify_materialized(self.model, self.info, self.root, self.saved(self.legacy()))
        self.assertEqual(report["verified_nonpersistent_buffers"], {
            "embeddings.position_ids": {"shape": [1, 7], "dtype": "torch.int64",
                "sha256": e.tensor_digest(self.model.embeddings.position_ids), "runtime_equal": True}})
        self.assertEqual(report["verified_tensor_keys"], len(self.model.state_dict()) + 1)
        self.assertEqual(e.parameters(self.model), before)

    def test_modern_state_without_regenerated_buffer_remains_valid(self):
        report = e.verify_materialized(self.model, self.info, self.root, self.saved(self.model.state_dict()))
        self.assertEqual(report["verified_nonpersistent_buffers"], {})

    def test_rehashed_wrong_buffer_rejected_without_repair(self):
        for value in (torch.zeros(1, 7, dtype=torch.int64), torch.arange(7).float().reshape(1, -1),
                      torch.arange(7), torch.arange(8).reshape(1, -1)):
            with self.subTest(shape=tuple(value.shape), dtype=str(value.dtype)):
                state = self.legacy()
                state["embeddings.position_ids"] = value
                with self.assertRaisesRegex(e.InputError, "nonpersistent buffer mismatch"):
                    e.verify_materialized(self.model, self.info, self.root, self.saved(state))
                self.assertTrue(torch.equal(self.model.embeddings.position_ids, torch.arange(7).reshape(1, -1)))

    def test_unregistered_attribute_is_not_a_saved_tensor_contract(self):
        state = {**self.legacy(), "unregistered": self.model.unregistered}
        with self.assertRaisesRegex(e.InputError, "unknown snapshot tensor: unregistered"):
            e.verify_materialized(self.model, self.info, self.root, self.saved(state))

    def test_unknown_position_id_name_is_not_allowlisted(self):
        state = {**self.legacy(), "other.position_ids": torch.arange(7).reshape(1, -1)}
        with self.assertRaisesRegex(e.InputError, "unknown snapshot tensor"):
            e.verify_materialized(self.model, self.info, self.root, self.saved(state))

    def test_actual_runtime_buffer_corruption_is_detected(self):
        manifest = self.saved(self.legacy())
        self.model.embeddings.position_ids[0, 2] = 99
        with self.assertRaisesRegex(e.InputError, "nonpersistent buffer mismatch"):
            e.verify_materialized(self.model, self.info, self.root, manifest)

    def test_buffer_alias_does_not_cover_missing_parameter(self):
        self.model.register_buffer("weight_alias", self.model.linear.weight.detach(), persistent=False)
        state = self.legacy()
        state["weight_alias"] = state.pop("linear.weight")
        with self.assertRaisesRegex(e.InputError, "unverified loaded tensor"):
            e.verify_materialized(self.model, self.info, self.root, self.saved(state))

    def test_loading_errors_are_still_fatal(self):
        manifest = self.saved(self.legacy())
        for field in self.info:
            with self.subTest(field=field), self.assertRaisesRegex(e.InputError, "incomplete model load"):
                e.verify_materialized(self.model, {**self.info, field: ["embeddings.position_ids"]}, self.root, manifest)

    def test_duplicate_keys_across_shards_are_rejected(self):
        manifest = self.saved(self.legacy())
        save_file({"embeddings.position_ids": self.model.embeddings.position_ids}, str(self.root / "extra.safetensors"))
        manifest["files"]["extra.safetensors"] = e.sha((self.root / "extra.safetensors").read_bytes())
        with self.assertRaisesRegex(e.InputError, "duplicate snapshot tensor"):
            e.verify_materialized(self.model, self.info, self.root, manifest)

    def test_nonfinite_nonpersistent_buffer_is_rejected(self):
        self.model.register_buffer("nan_buffer", torch.tensor([float("nan")]), persistent=False)
        state = {**self.legacy(), "nan_buffer": self.model.nan_buffer}
        with self.assertRaisesRegex(e.InputError, "nonpersistent buffer mismatch"):
            e.verify_materialized(self.model, self.info, self.root, self.saved(state))


if __name__ == "__main__":
    unittest.main()
