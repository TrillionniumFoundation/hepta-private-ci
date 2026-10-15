"""Actual CPU gradient tests for intermediate supervision, no pretrained win."""
import copy
import unittest

import torch
from torch.nn import functional as F

from group_core import Core
from group_training import StaticHead, fit_model


class GroupAttentionTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(11)
        torch.set_num_threads(1)
        self.targets = torch.arange(8, dtype=torch.long).repeat(3)
        self.features = torch.randn(24, 3, 8) * .05
        self.features[:, 0, :] += 5.0 * F.one_hot(self.targets, 8).float()
        self.mask = torch.ones(24, 3, dtype=torch.bool)
        self.attention = torch.zeros(24, 3, 3, dtype=torch.float32)
        self.attention[:, :, 0] = 1.0

    def test_attention_tuple_preserves_legacy_logits_and_backward(self):
        core = Core(8, 16)
        x, y = core.step(self.features, mask=self.mask)
        new_x, new_y, attention = core.step(
            self.features, mask=self.mask, return_attention=True)
        torch.testing.assert_close(x, new_x, rtol=0, atol=0)
        torch.testing.assert_close(y, new_y, rtol=0, atol=0)
        self.assertEqual(attention.shape, (24, 3))
        torch.testing.assert_close(attention.sum(1), torch.ones(24))

    def test_real_sgd_updates_shared_parameters_under_identical_sampling(self):
        core = Core(8, 16)
        before = copy.deepcopy(core.state_dict())
        baseline, a = fit_model(core, self.features, self.mask, self.targets,
                                steps=16, seed=33, max_depth=3, learning_rate=.1)
        supervised, b = fit_model(
            core, self.features, self.mask, self.targets,
            steps=16, seed=33, max_depth=3, learning_rate=.1,
            attention_targets=self.attention, attention_weight=.2)
        self.assertEqual(a["status"], "completed")
        self.assertEqual(b["status"], "completed")
        self.assertEqual(a["sample_and_depth_sha256"], b["sample_and_depth_sha256"])
        self.assertEqual(a["parameter_count"], b["parameter_count"])
        self.assertGreater(b["attention_supervised_step_examples"], 0)
        self.assertTrue(b["attention_supervision_enabled"])
        self.assertIsNotNone(b["attention_target_sha256"])
        self.assertFalse(a["attention_supervision_enabled"])
        self.assertEqual(b["work_observation"]["unknown_operators"], {})
        self.assertGreater(b["work_observation"]["phase_flops"]["train"], 0)
        self.assertEqual(before.keys(), core.state_dict().keys())
        for key, value in before.items():
            torch.testing.assert_close(value, core.state_dict()[key], rtol=0, atol=0)
        self.assertTrue(any(not torch.equal(a, b) for a, b in
                            zip(baseline.parameters(), supervised.parameters())))
        self.assertTrue(all(not p.requires_grad for p in supervised.parameters()))

    def test_invalid_masks_missing_scope_and_static_model_rejected(self):
        bad = self.attention.clone()
        bad[:, :, 1] = .5
        invalid = [bad, self.attention[:, :, :2], self.attention.clone().requires_grad_()]
        for teacher in invalid:
            with self.subTest(shape=tuple(teacher.shape)), self.assertRaises(ValueError):
                fit_model(Core(8, 16), self.features, self.mask, self.targets,
                          steps=2, seed=1, max_depth=3,
                          attention_targets=teacher)
        with self.assertRaises(ValueError):
            fit_model(StaticHead(8, 16), self.features, self.mask, self.targets,
                      steps=2, seed=1, max_depth=3,
                      attention_targets=self.attention)
        mask = self.mask.clone()
        mask[:, 0] = False
        with self.assertRaises(ValueError):
            fit_model(Core(8, 16), self.features, mask, self.targets,
                      steps=2, seed=1, max_depth=3,
                      attention_targets=self.attention)


if __name__ == "__main__":
    unittest.main()
