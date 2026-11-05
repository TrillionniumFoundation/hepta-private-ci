"""Identifiable toy environments test controller behavior, not real efficacy."""

from pathlib import Path
import tempfile
import unittest

import torch

from policies import ACTION_WEIGHTS, METHODS, Policies


def one_step_trajectories():
    qualities = [0.4, 0.5, 0.95, 0.75, 0.6, 0.5]
    losses = [0.02, 0.08, 1.0, 0.1, 0.05, 0.2]
    return [{"states": [[0.0] * 24], "actions": [action],
             "behavior_probs": [[1/6] * 6], "terminal_quality": qualities[action],
             "terminal_loss": losses[action], "split": "train"}
            for _ in range(4) for action in range(6)]


class PoliciesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        cls.policies = Policies(seed=7).fit(one_step_trajectories(), epochs=120, learning_rate=0.01)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def test_bsde_terminal_fit_recovers_action_conditioned_quality(self):
        result = self.policies.action([0.0] * 24, "ndu", risk_weight=0, seed=101)
        expected = torch.tensor([0.4, 0.5, 0.95, 0.75, 0.6, 0.5])
        predicted = torch.tensor(result["metadata"]["quality_estimates"])
        self.assertLess(float((predicted - expected).abs().max()), 0.08)
        self.assertLess(self.policies.training_metadata["training_terminal_residual_mse"], 0.01)
        self.assertFalse(self.policies.training_metadata["continuous_fbsde_solved"])

    def test_risk_weight_reduces_high_loss_action_probability(self):
        for method in ("risk_actor_critic", "ndu"):
            mean = self.policies.action([0.0] * 24, method, risk_weight=0, seed=2)
            sensitive = self.policies.action([0.0] * 24, method, risk_weight=2, seed=2)
            self.assertGreater(mean["metadata"]["action_probs"][2], sensitive["metadata"]["action_probs"][2])
        mean = self.policies.action([0.0] * 24, "mean_only", risk_weight=0, seed=2)
        ignored = self.policies.action([0.0] * 24, "mean_only", risk_weight=9, seed=2)
        self.assertEqual(mean, ignored)

    def test_sampled_policy_obeys_kl_and_replays_without_global_rng(self):
        for method in METHODS:
            first = self.policies.action([0.0] * 24, method, seed=700)
            torch.manual_seed(512)
            torch.rand(128)
            second = self.policies.action([0.0] * 24, method, seed=700)
            self.assertEqual(first, second)
            self.assertLessEqual(first["metadata"]["behavior_kl"], 0.250001)
            self.assertTrue(first["metadata"]["hard_kl_applies_to_executed_policy"])
            self.assertAlmostEqual(sum(first["metadata"]["action_probs"]), 1, places=6)
            self.assertEqual(first["weights"], ACTION_WEIGHTS[first["action"]])

    def test_covariance_is_an_optional_local_proxy(self):
        no_proxy = self.policies.action([0.0] * 24, "ndu", risk_weight=0.1, seed=5)
        proxy = torch.diag(torch.tensor([100.0, 0.0, 0.0, 0.0]))
        with_proxy = self.policies.action([0.0] * 24, "ndu", risk_weight=0.1, covariance=proxy, seed=5)
        self.assertLess(with_proxy["metadata"]["action_probs"][2], no_proxy["metadata"]["action_probs"][2])
        self.assertFalse(with_proxy["metadata"]["terminal_output_covariance_estimated"])
        self.assertIn("local_cell", with_proxy["metadata"]["covariance_kind"])
        with self.assertRaisesRegex(ValueError, "PSD"):
            self.policies.action([0.0] * 24, "ndu", covariance=-torch.eye(4), seed=5)

    def test_checkpoint_preserves_metadata_parameters_and_seeded_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policies.pt"
            self.policies.save(path)
            loaded = Policies.load(path)
            self.assertEqual(loaded.training_metadata, self.policies.training_metadata)
            for method in METHODS:
                self.assertEqual(loaded.action([0.0] * 24, method, seed=41),
                                 self.policies.action([0.0] * 24, method, seed=41))

    def test_test_labels_missing_action_support_and_bad_probabilities_rejected(self):
        trajectories = one_step_trajectories()
        trajectories[0]["split"] = "test"
        with self.assertRaisesRegex(ValueError, "train trajectories"):
            Policies().fit(trajectories, epochs=1)
        with self.assertRaisesRegex(ValueError, "every action"):
            Policies().fit(one_step_trajectories()[:2], epochs=1)
        trajectories = one_step_trajectories()
        trajectories[0]["behavior_probs"][0] = [0.0, 0.2, 0.2, 0.2, 0.2, 0.2]
        with self.assertRaisesRegex(ValueError, "full-support"):
            Policies().fit(trajectories, epochs=1)

    def test_multi_step_paths_use_actual_terminal_boundary(self):
        trajectories = []
        for first in range(6):
            for last in range(6):
                state = [0.0] * 24
                state[first] = 1.0
                state[6] = 1.0
                trajectories.append({"states": [[0.0] * 24, state], "actions": [first, last],
                                     "behavior_probs": [[1/6] * 6, [1/6] * 6],
                                     "terminal_quality": (last + 1) / 6,
                                     "terminal_loss": first / 5})
        policies = Policies(seed=31).fit(trajectories, epochs=140, learning_rate=0.01)
        self.assertEqual(policies.training_metadata["transitions"], 72)
        self.assertEqual(policies.training_metadata["action_counts"], [12] * 6)
        self.assertLess(policies.training_metadata["training_path_residual_mse"], 0.02)
        self.assertLess(policies.training_metadata["training_terminal_residual_mse"], 0.02)
        for method in METHODS:
            history = policies.training_metadata["loss_history"][method]
            self.assertLess(history[-1], history[0])


if __name__ == "__main__":
    unittest.main()
