"""Real-Torch support conformance on synthetic states, not calibration evidence."""

import unittest

import torch

from .action_effects import public_actions
from .controllers import ACTIONS, ControlPlan, PublicState
from .neural import CONTENT_WIDTH, STATE_WIDTH, FittedPredictor, ReceiptPortfolioModel
from .objective import forecast_seed
from .recursive_objective import DifferentiablePlanner


class ForecastSupportTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(17)
        self.model = ReceiptPortfolioModel().eval().requires_grad_(False)
        self.seed = 19

    def forecast_both(self, x, legal, action, *, step=2):
        plan = ControlPlan(particles=2)
        public = PublicState(tuple(x.tolist()), 100.0, step, tuple(legal))
        rows = FittedPredictor(self.model).forecast(
            public, action, plan.particles, forecast_seed(self.seed, step, action)
        )
        x = x.detach().requires_grad_(True)
        prediction = DifferentiablePlanner(self.model, plan, self.seed).forecast(
            x, action, step, x.new_tensor(100.0), tuple(legal)
        )
        features, duration, following = prediction
        self.assertEqual([row.legal_actions for row in rows], [following] * 2)
        torch.testing.assert_close(
            torch.tensor([row.next_features for row in rows]), features
        )
        self.assertEqual(tuple(features.shape), (2, STATE_WIDTH))
        (features.sum() + duration).backward()
        self.assertTrue(bool(torch.isfinite(x.grad).all()))
        return features.detach()[0], following

    def test_read_consumes_permission_and_writes_do_not_recreate_it(self):
        x = torch.zeros(STATE_WIDTH)
        x[CONTENT_WIDTH + 8] = 1.0  # Preparation remains after a read.
        for mode in ("reset", "persistent"):
            with self.subTest(mode=mode):
                plan = ControlPlan(particles=2, memory_mode=mode)
                rows = FittedPredictor(self.model, memory_mode=mode).forecast(
                    PublicState(tuple(x.tolist()), 100.0, 1, ACTIONS),
                    "READ_ROI",
                    plan.particles,
                    3,
                )
                self.assertNotIn("READ_ROI", rows[0].legal_actions)
        successor, legal = self.forecast_both(x, ACTIONS, "READ_ROI")
        self.assertEqual(float(successor[CONTENT_WIDTH + 8]), 1.0)
        successor, legal = self.forecast_both(successor, legal, "WRITE_TEXT")
        self.assertNotIn("READ_ROI", legal)
        with self.assertRaisesRegex(ValueError, "outside current public support"):
            self.forecast_both(successor, legal, "READ_ROI")

    def test_first_preparation_enables_read_and_non_geometric_actions_preserve_it(self):
        x = torch.zeros(STATE_WIDTH)
        legal = tuple(a for a in ACTIONS if a != "READ_ROI")
        successor, legal = self.forecast_both(x, legal, "PREPARE_ROI")
        self.assertIn("READ_ROI", legal)
        _, following = self.forecast_both(successor, legal, "WRITE_TEXT")
        self.assertIn("READ_ROI", following)

    def test_ambiguous_preparation_waits_for_actual_host_geometry(self):
        x = torch.zeros(STATE_WIDTH)
        x[CONTENT_WIDTH + 8 : CONTENT_WIDTH + 10] = 1.0
        _, hypothetical = self.forecast_both(x, ACTIONS, "PREPARE_ROI")
        self.assertNotIn("READ_ROI", hypothetical)
        packet = {
            "requirements": {"image": True},
            "initial_delivery": {"image": None},
        }
        state = {
            "observation": {"kind": "roi", "bbox": [0, 0, 20, 20]},
            "prepared_roi": [0, 0, 20, 20],
            "text_committed": False,
        }
        self.assertNotIn("READ_ROI", public_actions(packet, state))
        state["prepared_roi"] = [20, 0, 40, 20]
        self.assertIn("READ_ROI", public_actions(packet, state))

    def test_terminal_and_other_action_restrictions_are_preserved(self):
        x = torch.zeros(STATE_WIDTH)
        legal = ("PREPARE_ROI", "STOP")
        _, following = self.forecast_both(x, legal, "PREPARE_ROI")
        self.assertEqual(following, ("PREPARE_ROI", "READ_ROI", "STOP"))
        for action, step in (("STOP", 2), ("PREPARE_ROI", 7)):
            _, following = self.forecast_both(x, legal, action, step=step)
            self.assertEqual(following, ("STOP",))


if __name__ == "__main__":
    unittest.main()
