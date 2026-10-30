"""Instrumentation tests; manual weights here are not learned-policy evidence."""

from pathlib import Path
import tempfile
import unittest

import torch

from experiments.multimodal_output_portfolio.joint_hepta_20261029.diagnostics_v2.controller_feedback import (
    intervention_triplet, policy_probe, public_feedback_interventions,
)
from experiments.multimodal_output_portfolio.joint_hepta_20261029.mechanism_data import batch
from experiments.multimodal_output_portfolio.joint_hepta_20261029.model import ACTIONS, JointGenerator, tensor_digest
from experiments.multimodal_output_portfolio.joint_hepta_20261029.runtime import make_profile


class FeedbackDiagnosticTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1); torch.manual_seed(7)
        self.model = JointGenerator(width=8)
        self.public, self.target = batch([0], "controller-v2-development")

    def test_public_intervention_bounds(self):
        values = public_feedback_interventions(self.public)
        self.assertEqual(tuple(values["high"].shape), (1, 3))
        self.assertTrue(torch.equal(values["low"], torch.zeros(1, 3)))
        self.assertTrue(bool((values["high"] > 0).all()))
        self.assertTrue(bool((values["high"] <= torch.tensor([[1, 4, 1]])).all()))
        masked = {k: v.clone() for k, v in self.public.items()}
        for modality in ("image", "audio", "video"):
            masked[modality + "_mask"].zero_()
        self.assertTrue(torch.equal(public_feedback_interventions(masked)["high"], torch.zeros(1, 3)))

    def test_fixed_budget_probe_can_detect_invariant_actor(self):
        with torch.no_grad():
            for parameter in self.model.actor.parameters():
                parameter.zero_()
            probe = policy_probe(self.model, self.public, public_feedback_interventions(self.public), 7)
        self.assertEqual(probe["total_variation"], 0)
        self.assertFalse(probe["distribution_changed"])
        self.assertFalse(probe["physical_timing_equivalence_claimed"])

    def test_real_triplet_detects_paths_and_byte_changes_with_repeat_control(self):
        with torch.no_grad():
            for parameter in self.model.actor.parameters():
                parameter.zero_()
            self.model.actor[0].weight[0, 2 * self.model.width] = 4
            self.model.actor[-1].bias.fill_(-20)
            self.model.actor[-1].weight[ACTIONS.index("image"), 0] = 10
            self.model.actor[-1].weight[ACTIONS.index("audio"), 0] = -10
            self.model.actor[-1].bias[ACTIONS.index("image")] = 0
            self.model.actor[-1].bias[ACTIONS.index("audio")] = 1
            original = tensor_digest(self.model.state_dict())
            with tempfile.TemporaryDirectory() as root:
                result = intervention_triplet(self.model, self.public, self.target, Path(root),
                    profile=make_profile(), source=0, seed=7, strategy="greedy")
                self.assertEqual(len(list(Path(root).rglob("TRAJECTORY.json"))), 3)
        self.assertTrue(result["fixed_budget_policy_probe"]["distribution_changed"])
        self.assertTrue(result["actions_and_outputs_changed"])
        self.assertTrue(result["same_feedback_control_actions_identical"])
        self.assertTrue(result["same_feedback_control_outputs_identical"])
        self.assertEqual(result["failures"], 0)
        self.assertEqual(original, tensor_digest(self.model.state_dict()))
        self.assertFalse(result["physical_timing_exact_reproduction_claimed"])


if __name__ == "__main__":
    unittest.main()
