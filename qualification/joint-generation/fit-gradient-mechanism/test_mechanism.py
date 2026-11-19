"""Handmade scalar and saved-summary checks only; no model/data loading."""
import copy
import json
import math
from pathlib import Path
import unittest
from mechanism import conditional_rho2_coefficients, frozen_gates


def cells():
    return [{'paired_seed_slot': seed, 'anchor': anchor, 'trained_mode': mode,
             'shared_body': {'requests': 20, 'conflicts': {'T_I': 11, 'T_A': 2, 'T_N': 3},
                             'median_image_text_norm_ratio': 2.0}}
            for seed in (1, 2) for anchor in ('C', 'E') for mode in ('S', 'A', 'N')]


class MechanismChecks(unittest.TestCase):
    def test_exact_boundary_coefficients(self):
        x = conditional_rho2_coefficients(1, .5)
        self.assertAlmostEqual(x['N_to_A_p'], math.e-1, places=14)
        self.assertEqual(x['N_to_A_q'], 1)
        self.assertIsNone(conditional_rho2_coefficients(.5, 0)['N_to_A_p'])
        self.assertIsNone(conditional_rho2_coefficients(0, .5)['N_to_A_q'])

    def test_coefficients_match_independent_centered_differences(self):
        p, q, h = .4, .7, 1e-5
        ce = lambda p, q: -math.log1p(-p*(-math.expm1(-2*q)))/2
        x = conditional_rho2_coefficients(p, q)
        self.assertAlmostEqual((ce(p+h, q)-ce(p-h, q))/(2*h), x['CE_p'], places=9)
        self.assertAlmostEqual((ce(p, q+h)-ce(p, q-h))/(2*h), x['CE_q'], places=9)

    def test_image_coefficient_bound_on_fixed_literal_grid(self):
        for p in (0, .1, .5, .9, 1):
            for q in (0, .1, .5, .9, 1):
                x = conditional_rho2_coefficients(p, q)
                self.assertLessEqual(x['CE_q'], p+1e-15)
                self.assertGreaterEqual(x['CE_q'], 0)

    def test_invalid_coefficients_reject(self):
        for bad in (True, None, -.1, 1.1, math.inf, math.nan):
            with self.assertRaises(ValueError):conditional_rho2_coefficients(bad, .5)
            with self.assertRaises(ValueError):conditional_rho2_coefficients(.5, bad)

    def test_both_seeds_and_strict_thresholds_required(self):
        rows = cells()
        self.assertTrue(frozen_gates(rows)['H1_any_gate'])
        for row in rows:
            if row['paired_seed_slot'] == 2:
                row['shared_body']['conflicts']['T_I'] = 10
                row['shared_body']['conflicts']['T_N'] = 2
        result = frozen_gates(rows)
        self.assertFalse(result['H1_any_gate'])
        self.assertFalse(result['H2_any_gate'])
        rows = cells()
        for row in rows:row['shared_body']['median_image_text_norm_ratio'] = 1
        self.assertFalse(frozen_gates(rows)['H1_any_gate'])

    def test_zero_norm_null_is_not_success(self):
        rows = cells()
        for row in rows:row['shared_body']['median_image_text_norm_ratio'] = None
        self.assertFalse(frozen_gates(rows)['H1_any_gate'])

    def test_missing_duplicate_malformed_inventory_rejects(self):
        for rows in (cells()[:-1], cells()+[cells()[0]]):
            with self.assertRaises(ValueError):frozen_gates(rows)
        for key, value in (('requests', True), ('requests', 19), ('median_image_text_norm_ratio', math.nan)):
            rows = cells();rows[0]['shared_body'][key] = value
            with self.assertRaises(ValueError):frozen_gates(rows)
        rows = cells();rows[0]['shared_body']['conflicts']['T_N'] = -1
        with self.assertRaises(ValueError):frozen_gates(rows)

    def test_saved_deidentified_summary_recomputes_both_negative_gates(self):
        saved = json.loads(Path(__file__).with_name('SUMMARY.json').read_text())
        result = frozen_gates(saved['per_cell_summary'])
        self.assertEqual(result['H1_any_gate'], saved['H1_any_gate'])
        self.assertEqual(result['H2_any_gate'], saved['H2_any_gate'])
        self.assertFalse(result['H1_any_gate'])
        self.assertFalse(result['H2_any_gate'])


if __name__ == '__main__':unittest.main()
