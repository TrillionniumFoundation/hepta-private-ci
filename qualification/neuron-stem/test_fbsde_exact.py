"""Analytic and exhaustive oracles; no synthetic record is production evidence."""
import math
import unittest
from fractions import Fraction as F

from fbsde_local import LinearProfile, solve, stochastic_experiment
from fbsde_tree import (Problem, sweep, enumerate_policies, execute, WORLDS, check_nonanticipative,
                        conjunction, belief_bsde, joint_probability, polynomial_probability, posterior)


class LocalGlobalTests(unittest.TestCase):
    def test_pasted_solution_matches_monolithic_discrete_problem(self):
        for n in (16, 64, 256):
            full = solve(LinearProfile(), n)
            pasted = solve(LinearProfile(), n, 4)
            self.assertAlmostEqual(full['initial_y'], pasted['initial_y'], places=11)
            self.assertTrue(pasted['same_discrete_global_problem'])

    def test_refinement_converges_to_independent_analytic_reference(self):
        errors = [solve(LinearProfile(), n, 4)['max_trajectory_error'] for n in (16, 32, 64, 128, 256)]
        self.assertTrue(all(a > b for a, b in zip(errors, errors[1:])))
        self.assertGreater(errors[0]/errors[-1], 12)

    def test_leaf_only_success_does_not_certify_global_solution(self):
        r = solve(LinearProfile(c=0), 64, 2, reset_terminal=True)
        self.assertLess(r['local_terminal_residual'], 1e-10)
        self.assertLess(r['global_terminal_residual'], 1e-10)
        self.assertGreater(r['y_interface_residual'], 1.)
        self.assertFalse(r['same_discrete_global_problem'])

    def test_refinement_cannot_hide_regularity_failure(self):
        p = LinearProfile(); critical = p.pole()
        for t in (critical-1e-9, critical, critical+1e-3):
            for n in (16, 256, 4096):
                with self.assertRaises(ValueError): solve(LinearProfile(horizon=t), n, 4)

    def test_known_zero_driver_solution(self):
        r = solve(LinearProfile(c=0), 64, 4)
        self.assertAlmostEqual(r['initial_y'], 5., places=10)

    def test_invalid_mesh_and_nonfinite_profile(self):
        for args in ((LinearProfile(), 15, 4), (LinearProfile(horizon=float('nan')), 16, 4)):
            with self.assertRaises(ValueError): solve(*args)

    def test_same_brownian_path_refinement(self):
        rows = stochastic_experiment(paths=32, finest=256)['rows']
        self.assertLess(rows[-1]['terminal_x_rmse'], rows[0]['terminal_x_rmse']/4)
        self.assertLess(rows[-1]['global_bsde_left_rule_defect_rmse'], rows[0]['global_bsde_left_rule_defect_rmse']/4)


class TreeTests(unittest.TestCase):
    def test_whole_policy_oracle_matches_backwards_local_sweep(self):
        p = Problem()
        reference, _, count = enumerate_policies(p)
        value, policy, fields, edges = sweep(p)
        self.assertEqual(count, 1280)
        self.assertEqual(value, reference)
        self.assertEqual(value, F(33, 40))
        self.assertEqual(policy[()], 'inspect_0')
        self.assertTrue(all(e['residual'] == 0 for e in edges))
        self.assertTrue(check_nonanticipative([execute(p, policy, w)[2] for w in WORLDS]))

    def test_chance_max_is_not_conditional_expectation(self):
        _, _, _, edges = sweep(Problem())
        self.assertTrue(any(max(e['children'])-e['cost'] != e['u'] for e in edges))

    def test_oracle_future_dependent_policy_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unrevealed future'):
            check_nonanticipative([[((), 'true')], [((), 'false')]])

    def test_conjunction_requires_both_completed_obligations(self):
        with self.assertRaises(ValueError): conjunction(((0, 1),))
        self.assertFalse(conjunction(((0, 1), (1, 0))))
        self.assertTrue(conjunction(((1, 1), (0, 1))))

    def test_bad_probability_and_duplicate_observation_rejected(self):
        with self.assertRaises(ValueError): sweep(Problem(probabilities=(F(1),)*4))
        with self.assertRaises(ValueError): posterior(Problem(), ((0, 0), (0, 1)))

    def test_bsde_enumeration_and_exact_polynomial_have_same_value(self):
        formula = ('and', ('or', 0, 1), ('or', 2, 3))
        for p in ([.1,.2,.3,.4], [0,1,1,0], [.5]*4):
            u, residual, nodes = belief_bsde(formula, p)
            self.assertAlmostEqual(u, joint_probability(formula, p), places=14)
            self.assertAlmostEqual(u, polynomial_probability(formula, p), places=14)
            self.assertLess(residual, 1e-14)
            self.assertEqual(nodes, 31)

    def test_repeated_leaves_not_treated_as_independent_by_polynomial(self):
        with self.assertRaises(ValueError): polynomial_probability(('and', 0, 0), [.5])


if __name__ == '__main__': unittest.main()
