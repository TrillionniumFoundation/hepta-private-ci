import unittest

import torch
from torch import nn

from head_surgery import SparseSplitHead, TrainingBatch, merge_identical, tensor_inventory, train_candidate


class HeadSurgeryTests(unittest.TestCase):
    def setUp(self):
        self.parent = nn.Linear(2, 2)
        with torch.no_grad():
            self.parent.weight.copy_(torch.eye(2))
            self.parent.bias.zero_()
        self.x = torch.tensor([[-2., 0.], [-1., 0.], [1., 0.], [2., 0.]])

    def test_split_preserves_parent_and_counts_new_gate(self):
        split = SparseSplitHead(self.parent, parameter_cap=18)
        torch.testing.assert_close(split(self.x), self.parent(self.x), rtol=0, atol=0)
        self.assertEqual(tensor_inventory(split)["parameters"], 18)
        self.assertEqual(tensor_inventory(split)["unique_weight_bytes"], 18 * 4)
        self.assertNotEqual(split.children_heads[0].weight.data_ptr(), split.children_heads[1].weight.data_ptr())
        self.assertNotEqual(split.children_heads[0].weight.data_ptr(), self.parent.weight.data_ptr())

    def test_parameter_cap_includes_router(self):
        for cap in (12, 17, True):
            with self.assertRaises(ValueError):
                SparseSplitHead(self.parent, parameter_cap=cap)

    def test_routing_is_input_conditional_and_physically_sparse(self):
        split = SparseSplitHead(self.parent, parameter_cap=18)
        with torch.no_grad():
            split.gate.weight.copy_(torch.tensor([[-1., 0.], [1., 0.]]))
        counts = [0, 0]
        handles = []
        for i, head in enumerate(split.children_heads):
            def record(module, args, i=i):
                counts[i] += len(args[0])
            handles.append(head.register_forward_pre_hook(record))
        try:
            split(self.x)
            self.assertEqual(counts, [2, 2])
            counts[:] = [0, 0]
            split(self.x[2:])
            self.assertEqual(counts, [0, 2])
        finally:
            for handle in handles:
                handle.remove()

    def test_training_updates_candidate_not_selected_or_features(self):
        split = SparseSplitHead(self.parent, parameter_cap=18)
        before = {k: v.clone() for k, v in split.state_dict().items()}
        features = self.x.clone()
        batch = TrainingBatch(self.x, torch.tensor([1, 1, 0, 0]),
                              torch.tensor([0, 0, 1, 1]), (1, 2, 3, 4), "a" * 64)
        trained, report = train_candidate(split, batch, cutoff_ns=4, steps=16, learning_rate=.1)
        for key, value in split.state_dict().items():
            torch.testing.assert_close(value, before[key], rtol=0, atol=0)
        torch.testing.assert_close(self.x, features, rtol=0, atol=0)
        self.assertTrue(any(not torch.equal(before[k], v) for k, v in trained.state_dict().items()))
        self.assertEqual(trained.gate(self.x).argmax(1).tolist(), [0, 0, 1, 1])
        self.assertEqual(report["examples_seen"], 64)
        self.assertFalse(report["future_gain_established"])
        self.assertIsNone(report["measured_flops"])

    def test_frozen_selected_parameters_only_thaw_in_candidate(self):
        selected = SparseSplitHead(self.parent, parameter_cap=18).requires_grad_(False)
        batch = TrainingBatch(self.x, torch.tensor([1, 1, 0, 0]),
                              torch.tensor([0, 0, 1, 1]), (1, 2, 3, 4), "a" * 64)
        candidate, _ = train_candidate(selected, batch, cutoff_ns=4, steps=2)
        self.assertTrue(all(not p.requires_grad for p in selected.parameters()))
        self.assertTrue(all(p.requires_grad for p in candidate.parameters()))
        self.assertTrue(any(not torch.equal(a, b) for a, b in
                            zip(selected.children_heads.parameters(), candidate.children_heads.parameters(), strict=True)))

    def test_future_labels_and_trainable_feature_sources_reject(self):
        split = SparseSplitHead(self.parent, parameter_cap=18)
        for features, times in ((self.x, (1, 2, 3, 5)),
                                (self.x.clone().requires_grad_(), (1, 2, 3, 4))):
            batch = TrainingBatch(features, torch.tensor([1, 1, 0, 0]),
                                  torch.tensor([0, 0, 1, 1]), times, "a" * 64)
            with self.assertRaises(ValueError):
                train_candidate(split, batch, cutoff_ns=4)

    def test_identical_merge_is_exact_divergent_merge_rejected(self):
        split = SparseSplitHead(self.parent, parameter_cap=18)
        merged = merge_identical(split)
        torch.testing.assert_close(merged(self.x), split(self.x), rtol=0, atol=0)
        with torch.no_grad():
            split.children_heads[1].bias.add_(1)
        with self.assertRaises(ValueError):
            merge_identical(split)

    def test_physical_inventory_deduplicates_shared_module(self):
        combined = nn.ModuleList([self.parent] * 16)
        self.assertEqual(tensor_inventory(combined)["parameters"], 6)
        self.assertEqual(tensor_inventory(combined)["unique_weight_bytes"], 24)


if __name__ == "__main__":
    unittest.main()
