"""Real-model development checks for lazy, budgeted four-output execution."""

from pathlib import Path
import sys
import unittest

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control import portfolio_grid
from model import OutputModel
from world import canonical, sample_worlds
from evaluation import rollout


class _UnacquiredVideo:
    def __getitem__(self, key):
        raise AssertionError("unacquired video was read")

    def __array__(self, *args, **kwargs):
        raise AssertionError("unacquired video was converted")


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.targets = canonical()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(941)
            self.model = OutputModel({name: values.shape[1]
                                      for name, values in self.targets.items()})
        self.model.eval().requires_grad_(False)
        self.world = sample_worlds(12, 912347, "review-development-v2-regression",
                                   scenario="iid")
        self.grid = portfolio_grid()
        self.policy = {"order": [1, 2], "modalities": [0, 1, 2],
                       "weights": [0.5, 0.25, 0.25], "depth": 2}

    def test_actual_linear_work_lazy_inputs_and_complete_emission(self):
        # An acquired missing report still costs budget, but no encoder call.
        self.world["raw"]["audio"][0] = 0
        self.world["raw"]["image"][1] = 0
        self.world["raw"]["text"][2] = 0
        self.world["raw"]["video"] = _UnacquiredVideo()
        observed_macs = []

        def count_linear(module, inputs, output):
            examples = inputs[0].numel() // module.in_features
            observed_macs.append(examples * module.in_features * module.out_features)

        handles = [module.register_forward_hook(count_linear)
                   for module in self.model.modules() if isinstance(module, torch.nn.Linear)]
        try:
            _, receipt, _ = rollout(self.model, self.world, self.policy, 16,
                                    self.grid, self.targets)
        finally:
            for handle in handles:
                handle.remove()
        self.assertEqual(sum(observed_macs), int(receipt["linear_macs"].sum()))
        self.assertGreater(sum(observed_macs), 0)
        self.assertEqual(receipt["encoder_calls"]["video"], 0)
        self.assertEqual(receipt["encoded_examples"]["video"], 0)
        self.assertLess(receipt["encoded_examples"]["audio"], 12)
        self.assertLess(receipt["encoded_examples"]["image"], 12)
        np.testing.assert_array_equal(receipt["remaining"], np.full(12, 3))
        self.assertEqual(set(receipt["output_sha256"]), set(self.targets))
        self.assertTrue(all(len(value) == 64 for value in receipt["output_sha256"].values()))
        self.assertTrue(receipt["all_four_outputs"])
        self.assertEqual(receipt["budget_violations"], 0)
        for trace in receipt["trace"]:
            events = [item["event"] for item in trace]
            self.assertEqual(events, ["initial_text", "acquire", "acquire",
                                      "initialize", "refine", "refine", "emit_all_four"])
            self.assertTrue(trace[-1]["sealed"])
            self.assertEqual([item["remaining"] for item in trace], [16, 13, 11, 9, 7, 5, 3])

    def test_truth_and_hidden_metadata_cannot_change_generation(self):
        _, first, _ = rollout(self.model, self.world, self.policy, 16,
                               self.grid, self.targets)
        changed = dict(self.world)
        changed["truth"] = (self.world["truth"] + 3) % 8
        changed["reports"] = np.full_like(self.world["reports"], 7)
        changed["scenario"] = np.full(12, "untrusted-hidden-metadata")
        changed["ids"] = ["changed-hidden-id"] * 12
        _, second, _ = rollout(self.model, changed, self.policy, 16,
                                self.grid, self.targets)
        for key in ("linear_macs", "remaining", "depth", "portfolio", "preference"):
            np.testing.assert_array_equal(first[key], second[key])
        for key in ("trace", "encoder_calls", "encoded_examples", "output_sha256",
                    "all_four_outputs", "budget_violations"):
            self.assertEqual(first[key], second[key])

    def test_infeasible_generation_cannot_claim_complete_output(self):
        # The same policy costs thirteen post-text units. Twelve cannot pass.
        with self.assertRaisesRegex(AssertionError, "generation exceeds remaining budget"):
            rollout(self.model, self.world, self.policy, 12, self.grid, self.targets)


if __name__ == "__main__":
    unittest.main()
