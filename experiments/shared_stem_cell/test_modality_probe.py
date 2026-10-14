"""Actual fixed-parameter fusion probes on synthetic features; not model quality."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import torch

from experiments.shared_stem_cell import controls as c
from experiments.shared_stem_cell import execution as e


class ModalityProbeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(31)
        self.inputs = {name: (torch.randn(6, 2, 4), torch.ones(6, 2, dtype=torch.bool),
                             torch.tensor([[1, 2]] * 6)) for name in ("text", "image")}
        self.parts = ["holdout"] * 4 + ["retention"] * 2
        self.model = c.FusionHead({"text": (2, 4), "image": (2, 4)}, 2)

    def probe(self):
        return c.paired_modality_probe(self.model, self.inputs, self.parts)

    def test_all_probes_reuse_identical_parameters(self):
        before = e.parameters(self.model)
        result = self.probe()
        self.assertEqual(set(result["predictions"]), {"as_observed", "mask:image", "rotate:image", "mask:text", "rotate:text"})
        self.assertEqual({r["model_sha256"] for r in result["costs"].values()}, {before["sha256"]})
        self.assertEqual(e.parameters(self.model), before)
        self.assertTrue(all(r["fusion_forward_calls"] == 1 for r in result["costs"].values()))

    def test_as_observed_matches_original_joint_prediction(self):
        with torch.no_grad():
            original = self.model(self.inputs).softmax(-1).tolist()
        self.assertEqual(self.probe()["predictions"]["as_observed"], original)

    def test_rotation_stays_in_each_fold(self):
        result = self.probe()
        for name in ("image", "text"):
            mapping = result["source_rows"][f"rotate:{name}"]["rows"]
            self.assertEqual(mapping, [1, 2, 3, 0, 5, 4])
            for i, donor in enumerate(mapping):
                self.assertEqual(self.parts[i], self.parts[donor])

    def test_masks_remove_features_and_presence_without_mutation(self):
        before = deepcopy(self.inputs)
        result = self.probe()
        removed = dict(self.inputs)
        removed["image"] = tuple(torch.zeros_like(v) for v in self.inputs["image"])
        with torch.no_grad():
            expected = self.model(removed).softmax(-1).tolist()
        self.assertEqual(result["predictions"]["mask:image"], expected)
        for name in before:
            for x, y in zip(before[name], self.inputs[name]):
                self.assertTrue(torch.equal(x, y))

    def test_missing_media_never_becomes_present_by_rotation(self):
        self.inputs["image"][1][1] = False
        result = self.probe()
        mapping = result["source_rows"]["rotate:image"]["rows"]
        self.assertEqual(mapping[1], 1)
        self.assertEqual(set(mapping[:4]), {0, 1, 2, 3})

    def test_single_case_fold_is_explicit_identity_not_fake_swap(self):
        self.parts[-2:] = ["small-a", "small-b"]
        self.assertEqual(self.probe()["source_rows"]["rotate:text"]["rows"][-2:], [4, 5])

    def test_partition_mismatch_rejected(self):
        self.parts.pop()
        with self.assertRaises(e.InputError):
            self.probe()

    def test_probes_do_not_add_optimizer_steps(self):
        original = torch.optim.AdamW.step
        count = []
        def counted(optimizer, *args, **kwargs):
            count.append(1)
            return original(optimizer, *args, **kwargs)
        with patch.object(torch.optim.AdamW, "step", counted):
            result = c.modality_trial(self.inputs, torch.tensor([0, 1, 0, 1, 0, 1]), self.inputs,
                                      classes=2, steps=2, test_partitions=self.parts)
        self.assertEqual(len(count), 6)  # joint, image and text: two steps each
        self.assertEqual(sum(v["steps"] for v in result["costs"].values()), 6)
        self.assertEqual(result["modality_interventions"]["predictions"]["as_observed"], result["predictions"]["image+text"])
        self.assertFalse(result["modality_interventions"]["causal_semantics_established"])


if __name__ == "__main__":
    unittest.main()
