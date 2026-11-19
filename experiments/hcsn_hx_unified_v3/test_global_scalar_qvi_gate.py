"""Source-exact isolated regression checks for global scalar QVI sign theorem."""

import math
import random
import unittest
from decimal import Decimal, localcontext

from .global_scalar_qvi_gate import ScalarCase, audit_scalar_global_qvi


class GlobalScalarQviTests(unittest.TestCase):
    def test_canonical_and_observed_identity(self):
        case = ScalarCase(0, 1, .5, 0, -1, 0)
        witness = audit_scalar_global_qvi(case)
        verified = audit_scalar_global_qvi(case, observed_boundary=witness.boundary)
        self.assertTrue(verified.observed_boundary_checked)
        self.assertAlmostEqual(witness.kappa, 1)
        self.assertAlmostEqual(witness.boundary, 0.8414056604369606, places=14)
        self.assertAlmostEqual(witness.t + witness.renewal_ratio, 1, places=14)
        self.assertAlmostEqual(witness.generator_upper_bound, -0.5)
        self.assertEqual(witness.scope, 'ANALYTIC_IDEAL_SCALAR_ONLY_NOT_PRODUCTION')

    def test_exact_global_obstacle_is_exponential_tangent_inequality(self):
        case = ScalarCase(-.8, 1, .2, 1, 0, .1)
        result = audit_scalar_global_qvi(case)
        with localcontext() as c:
            c.prec = 100
            k = Decimal.from_float(result.kappa)
            for u in ('1e-40', '1e-25', '1e-12', '1e-6', '.03', '.7', '1', '12', '100'):
                z = Decimal(u)
                gap = ((-z).exp() - 1 + z) / k
                self.assertGreater(gap, 0, msg=u)

    def test_firing_region_generator_is_globally_negative(self):
        for case in (ScalarCase(0, 1, .5, 0, -1, 0),
                     ScalarCase(.5, .7, .3, 1, .2, .25),
                     ScalarCase(-.8, 1, .2, 1, 0, .1)):
            w = audit_scalar_global_qvi(case)
            self.assertLess(w.generator_upper_bound, 0)
            for dx in (0, .001, 1, 100):
                x = w.boundary + dx
                value = (x-case.cost) + w.renewal_ratio/w.kappa
                generator = case.drift - case.discount*value
                self.assertLessEqual(generator, 1e-12)

    def test_numerical_residual_of_independent_log_root(self):
        for case in (ScalarCase(0, 1, .5, 0, -1e-20, 0),
                     ScalarCase(.5, .7, .3, 1, .2, .25),
                     ScalarCase(-.8, 1, .2, 1, 0, .1)):
            w = audit_scalar_global_qvi(case)
            with localcontext() as c:
                c.prec = 90
                d = Decimal.from_float
                k = d(w.kappa)
                h = d(case.discount)*d(case.refractory)+k*(d(case.cost)-d(case.reset))
                t = d(w.t)
                # Different numerical equation from the implementation's
                # exponential smooth-fit residual.
                ln_residual = -(1-t).ln() - t - h
                self.assertLess(abs(ln_residual), h*Decimal('2e-12'))

    def test_tiny_branchpoint_and_refractory(self):
        for gap in (1e-6, 1e-12, 1e-20, 1e-30):
            p = ScalarCase(0, 1, .5, 0, -gap, 0)
            w = audit_scalar_global_qvi(p)
            self.assertGreater(w.boundary, 0)
            self.assertAlmostEqual(w.boundary / math.sqrt(2*gap), 1, delta=1e-3)
        # True scalar solution still exists, but q rounds to one in f64.
        for gap in (1e-40, 1e-50):
            with self.assertRaisesRegex(ArithmeticError, "collapsed in f64"):
                audit_scalar_global_qvi(ScalarCase(0, 1, .5, 0, -gap, 0))
        w = audit_scalar_global_qvi(ScalarCase(0, 1, .5, 0, -1e-20, .25))
        self.assertGreater(w.boundary, .1)

    def test_reject_changed_observed_boundary(self):
        p = ScalarCase(0, 1, .5, 0, -1, 0)
        base = audit_scalar_global_qvi(p).boundary
        with self.assertRaisesRegex(ArithmeticError, 'Observed threshold disagrees'):
            audit_scalar_global_qvi(p, observed_boundary=base + 1e-5)
        with self.assertRaisesRegex(ArithmeticError, 'Observed threshold not finite'):
            audit_scalar_global_qvi(p, observed_boundary=float('inf'))

    def test_reject_erased_float_boundary(self):
        p = ScalarCase(0, 1, .5, 1e16, 1e16-2, 0)
        with self.assertRaises(ArithmeticError):
            audit_scalar_global_qvi(p)

    def test_reject_nondomain_or_unresolved_loss(self):
        bad = (ScalarCase(0, 0, .5, 0, -1, 0),
               ScalarCase(0, 1, 0, 0, -1, 0),
               ScalarCase(0, 1, .5, 0, 0, 0),
               ScalarCase(0, 1, .5, 0, -1, -1),
               ScalarCase(float('nan'), 1, .5, 0, -1, 0))
        for p in bad:
            with self.subTest(p=p), self.assertRaises(ValueError):
                audit_scalar_global_qvi(p)
        with self.assertRaisesRegex(ArithmeticError, 'outside audited'):
            audit_scalar_global_qvi(ScalarCase(0, 1, .5, 0, -100, 0))

    def test_sweep_no_fabricated_full_parameter_domain(self):
        rng = random.Random(20261031)
        accepted, refused = 0, 0
        for _ in range(100):
            mu = rng.uniform(-1, 1)
            sigma = rng.uniform(.3, 2)
            rho = rng.uniform(.1, 1.5)
            cost = rng.uniform(-1, 1)
            reset = cost - rng.uniform(.01, 3)
            duration = rng.uniform(0, 2)
            p = ScalarCase(mu, sigma, rho, cost, reset, duration)
            try:
                w = audit_scalar_global_qvi(p)
            except ArithmeticError:
                refused += 1
                continue
            accepted += 1
            self.assertTrue(0 < w.t < 1 and 0 < w.renewal_ratio < 1)
            self.assertAlmostEqual(w.t+w.renewal_ratio, 1, delta=2e-14)
            self.assertGreater(w.boundary, p.cost)
            self.assertLess(w.generator_upper_bound, 0)
            audit_scalar_global_qvi(p, observed_boundary=w.boundary)
        self.assertGreater(accepted, 60)
        self.assertEqual(accepted + refused, 100)


if __name__ == '__main__':
    unittest.main()
