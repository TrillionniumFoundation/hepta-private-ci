"""Counterfactual and persistence invariants, not claims about task accuracy."""

import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from budget_study import local_credit, prune, task_value
from corpus import POLICIES, bits
from structure_models import Structure
from tensor_cell import CellConfig, OutputSpec, TensorCell


class BudgetStudyTests(unittest.TestCase):
    def fixture(self, arm):
        parent = TensorCell(CellConfig("test-parent", rank=2, input_dim=8,
                                      outputs=(OutputSpec("policy", size=12),), seed=71), "a" * 64)
        structure = Structure(parent, arm)
        return structure, torch.eye(8)

    def test_task_value_penalizes_full_trace_and_policy_error(self):
        exact = np.asarray([bits(policy) for policy in POLICIES], dtype=bool)
        actual = task_value(exact, [list(p) for p in POLICIES], [0, 5, 11, 17])
        self.assertEqual(actual["utility"], 1.0)
        changed = exact.copy(); changed[0, :4] = ~changed[0, :4]
        self.assertLess(task_value(changed, [list(p) for p in POLICIES], [0, 5, 11, 17])["utility"], 1.0)

    def test_credit_is_zero_without_learning_and_restores_parameter_bytes(self):
        structure, features = self.fixture("fixed_experts")
        prior = [(cell.A.detach().clone(), cell.B.detach().clone()) for cell in structure.cells]
        before = [cell.parameter_digest() for cell in structure.cells]
        receipt = local_credit(structure, prior, structure.routes.copy(), features,
                               [list(p) for p in POLICIES], {"event_probes": [0, 5]})
        self.assertEqual([row["task_value_delta"] for row in receipt["cells"]], [0.0, 0.0])
        self.assertEqual(receipt["routing_task_value_delta"], 0.0)
        self.assertEqual(before, [cell.parameter_digest() for cell in structure.cells])

    def test_pruning_compacts_real_parameters_and_roundtrips_shared_head(self):
        structure, features = self.fixture("monolith")
        before = copy.deepcopy(structure.counts())
        receipt = prune(structure, features, [list(p) for p in POLICIES],
                        {"event_probes": [0, 5], "pruned_rank": 1})
        self.assertEqual(len(receipt["retained_channels"]), 1)
        self.assertLess(structure.counts()["trainable"], before["trainable"])
        self.assertIs(structure.head, structure.cells[0].head)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            structure.save(checkpoint)
            restored = Structure.load(checkpoint, "a" * 64)
            self.assertTrue(torch.equal(structure(features, torch.arange(8)), restored(features, torch.arange(8))))


if __name__ == "__main__":
    unittest.main()
