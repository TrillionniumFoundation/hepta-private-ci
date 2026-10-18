"""Independent numerical checks against a solvable quadratic reference."""

import unittest

from analytic_reference import evaluate_analytic_reference
from ndu_fbsde_tree import FbsdeShadowGateV1


class AnalyticReferenceTests(unittest.TestCase):
    def test_local_semigroup_recovers_exact_conditional_root(self):
        observed = evaluate_analytic_reference(samples=512)
        self.assertEqual(observed.node_count, 31)
        self.assertAlmostEqual(observed.root_value, 1.0, places=12)
        self.assertLessEqual(observed.maximum_value_field_error, 1e-12)
        self.assertLessEqual(observed.terminal_residual, 1e-12)

    def test_conditional_covariance_recovers_z_and_single_branch_does_not(self):
        for steps in (1, 2, 4, 6):
            observed = evaluate_analytic_reference(steps=steps, samples=256)
            self.assertLessEqual(observed.maximum_z_covariance_error, 1e-12)
            self.assertAlmostEqual(observed.root_value, 1.0, places=12)
            self.assertGreater(observed.single_branch_global_gap, 0.1)

    def test_independent_gaussian_heldout_matches_analytic_value_with_error_bars(self):
        observed = evaluate_analytic_reference()
        self.assertTrue(observed.heldout_pass)
        self.assertLess(
            abs(observed.heldout_estimate - observed.exact_global_value),
            4.0 * observed.heldout_standard_error,
        )
        self.assertNotEqual(observed.train_estimate, observed.heldout_estimate)
        self.assertEqual(
            observed.evidence_digest(), evaluate_analytic_reference().evidence_digest()
        )
        self.assertEqual(observed.authority, "DENY_ALL")
        self.assertFalse(observed.production_activated)
        self.assertFalse(observed.learned_model_efficacy_measured)

    def test_single_path_cannot_pass_global_gate_despite_zero_local_residual(self):
        reference = evaluate_analytic_reference(samples=512)
        gate = FbsdeShadowGateV1(
            terminal_residual=reference.terminal_residual,
            interface_residual=reference.maximum_value_field_error,
            z_residual=reference.maximum_z_covariance_error,
            semigroup_residual=reference.maximum_value_field_error,
            branch_global_gap=reference.single_branch_global_gap,
            interval_margin=0.05,
            covariance_condition=1.0,
            heldout_path_pass=reference.heldout_pass,
            boundary_immutable=True,
            prompt_injection_rejected=True,
            resource_ok=True,
            evidence_complete=True,
        )
        self.assertEqual(gate.advisory()["decision"], "NO_GO")
        self.assertIn("branch_global_gap", gate.reasons())

    def test_invalid_horizon_and_reused_paths_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate_analytic_reference(steps=0)
        with self.assertRaises(ValueError):
            evaluate_analytic_reference(steps=11)
        with self.assertRaises(ValueError):
            evaluate_analytic_reference(samples=1)
        with self.assertRaises(ValueError):
            evaluate_analytic_reference(train_seed=4, heldout_seed=4)

    def test_node_envelope_bounded(self):
        observed = evaluate_analytic_reference(steps=10, samples=64)
        self.assertEqual(observed.node_count, 2047)
        self.assertLessEqual(observed.maximum_value_field_error, 1e-11)
        self.assertLessEqual(observed.maximum_z_covariance_error, 1e-11)


if __name__ == "__main__":
    unittest.main()
