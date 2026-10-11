"""Adversarial and numerical controls for the registered coupled discretization."""
from dataclasses import asdict, replace
import math
import random
import unittest
from fbsde_coupled import (CoupledProfile, global_map, solve_global, residual_report,
                           continuation_fields, trace_fields, _interpolate)
from fbsde_coupled_reference import monolithic_reference, residual_and_jacobian


class CoupledTests(unittest.TestCase):
    def test_global_matches_independent_dense_reference(self):
        for n in (2, 4, 6):
            p = CoupledProfile(steps=n)
            r = monolithic_reference(asdict(p), .45)
            s = solve_global(p, .45)
            error = max(abs(a-b) for a, b in zip(r['y'], s['y']))
            self.assertLess(error, s['report']['y_error_bound_exact_arithmetic']+1e-12)
            self.assertGreater(s['report']['max_abs_generator'], .01)
            self.assertGreater(s['report']['max_abs_z'], .01)

    def test_same_global_q_cannot_be_fixed_by_more_steps(self):
        for n in (2, 5, 10):
            with self.assertRaisesRegex(ValueError, 'global contraction'):
                solve_global(CoupledProfile(horizon=1., a=.8, beta=.5, steps=n), .2)

    def test_actual_map_respects_derived_contraction_bound(self):
        p = CoupledProfile(steps=4)
        rng = random.Random(137)
        for _ in range(12):
            a = [rng.uniform(-2, 2) for _ in range(15)]
            b = [rng.uniform(-2, 2) for _ in range(15)]
            ma, mb = global_map(p, .3, a), global_map(p, .3, b)
            self.assertLessEqual(max(abs(x-y) for x, y in zip(ma, mb)),
                                 p.q*max(abs(x-y) for x, y in zip(a, b))+1e-12)

    def test_refinement_and_wrong_suffix_control(self):
        p = CoupledProfile()
        ref = monolithic_reference(asdict(p), .45)
        errors = []
        for dx in (.5, .125, .03125):
            trace = trace_fields(p, .45, continuation_fields(p, dx))
            errors.append(max(abs(a-b) for a, b in zip(trace['y'], ref['y'])))
            self.assertLessEqual(errors[-1], trace['report']['y_error_bound_exact_arithmetic']+1e-11)
        self.assertLess(errors[-1], errors[0]/20)
        wrong = trace_fields(p, .45, continuation_fields(p, .03125, reset_at=(2, 4)))
        self.assertGreater(wrong['max_reset_interface_jump'], .05)
        self.assertGreater(wrong['report']['fixed_point_residual'], .02)

    def test_corrector_uses_original_problem_not_local_terminal_success(self):
        p = CoupledProfile()
        wrong = trace_fields(p, .45, continuation_fields(p, .0625, reset_at=(2, 4)))
        corrected = solve_global(p, .45, initial=wrong['y'])
        cold = solve_global(p, .45)
        self.assertLess(max(abs(a-b) for a, b in zip(corrected['y'], cold['y'])), 2e-10)

    def test_no_feedback_zero_generator_has_direct_expectation(self):
        p = CoupledProfile(a=0, beta=0, lam=0, steps=4)
        s = solve_global(p, .37)
        expectation = sum(math.tanh(x) for x in s['x'][15:])/16
        self.assertAlmostEqual(s['y'][0], expectation, places=13)

    def test_jacobian_matches_finite_differences(self):
        p = asdict(CoupledProfile(steps=3))
        y = [.03*i for i in range(7)]
        r, jac, _ = residual_and_jacobian(p, .2, y)
        for j in range(7):
            yp = y[:]; yp[j] += 1e-6
            ym = y[:]; ym[j] -= 1e-6
            plus = residual_and_jacobian(p, .2, yp)[0]
            minus = residual_and_jacobian(p, .2, ym)[0]
            for i in range(7):
                self.assertAlmostEqual(jac[i][j], (plus[i]-minus[i])/2e-6, places=7)

    def test_initial_and_nonfinite_inputs_rejected(self):
        for value in (float('nan'), float('inf'), True, 8.):
            with self.assertRaises(ValueError):
                solve_global(CoupledProfile(), value)
        with self.assertRaises(ValueError):
            global_map(CoupledProfile(), 0., [float('nan')]*31)
        with self.assertRaises(ValueError):
            global_map(CoupledProfile(), 0., [0.]*32)

    def test_wrong_profile_cannot_reuse_continuation_field(self):
        p = CoupledProfile()
        fields = continuation_fields(p, .25)
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            trace_fields(replace(p, sigma=.31), .3, fields)

    def test_missing_domain_never_extrapolates(self):
        with self.assertRaisesRegex(ValueError, 'domain exhausted'):
            _interpolate([-1., 1.], [-.5, .5], 1.01)

    def test_budget_exhaustion_is_not_a_solution(self):
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            solve_global(CoupledProfile(), .4, max_iterations=1)

    def test_last_terminal_alone_cannot_certify(self):
        p = CoupledProfile()
        r = residual_report(p, .45, [0.]*31)
        # Terminal values are exactly tanh(X_T) by construction, but all earlier Ys are wrong.
        self.assertGreater(r['fixed_point_residual'], .1)
        self.assertFalse(r['continuous_time_error_bounded'])
        self.assertFalse(r['float_roundoff_rigorously_enclosed'])


if __name__ == '__main__':
    unittest.main()
