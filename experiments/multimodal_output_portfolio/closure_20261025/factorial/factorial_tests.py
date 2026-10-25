"""Check the causal contrast and target isolation needed by this experiment."""

import unittest

import numpy as np
import torch

from .analyze import contrast_weights, signs
from .heads import Gate, child_columns, objective, select
from ...v6.forecast import RidgeHead


class FactorialTests(unittest.TestCase):
    def test_plan_risk_changes_preference_for_a_bad_tail(self):
        utilities = torch.tensor([[[.4, .4], [1., -.1]]], dtype=torch.float64)
        mean_logits = torch.zeros((1, 2), requires_grad=True, dtype=torch.float64)
        risk_logits = mean_logits.detach().clone().requires_grad_(True)
        objective(mean_logits, utilities, "mean").backward()
        objective(risk_logits, utilities, "entropic").backward()
        self.assertLess(float(mean_logits.grad[0, 1]), 0.)
        self.assertGreater(float(risk_logits.grad[0, 1]), 0.)
        self.assertFalse(utilities.requires_grad)

    def test_feedback_replans_only_the_second_action_and_can_stop(self):
        gate = Gate()
        with torch.no_grad():
            for p in gate.parameters():
                p.zero_()
            gate.net[-1].bias[5] = 10.  # semantic followed by semantic
        critic = RidgeHead(673, 5)
        with torch.no_grad():
            critic.weight[-1] = torch.tensor([.4, .2, .8, .9, .7])
        features = torch.zeros(3, 5, 673)
        fixed = select(gate, critic, features, False)
        adaptive = select(gate, critic, features, True)
        self.assertEqual(fixed.tolist(), [5, 5, 5])
        self.assertEqual(adaptive.tolist(), [child_columns(1)[0]] * 3)

    def test_nonfinite_gate_evidence_rejected(self):
        with self.assertRaises(ValueError):
            objective(torch.zeros(1, 2), torch.full((1, 2, 2), float("nan")), "mean")

    def test_additive_factorial_recovers_main_effects_without_interactions(self):
        cells = [{"seed": seed, "base": base, "gate": gate, "dynamic": dynamic}
                 for seed in (17, 29, 43) for base in ("supervised", "terminal_entropic_ndu")
                 for gate in ("mean", "entropic") for dynamic in (False, True)]
        outcomes = np.array([.3 + signs(cell) @ np.array([.02, -.04, .06]) for cell in cells])
        np.testing.assert_allclose(contrast_weights(cells) @ outcomes,
                                   [.04, -.08, .12, 0., 0., 0., 0.], atol=1e-14)


if __name__ == "__main__":
    unittest.main()
