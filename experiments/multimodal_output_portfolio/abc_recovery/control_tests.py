"""Actual-tree label indexing, information reveal, and role-isolated fitting."""

import copy
from pathlib import Path
import tempfile
import unittest

import torch

from .control import (PLANS, calibration_report, feedback_paths, fit_feedback,
                      load_feedback, one_step_examples, save_feedback,
                      select_static, training_utilities)


def fixture():
    rng = torch.Generator().manual_seed(77)
    features = torch.randn((6, 5, 673), generator=rng)
    features[:, :, -1] = .5
    features[:, 0, -1] = 1.
    utility = torch.rand((6, 21), generator=rng) * 2 - 1
    metrics = {"utility": utility, "text_fact": torch.zeros_like(utility),
               "relation": torch.zeros_like(utility), "image_fact": torch.ones_like(utility),
               "pixel_mse": torch.zeros_like(utility)}
    return {"features": features, "plans": PLANS, "metrics": {"primary": metrics},
            "role": "forecast_fit", "pair_start": 384}


class ControlTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)

    def test_labels_bind_to_actual_prefix_and_budget(self):
        data = fixture()
        features, utility = one_step_examples(data)
        self.assertTrue(torch.equal(features[:, -1], torch.full((30,), .5)))
        self.assertTrue(torch.equal(data["features"][:, 0, -1], torch.ones(6)))
        values = utility.reshape(6, 5, 5)
        for first in range(4):
            self.assertTrue(torch.equal(values[:, first + 1, 0],
                                        data["metrics"]["primary"]["utility"][:, first + 1]))
            for second in range(4):
                self.assertTrue(torch.equal(values[:, first + 1, second + 1],
                                            data["metrics"]["primary"]["utility"][:, 5 + 4 * first + second]))
        masked, _ = one_step_examples(data, draft_mode="masked")
        self.assertEqual(float(masked[:, 384:672].abs().sum()), 0.)
        torch.testing.assert_close(training_utilities(data, "local"),
                                   torch.full((6, 21), 1 - 2 * .35 / .90))

    def test_second_decision_receives_only_committed_child(self):
        seen = []

        class PublicPolicy:
            def choose(self, features, remaining):
                seen.append((features.clone(), remaining))
                return torch.tensor([0, 1, 2, 3, 4, 1]) if remaining == 2 else torch.zeros(len(features), dtype=torch.long)

        data = fixture()
        paths = feedback_paths(PublicPolicy(), data["features"])
        self.assertEqual(paths.tolist(), [0, 1, 2, 3, 4, 1])
        self.assertEqual(seen[0][1], 2)
        torch.testing.assert_close(seen[0][0], data["features"][:, 0])
        for action, (actual, remaining) in enumerate(seen[1:], 1):
            selected = torch.tensor([0, 1, 2, 3, 4, 1]) == action
            self.assertEqual(remaining, 1)
            torch.testing.assert_close(actual, data["features"][selected, action])

    def test_primary_only_fitting_freezing_roundtrip_and_role_rejection(self):
        data = fixture()
        config = {"hidden_dim": 8, "batch_size": 30, "learning_rate": .003, "steps_per_horizon": 6}
        first = fit_feedback(data, "allocation_only_feedback", 55, config)
        changed = copy.deepcopy(data)
        changed["metrics"]["secondary"] = {"utility": torch.full((6, 21), 100000.)}
        second = fit_feedback(changed, "allocation_only_feedback", 55, config)
        for a, b in zip(first.critic.two_step_model.parameters(), second.critic.two_step_model.parameters()):
            torch.testing.assert_close(a, b, rtol=0, atol=0)
        paths = feedback_paths(first, data["features"])
        self.assertTrue(all(all(action in {"refine_image", "refine_text"} for action in PLANS[int(i)]) for i in paths))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.pt"
            save_feedback(first, path)
            restored = load_feedback(path)
            self.assertTrue(torch.equal(feedback_paths(restored, data["features"]), paths))
        changed["role"] = "development"
        with self.assertRaises(ValueError):
            fit_feedback(changed, "feedback", 55, config)
        with self.assertRaises(ValueError):
            select_static(data)
        with self.assertRaises(ValueError):
            calibration_report(first, data)
        changed["pair_start"] = 736
        choice = select_static(changed)
        self.assertIn(choice["plan_index"], range(21))


if __name__ == "__main__":
    unittest.main()
