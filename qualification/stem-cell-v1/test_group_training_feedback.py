"""CPU numeric ablation for optional TRAIN feedback and terminal supervision.

Synthetic tensors validate mechanism only, not pretrained Granite reasoning.
"""
import unittest
import torch
from group_core import Core
from group_training import fit_model


class GroupFeedbackTests(unittest.TestCase):
    def setUp(self):
        import torch._dynamo
        torch.manual_seed(91)
        torch.set_num_threads(1)
        self.x = torch.randn(16, 3, 8) * 0.1
        self.y = torch.arange(8, dtype=torch.long).repeat(2)
        self.mask = torch.ones(16, 3, dtype=torch.bool)
        self.teacher = torch.zeros(16, 3, 3)
        self.teacher[:, 0, 0] = 1
        self.teacher[:, 2, 2] = 1
        self.operations = self.teacher.unsqueeze(2).clone()
        self.core = Core(8, 16)

    def test_paired_four_mode_training_and_no_callback(self):
        fitted = {}
        call_counts = []
        for guarded in (False, True):
            for isolated in (False, True):
                calls = [0]
                def train_callback(indices, guesses):
                    calls[0] += 1
                    return torch.tensor([
                        [float(int(self.y[i]) == guess), 1., 0., 0.]
                        for i, guess in zip(indices, guesses)])
                model, receipt = fit_model(
                    self.core, self.x, self.mask, self.y, steps=8, seed=33,
                    learning_rate=.05, max_depth=3, batch_size=8,
                    attention_targets=self.teacher, operation_targets=self.operations,
                    terminal_guard=guarded,
                    feedback_fn=None if isolated else train_callback,
                    training_feedback_policy=("no_verifier_v1" if isolated
                                              else "legacy_oracle_v1"))
                self.assertEqual(receipt["status"], "completed")
                self.assertEqual(receipt["work_observation"]["unknown_operators"], {})
                self.assertEqual(receipt["training_feedback_calls"], calls[0])
                self.assertEqual(isolated, calls[0] == 0)
                self.assertEqual(guarded, receipt["terminal_guard_enabled"])
                if guarded:
                    self.assertGreater(receipt["terminal_suppressed_step_examples"], 0)
                fitted[(guarded, isolated)] = (model, receipt)
                call_counts.append(calls[0])
        receipts = [r for _, r in fitted.values()]
        self.assertEqual(len({r["initial_model_sha256"] for r in receipts}), 1)
        self.assertEqual(len({r["sample_and_depth_sha256"] for r in receipts}), 1)
        self.assertEqual(len({r["parameter_count"] for r in receipts}), 1)
        self.assertNotEqual(
            fitted[(True, False)][1]["trained_model_sha256"],
            fitted[(True, True)][1]["trained_model_sha256"])

    def test_core_no_callback_preserves_stepwise_loss(self):
        def callback(indices, guesses):
            return torch.ones(len(indices), 4)
        _, original = fit_model(self.core, self.x, self.mask, self.y,
                                steps=5, seed=55, max_depth=3, feedback_fn=callback)
        _, without = fit_model(self.core, self.x, self.mask, self.y,
                               steps=5, seed=55, max_depth=3,
                               training_feedback_policy="no_verifier_v1")
        self.assertEqual(original["depth_supervision"], "mean_all_steps")
        self.assertEqual(without["depth_supervision"], "mean_all_steps")
        self.assertEqual(original["sample_and_depth_sha256"],
                         without["sample_and_depth_sha256"])
        self.assertEqual(without["training_feedback_calls"], 0)

    def test_conflicting_feedback_is_denied_before_training(self):
        for kwargs in ({"feedback_fn": lambda a, b: torch.zeros(len(a), 4)},
                       {"feedback": torch.zeros(16, 4)}):
            with self.assertRaises(ValueError):
                fit_model(self.core, self.x, self.mask, self.y,
                          steps=1, seed=3, training_feedback_policy="no_verifier_v1",
                          **kwargs)
        with self.assertRaises(ValueError):
            fit_model(self.core, self.x, self.mask, self.y, steps=1, seed=3,
                      training_feedback_policy="unsupported")


if __name__ == "__main__":
    unittest.main()
