"""Same-equation solver and integration regressions; no performance thresholds."""
import copy
from dataclasses import asdict, replace
import math
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from four_gate_common import digest
from fbsde_coupled import CoupledProfile, global_map, solve_global, residual_report
from fbsde_coupled_reference import residual_and_jacobian, _linear, monolithic_reference
from fbsde_riccati import linear_field, linear_trace, newton_direction, solve_newton
from fbsde_riccati_audit import original_metrics


class RiccatiTests(TestCase):
    def test_direction_matches_independent_dense_jacobian(self):
        p = CoupledProfile(steps=4)
        y = [.07*i-.2 for i in range(2**p.steps-1)]
        r, jac, _ = residual_and_jacobian(asdict(p), .45, y)
        expected = _linear(jac, [-v for v in r])
        actual = newton_direction(p, .45, y)
        self.assertLess(max(abs(a-b) for a, b in zip(actual['dy'], expected)), 1e-12)
        self.assertEqual(actual['dx'][0], 0.)

    def test_direction_matches_finite_difference_action(self):
        p = CoupledProfile(steps=3)
        y = [-.1+i*.13 for i in range(7)]
        direction = newton_direction(p, -.3, y)['dy']
        eps = 1e-6
        r, _, _ = residual_and_jacobian(asdict(p), -.3, y)
        plus = residual_and_jacobian(asdict(p), -.3, [a+eps*b for a,b in zip(y,direction)])[0]
        minus = residual_and_jacobian(asdict(p), -.3, [a-eps*b for a,b in zip(y,direction)])[0]
        self.assertLess(max(abs((a-b)/(2*eps)+c) for a,b,c in zip(plus,minus,r)), 1e-8)

    def test_original_problem_and_reference_agree(self):
        for sigma in (0., .3):
            p = CoupledProfile(steps=5, sigma=sigma)
            for x0 in (-.8, 0., .2):
                with self.subTest(sigma=sigma, x0=x0):
                    result = solve_newton(p, x0)
                    ref = monolithic_reference(asdict(p), x0)
                    self.assertLess(max(abs(a-b) for a,b in zip(result['y'],ref['y'])), 2e-10)
                    self.assertLessEqual(original_metrics(asdict(p),x0,result['y'])['error_bound'], 1e-10)

    def test_linear_field_solves_identity_not_tanh(self):
        p = CoupledProfile()
        field = linear_field(p)
        trace = linear_trace(p,.45,field)
        n = len(trace['y']); full = trace['y']+trace['x'][n:]
        residual = [(1+p.lam*p.h)*full[i]-.5*(full[2*i+1]+full[2*i+2])-
                    p.beta*p.h*trace['x'][i] for i in range(n)]
        self.assertLess(max(map(abs,residual)), 1e-12)
        self.assertGreater(original_metrics(asdict(p),.45,trace['y'])['error_bound'], .1)
        corrected = solve_newton(p,.45,initial=trace['y'])
        self.assertLessEqual(corrected['report']['y_error_bound_exact_arithmetic'], 1e-10)

    def test_rehashed_field_mutation_rejected(self):
        p=CoupledProfile();f=linear_field(p);f['coefficients'][0]+=.01
        f['binding']=digest({k:f[k] for k in ('target','profile','coefficients')})
        with self.assertRaisesRegex(ValueError,'recurrence'):linear_trace(p,.2,f)

    def test_cross_profile_and_target_reuse_rejected(self):
        p=CoupledProfile();f=linear_field(p)
        with self.assertRaisesRegex(ValueError,'mismatch'):linear_trace(replace(p,lam=.3),.2,f)
        f['target']='nonlinear_tanh'
        with self.assertRaisesRegex(ValueError,'mismatch'):linear_trace(p,.2,f)

    def test_singular_or_unsupported_pivot_does_not_clip(self):
        p=CoupledProfile(lam=0.)
        with self.assertRaisesRegex(ValueError,'pivot unsupported'):
            newton_direction(p,.2,[0.]*(2**p.steps-1),pivot_floor=1.)

    def test_global_margin_not_changed_by_mesh(self):
        for steps in (2,5,10):
            with self.assertRaisesRegex(ValueError,'contraction'):
                solve_newton(CoupledProfile(a=.9,steps=steps),.2)

    def test_exhausted_iterations_do_not_return_candidate(self):
        with self.assertRaisesRegex(ValueError,'iteration budget'):
            solve_newton(CoupledProfile(),.45,max_updates=0)

    def test_bad_direction_cannot_bypass_original_merit(self):
        def ascend(p,x0,y,**kw):
            direction=newton_direction(p,x0,y,**kw)
            direction['dy']=[-v for v in direction['dy']]
            return direction
        with patch('fbsde_riccati.newton_direction',side_effect=ascend):
            with self.assertRaisesRegex(ValueError,'line search'):
                solve_newton(CoupledProfile(),.45,max_backtracks=0)

    def test_initial_solution_exits_without_newton(self):
        p=CoupledProfile(sigma=0.)
        r=solve_newton(p,0.,max_updates=0)
        self.assertEqual(r['newton_updates'],0)
        self.assertEqual(r['y'],[0.]*(2**p.steps-1))

    def test_inputs_and_budgets_fail_closed(self):
        p=CoupledProfile()
        for kwargs in ({'tolerance':float('nan')},{'max_updates':True},
                       {'max_backtracks':25},{'pivot_floor':0.},
                       {'initial':[float('nan')]*31},{'initial':[0.]},
                       {'initial':[True]*31}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):solve_newton(p,.2,**kwargs)
        with self.assertRaises(ValueError):solve_newton(p,2.)

    def test_error_history_decreases_on_original_map(self):
        r=solve_newton(CoupledProfile(),.45,initial=[.7]*31)
        self.assertTrue(all(b<a for a,b in zip(r['error_bound_history'],r['error_bound_history'][1:])))
        self.assertEqual(len(r['damping']),r['newton_updates'])
        self.assertEqual(len(r['pivot_history']),r['newton_updates'])

    def test_linear_coefficients_reused_for_distinct_initial_states(self):
        p=CoupledProfile();f=linear_field(p);before=copy.deepcopy(f)
        a,b=[linear_trace(p,x,f) for x in (-.5,.5)]
        self.assertEqual(f,before)
        self.assertNotEqual(a['y'],b['y'])
        self.assertAlmostEqual(a['y'][0],-b['y'][0])


if __name__=='__main__':main()
