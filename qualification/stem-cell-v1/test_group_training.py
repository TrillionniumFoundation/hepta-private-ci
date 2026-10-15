import copy
import unittest

import torch
from torch.nn import functional as F

from group_core import Core
from group_training import SplitCore, StaticHead, fit_model, matched_static


class GroupTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(5)
        torch.set_num_threads(1)
        self.targets = torch.arange(8).repeat(3)
        self.features = F.one_hot(self.targets, 8).float().unsqueeze(1).repeat(1, 3, 1)
        self.masks = torch.ones(24, 3, dtype=torch.bool)

    def test_fit_is_real_measured_frozen_and_preserves_source(self):
        model = StaticHead(8, 16)
        before = copy.deepcopy(model.state_dict())
        trained, receipt = fit_model(model, self.features, self.masks, self.targets,
                                     steps=80, seed=3, learning_rate=.3)
        self.assertEqual(receipt["status"], "completed")
        self.assertLess(receipt["loss_after"], receipt["loss_before"] * .3)
        self.assertTrue(all(torch.equal(before[k], v) for k, v in model.state_dict().items()))
        self.assertFalse(trained.training)
        self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})
        self.assertGreater(receipt["work_observation"]["phase_flops"]["train"], 0)
        self.assertEqual(receipt["optimizer_bytes"], 0)
        self.assertEqual(receipt["actual_completed_training_exposures"], 80 * 24)

    def test_matched_width_is_nearest_and_split_executes_only_selected_head(self):
        parent = Core(8, hidden_dim=16)
        static, match = matched_static(parent)
        target = match["target_parameters"]
        width = match["hidden_dim"]
        actual = sum(p.numel() for p in static.parameters())
        self.assertEqual(actual, match["actual_parameters"])
        self.assertLessEqual(abs(actual - target), min(abs((width - 1) * 17 + 8 - target),
                                                       abs((width + 1) * 17 + 8 - target)))
        split = SplitCore(parent)
        with torch.no_grad():
            for parameter in split.router.parameters():
                parameter.zero_()
            split.router[-1].bias[0] = 1
        calls = [0, 0]
        hooks = [head.register_forward_hook(lambda m, a, o, i=i: calls.__setitem__(i, calls[i] + 1))
                 for i, head in enumerate(split.readouts)]
        split(self.features, steps=2, mask=self.masks)
        self.assertEqual(calls, [2, 0])
        for hook in hooks:
            hook.remove()
        trained, receipt = fit_model(split, self.features, self.masks, self.targets,
                                     steps=8, seed=2, route_targets=self.targets % 2, max_depth=2)
        self.assertEqual(receipt["status"], "completed")
        self.assertFalse(receipt["readouts_share_parameter_storage"])
        self.assertFalse(receipt["readout_parameters_equal"])
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})
        self.assertEqual(len(trained.readouts), 2)

    def test_dynamic_training_feedback_reaches_later_recurrent_steps(self):
        seen = []
        def checker(indices, guesses):
            self.assertTrue(all(0 <= i < len(self.targets) for i in indices))
            self.assertEqual(len(indices), len(guesses))
            seen.append(tuple(indices))
            return torch.tensor([[0., float(g != self.targets[i].item()), 0., 0.]
                                 for i, g in zip(indices, guesses)])
        _, receipt = fit_model(Core(8, 16), self.features, self.masks, self.targets,
                              steps=12, seed=4, max_depth=4, feedback_fn=checker)
        self.assertGreater(len(seen), 0)
        self.assertEqual(receipt["training_feedback_calls"], len(seen))
        self.assertGreater(receipt["nonzero_feedback_batches"], 0)
        self.assertEqual(receipt["depth_supervision"], "mean_all_steps")
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})


if __name__ == "__main__":
    unittest.main()
