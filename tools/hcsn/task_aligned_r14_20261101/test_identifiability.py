"""Independent checks of flow equivalence, observable gradients and gauges."""

import unittest

import numpy as np

from ..unified_cell_r12_20261031.cell import Cell
from .identifiability import observable_table, reduced_cell, run_audit


class IdentifiabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = run_audit()

    def test_physical_flow_rank_and_known_null(self):
        self.assertEqual(self.audit["full_physical_spectrum"]["rank"], 2)
        self.assertEqual(self.audit["fixed_maturity_spectrum"]["rank"], 2)
        self.assertLess(self.audit["generator_prior_emission_null_residual_max"], 1e-10)
        self.assertLess(self.audit["raw_law_null_residual_max"], 1e-11)

    def test_raw_symbol_derivative_against_independent_perturbations(self):
        self.assertLess(self.audit["forward_vs_central_jacobian_max_abs_error"], 2e-7)
        np.testing.assert_allclose(self.audit["observation_probability_sums"], 1., atol=1e-12, rtol=0)

    def test_joint_observable_rank_after_physical_and_emission_gauge_removal(self):
        joint = self.audit["joint_observation_spectra"]
        self.assertEqual(joint["physical_plus_twelve_logits"]["rank"], 12)
        self.assertEqual(joint["fixed_maturity_plus_ten_logit_coordinates"]["rank"], 12)
        self.assertLess(joint["forward_vs_central_joint_jacobian_max_abs_error"], 2e-7)
        self.assertLess(joint["joint_and_physical_raw_law_max_abs_difference"], 1e-13)

    def test_equivalent_raw_flows_do_not_determine_fees(self):
        profiles = [p for p in self.audit["equal_boundary_profile"] if p["status"] == "equivalent_flow"]
        self.assertGreaterEqual(len(profiles), 2)
        for profile in profiles:
            self.assertLess(profile["generator_max_abs_error"], 1e-10)
            self.assertLess(profile["raw_law_max_abs_error"], 1e-11)
            self.assertLess(abs(profile["population_nll_change_sum_across_designs"]), 1e-11)
        self.assertGreater(max(p["read_fee_max_abs_difference"] for p in profiles), 1e-4)

    def test_emission_gauges_and_label_permutation(self):
        for key in ("softmax_shift_max_abs_error", "two_row_shift_jacobian_residual_max",
                    "bit_label_swap_raw_law_max_abs_error"):
            self.assertLess(self.audit["emission_gauge"][key], 1e-13)

    def test_reset_uses_actual_successor_before_read(self):
        cell = reduced_cell(.3, .02)
        design = (((.15, "RESET"), (.45, "READ")),)
        raw, derivative = observable_table(cell, design)
        expected = cell.prior @ cell.R @ cell.transition(.15) @ cell.transition(.45) @ cell.E
        np.testing.assert_allclose(raw, expected, atol=1e-13, rtol=0)
        np.testing.assert_allclose(derivative.sum(axis=0), 0., atol=1e-11, rtol=0)

    def test_fixed_maturity_retains_explicit_canonical_cell(self):
        reduced, original = reduced_cell(.27, .016), Cell([.27, .016, 1.3])
        np.testing.assert_array_equal(reduced.Q, original.Q)
        np.testing.assert_array_equal(reduced.prior, original.prior)
        np.testing.assert_allclose(reduced.emission_logits.mean(axis=1), 0., atol=1e-15, rtol=0)

    def test_gauge_canonicalization_preserves_all_raw_sequence_laws(self):
        original = Cell()
        shifted = original.emission_logits + np.array([[2.], [-1.5]])
        reduced = reduced_cell(*original.theta[:2], emission_logits=shifted)
        np.testing.assert_allclose(reduced.emission_logits.mean(axis=1), 0., atol=1e-15, rtol=0)
        np.testing.assert_allclose(observable_table(reduced)[0], observable_table(original)[0], atol=1e-14, rtol=0)


if __name__ == "__main__":
    unittest.main()
