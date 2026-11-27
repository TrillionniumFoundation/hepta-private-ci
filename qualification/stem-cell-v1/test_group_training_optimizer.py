"""Research-only measured CPU optimizer controls; no pretrained efficacy."""
import copy
import math
import unittest

import torch
from torch.nn import functional as F

from group_core import Core
from group_training import fit_model


class GroupOptimizerFrontierTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(9)
        self.targets = torch.arange(8, dtype=torch.long).repeat(2)
        self.features = F.one_hot(self.targets, 8).float().unsqueeze(1).repeat(1, 3, 1)
        self.masks = torch.ones(len(self.targets), 3, dtype=torch.bool)

    def test_real_adam_cpu_state_and_paired_sampling(self):
        import torch._dynamo  # Initialize lazy framework before strict meter.
        initial = Core(8, 16)
        original = copy.deepcopy(initial.state_dict())
        sgd_model, sgd = fit_model(initial, self.features, self.masks,
                                   self.targets, steps=16, seed=31,
                                   max_depth=2, learning_rate=0.05,
                                   optimizer_kind="sgd")
        adam_model, adam = fit_model(initial, self.features, self.masks,
                                     self.targets, steps=16, seed=31,
                                     max_depth=2, learning_rate=0.008,
                                     optimizer_kind="adam")
        self.assertEqual(sgd["sample_and_depth_sha256"], adam["sample_and_depth_sha256"])
        self.assertEqual(sgd["initial_model_sha256"], adam["initial_model_sha256"])
        self.assertEqual(sgd["parameter_count"], adam["parameter_count"])
        self.assertEqual(sgd["optimizer_bytes"], 0)
        self.assertGreater(adam["optimizer_bytes"], 0)
        self.assertEqual(adam["optimizer_kind"], "adam")
        self.assertEqual(adam["optimizer_learning_rate"], 0.008)
        self.assertEqual(adam["status"], "completed")
        self.assertEqual(adam["work_observation"]["unknown_operators"], {})
        self.assertGreater(adam["work_observation"]["phase_flops"]["train"], 0)
        self.assertTrue(all(not p.requires_grad for p in adam_model.parameters()))
        self.assertTrue(all(torch.equal(original[key], value)
                            for key, value in initial.state_dict().items()))

    def test_reject_unregistered_or_nonfinite_optimizer_settings(self):
        initial = Core(8, 16)
        for optimizer in ("adamw", "fused", "Adam", True, None):
            with self.subTest(name=optimizer), self.assertRaises(ValueError):
                fit_model(initial, self.features, self.masks, self.targets,
                          steps=1, seed=0, optimizer_kind=optimizer)
        for lr in (float("nan"), float("inf"), -1.0, True, 0.0):
            with self.subTest(lr=lr), self.assertRaises(ValueError):
                fit_model(initial, self.features, self.masks, self.targets,
                          steps=1, seed=0, optimizer_kind="adam", learning_rate=lr)


if __name__ == "__main__":
    unittest.main()
