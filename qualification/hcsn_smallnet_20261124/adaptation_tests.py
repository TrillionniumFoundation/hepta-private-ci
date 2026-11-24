"""Mathematical, budget, preservation, and unopened-holdout controls."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from torch import nn

from . import adaptation_suite as suite
from .editing import tensor_digest


class _Head(nn.Module):
    def __init__(self):
        super().__init__()
        self.readout = nn.Linear(3, 2, dtype=torch.float64)
        self.register_buffer("protected_physics", torch.tensor([.7, 1.2], dtype=torch.float64))
        with torch.no_grad():
            self.readout.weight.zero_()
            self.readout.bias.zero_()


class AdaptationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        generator = torch.Generator().manual_seed(7361)
        x = torch.randn(80, 3, generator=generator, dtype=torch.float64)
        y = (x[:, 0] + .2 * x[:, 1] > 0).long()
        bundle = suite.FeatureBundle(x, y, torch.arange(80) % 4, "fixture-only")
        self.bundles = {key: bundle for key in ("train", "new_dev", "old_dev")}
        self.model = _Head()
        self.editing = {"ridge": .01, "bp_steps": 96, "cpu_seconds": 10.,
                        "max_dev_old_accuracy_loss": .02, "max_dev_old_brier_increase": .02}

    def test_closed_solution_has_zero_gradient_for_identical_objective(self):
        bundle = self.bundles["train"]
        matrix, targets = bundle.augmented(), bundle.targets()
        solution, receipt = suite.solve_ridge(matrix, targets, .01)
        theta = solution.detach().requires_grad_()
        gradient = torch.autograd.grad(suite.ridge_objective(theta, matrix, targets, .01), theta)[0]
        self.assertLess(float(gradient.abs().max()), 1e-10)
        self.assertEqual(receipt["normalization_denominator"], 160)
        self.assertFalse(receipt["bias_regularized"])
        self.assertTrue(receipt["normal_condition_2"] >= 1)

    def test_unregularized_bias_fits_constant_target_without_spurious_weights(self):
        matrix = self.bundles["train"].augmented()
        target = torch.tensor([-1., 1.], dtype=torch.float64).expand(len(matrix), 2)
        theta, _ = suite.solve_ridge(matrix, target, .5)
        torch.testing.assert_close(theta[:-1], torch.zeros_like(theta[:-1]), atol=1e-12, rtol=0)
        torch.testing.assert_close(theta[-1], target[0], atol=1e-12, rtol=0)

    def test_bp_analytic_share_optimum_with_hard_gradient_budget_and_no_parent_mutation(self):
        before = tensor_digest(self.model.state_dict())
        analytical, direct, _ = suite.run_head_method("ANALYTIC", self.model, self.bundles, self.editing)
        optimized, bp, _ = suite.run_head_method("BP", self.model, self.bundles, self.editing)
        self.assertEqual(direct["adoption"], "ADOPT")
        self.assertEqual(bp["adoption"], "ADOPT")
        self.assertLess(abs(bp["selected_train_objective"] - direct["selected_train_objective"]), 2e-6)
        self.assertLessEqual(bp["counters"]["closure_calls"], 96)
        self.assertEqual(bp["counters"]["closure_calls"], bp["counters"]["backward_calls"])
        self.assertEqual(bp["counters"]["closure_calls"], bp["counters"]["optimizer_steps_completed"])
        self.assertLessEqual(bp["counters"]["development_candidates"], 4)
        self.assertEqual(bp["solver"]["termination_reason"], "gradient_converged")
        self.assertLess(bp["counters"]["closure_calls"], 96)
        self.assertEqual(tensor_digest(self.model.state_dict()), before)
        self.assertEqual(analytical.shape, optimized.shape)

    def test_bp_already_optimal_head_stops_after_one_closure_and_one_query(self):
        bundle = self.bundles["train"]
        optimum, _ = suite.solve_ridge(bundle.augmented(), bundle.targets(), self.editing["ridge"])
        with torch.no_grad():
            self.model.readout.weight.copy_(optimum[:-1].T)
            self.model.readout.bias.copy_(optimum[-1])
        selected, report, _ = suite.run_head_method("BP", self.model, self.bundles, self.editing)
        self.assertEqual(report["solver"]["termination_reason"], "gradient_converged")
        self.assertEqual(report["counters"]["closure_calls"], 1)
        self.assertEqual(report["counters"]["backward_calls"], 1)
        self.assertEqual(report["counters"]["development_candidates"], 1)
        self.assertEqual(report["adoption"], "KEEP")
        self.assertTrue(torch.equal(selected, suite.head_theta(self.model.state_dict())))

    def test_strict_unidentified_rule_abstains_without_solver_or_gradients(self):
        before = tensor_digest(self.model.state_dict())
        with patch.object(suite, "solve_ridge", side_effect=AssertionError("label-based solve forbidden")):
            selected, report, _ = suite.run_head_method("STRICT_WSP", self.model, self.bundles, self.editing)
        self.assertEqual(report["status"], "ABSTAIN")
        self.assertEqual(report["adoption"], "KEEP")
        self.assertEqual(report["counters"]["backward_calls"], 0)
        self.assertEqual(report["counters"]["development_candidates"], 0)
        self.assertFalse(report["solver"]["weight_program"]["protocol"]["label_fitting"])
        self.assertTrue(torch.equal(selected, suite.head_theta(self.model.state_dict())))
        self.assertEqual(tensor_digest(self.model.state_dict()), before)

    def test_old_retention_refuses_conflicting_new_label_schema_for_both_supervised_rules(self):
        with torch.no_grad():
            self.model.readout.weight[0, 0] = -2
            self.model.readout.weight[1, 0] = 2
        x = torch.zeros(40, 3, dtype=torch.float64)
        x[:, 0] = torch.linspace(-1, 1, 40)
        old_labels = (x[:, 0] > 0).long()
        old = suite.FeatureBundle(x, old_labels, torch.arange(40) % 4, "old")
        new = suite.FeatureBundle(x, 1 - old_labels, torch.arange(40) % 4, "contradictory-new")
        bundles = {"train": new, "new_dev": new, "old_dev": old}
        settings = {**self.editing, "max_dev_old_accuracy_loss": 0., "max_dev_old_brier_increase": 0.}
        for method in ("ANALYTIC", "HYBRID"):
            selected, report, _ = suite.run_head_method(method, self.model, bundles, settings)
            self.assertEqual(report["adoption"], "KEEP", method)
            self.assertTrue(all(not row["retention_eligible"] for row in report["history"]))
            self.assertTrue(torch.equal(selected, suite.head_theta(self.model.state_dict())))

    def test_failed_solve_retains_parent_and_records_attempt_and_cost(self):
        with patch.object(suite, "solve_ridge", side_effect=FloatingPointError("injected numerical failure")):
            selected, report, _ = suite.run_head_method("ANALYTIC", self.model, self.bundles, self.editing)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["adoption"], "KEEP")
        self.assertEqual(report["counters"]["conditional_solve_attempts"], 1)
        self.assertEqual(report["counters"]["linear_system_solves"], 0)
        self.assertGreater(report["construction_selection_cpu_seconds"], 0)
        self.assertIn("injected numerical failure", report["error"])
        self.assertTrue(torch.equal(selected, suite.head_theta(self.model.state_dict())))
        json.dumps(report, allow_nan=False)

    def test_incomplete_global_roster_is_rejected_before_constructing_holdout(self):
        p = {"source_hashes": {}, "independent_neurons": [8], "seeds": [101]}
        ap = {"fixture": "bound"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            training_seal = root / "training_seal.json"
            adaptation_seal = root / "adaptation_seal.json"
            training_seal.write_text(json.dumps({"source_hashes": {}, "protocol_sha256": suite.training.protocol_digest(p), "attempts": {}}))
            adaptation_seal.write_text(json.dumps({"adaptation_protocol_sha256": suite.training.protocol_digest(ap), "attempts": {}}))
            output = root / "n8-qvi_full-s101"
            output.mkdir()
            with patch.object(suite, "validate_adaptation_protocol"), \
                    patch.object(suite.training, "validate_attempts", return_value={}), \
                    patch.object(suite, "make_data", side_effect=AssertionError("holdout must remain unopened")) as data:
                with self.assertRaises(ValueError):
                    suite.final_test_adaptation(p, output, adaptation_protocol=ap,
                        training_seal_path=training_seal, adaptation_seal_path=adaptation_seal)
                data.assert_not_called()
                self.assertFalse((output / "FINAL_CLAIM").exists())


if __name__ == "__main__":
    unittest.main()
