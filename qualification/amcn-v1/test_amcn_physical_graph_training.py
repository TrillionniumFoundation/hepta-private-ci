"""Real CPU Torch parity plus adversarial source/math controls (no pretrained model)."""
from copy import deepcopy
from hashlib import sha256
import math
import unittest

import torch

import amcn_causal_graph_training as graph
from amcn_causal_route_plan import RELATIONS
from amcn_causal_task_audit import Refused, digest


def sample():
    return [{"relation": "supports", "label": 1, "family": "train-a", "split": "train"},
            {"relation": "supports", "label": 0, "family": "train-b", "split": "train"},
            {"relation": "temporal", "label": 1, "family": "train-c", "split": "train"},
            {"relation": "procedural", "label": 0, "family": "train-d", "split": "train"},
            {"relation": "associative", "label": 1, "family": "train-e", "split": "train"},
            {"relation": "contradicts", "label": 0, "family": "train-f", "split": "train"}]


class TorchTrainingMathematics(unittest.TestCase):
    def test_real_cpu_optimizer_matches_independent_scalar_recurrence(self):
        """Runs true torch.optim.SGD (not a mocked Head or claimed receipt)."""
        torch.set_num_threads(1)
        rows = sample()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(17)
            weights = torch.nn.Parameter(torch.zeros(len(RELATIONS), dtype=torch.float32))
            labels = torch.tensor([r["label"] for r in rows], dtype=torch.float32)
            indices = torch.tensor([RELATIONS.index(r["relation"]) for r in rows])
            optim = torch.optim.SGD([weights], lr=0.1)
            for _ in range(77):
                optim.zero_grad(set_to_none=True)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    weights[indices], labels)
                loss.backward()
                optim.step()
                with torch.no_grad():
                    weights.clamp_(-8, 8)
            expected = graph.independent_sgd(rows, steps=77)
            observed = weights.detach().tolist()
        for r, value in zip(RELATIONS, observed):
            self.assertAlmostEqual(value, expected[r], delta=2e-5)
        self.assertGreater(abs(observed[RELATIONS.index("temporal")]), 1e-5)

    def test_changed_train_label_changes_numeric_outcome(self):
        rows = sample()
        first = graph.independent_sgd(rows, steps=30)
        rows[0]["label"] = 0
        second = graph.independent_sgd(rows, steps=30)
        self.assertNotEqual(first["supports"], second["supports"])

    def test_future_label_is_not_legal_optimizer_input(self):
        rows = sample()
        rows[0]["split"] = "future_a"
        with self.assertRaisesRegex(Refused, "future-family contamination"):
            graph._valid_training(rows, set(RELATIONS),
                                  expected_training_sha256=digest(rows),
                                  forbidden_future_families={"future-family"})

    def test_heldout_family_leak_denied(self):
        rows = sample()
        rows[0]["family"] = "future-family"
        with self.assertRaisesRegex(Refused, "future-family contamination"):
            graph._valid_training(rows, set(RELATIONS),
                                  expected_training_sha256=digest(rows),
                                  forbidden_future_families={"future-family"})

    def test_unregistered_relation_denied(self):
        with self.assertRaisesRegex(Refused, "future-family contamination"):
            graph._valid_training(sample(), {"supports"},
                                  expected_training_sha256=digest(sample()),
                                  forbidden_future_families={"future-family"})

    def test_forged_train_source_pin_denied(self):
        with self.assertRaisesRegex(Refused, "pinned original"):
            graph._valid_training(sample(), set(RELATIONS),
                                  expected_training_sha256=sha256(b"forgery").hexdigest(),
                                  forbidden_future_families=set())

    def test_no_independent_sgd_when_step_count_zero(self):
        with self.assertRaisesRegex(Refused, "step count"):
            graph.independent_sgd(sample(), steps=0)

    def test_no_model_training_disguised_as_graph_positive(self):
        rows = sample()
        rows[0]["label"] = "yes"
        with self.assertRaises(Refused):
            graph.independent_sgd(rows, steps=10)


if __name__ == "__main__":
    unittest.main()
