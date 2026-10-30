"""Independent FPT and integrated HX bond tests. No production permissions."""
import math
import unittest

from .bond_fpt_independent import (independent_bond, integrate_passage,
                                   reflected_passage, reference_sweep)


class IndependentPassageTests(unittest.TestCase):
    def test_independent_density_versus_reflection_108_cases(self):
        report=reference_sweep()
        self.assertEqual(report['count'],108)
        self.assertLess(report['max_F_difference'],2e-10)
        self.assertLess(report['max_G_difference'],2e-10)

    def test_distant_first_passage_mode_cannot_disappear(self):
        # Prior unpartitioned quad([u0, infinity)) returned F ~ 1.3e-15
        # here, although the independently evaluated reflection gives F=1.
        # The density has its narrow u-mode at ~sqrt(-a) >> u0.
        kwargs=dict(x=3.69821872103264, drift=-.7997788483837058,
                    sigma=.07189992168352377, discount=4.966000807445653e-5,
                    horizon=85.44911244689267)
        actual=integrate_passage(**kwargs)
        reference=reflected_passage(**kwargs)
        self.assertGreater(actual.probability,.999)
        self.assertLess(abs(actual.probability-reference.probability),3e-11)
        self.assertLess(abs(actual.discounted-reference.discounted),3e-11)

    def test_distant_density_modes_72_cases(self):
        # Independent integral must resolve the f64 peak, including the
        # discount-shifted location when G has a different mode from F.
        from itertools import product
        count=0
        for x,drift,sigma,horizon,q in product(
                (2.5,4.,8.),(-.2,-.8),(.05,.1),(20.,120.),(.001,.5,5.)):
            params=dict(x=x,drift=drift,sigma=sigma,
                        horizon=horizon,discount=q)
            a=integrate_passage(**params)
            b=reflected_passage(**params)
            self.assertLess(abs(a.probability-b.probability),3e-11,params)
            self.assertLess(abs(a.discounted-b.discounted),3e-11,params)
            count+=1
        self.assertEqual(count,72)

    def test_seeded_broad_parameter_stress_2000_cases(self):
        # Deterministic adversarial CPU suite, not interval/full-domain proof.
        import random
        rng=random.Random(20261030)
        maximum=0.
        for _ in range(2000):
            params=dict(x=10**rng.uniform(-10,1.6),
                        sigma=10**rng.uniform(-2,.5),
                        drift=rng.uniform(-1.,1.),
                        discount=10**rng.uniform(-9,1.5),
                        horizon=10**rng.uniform(-5,2.5))
            a=integrate_passage(**params)
            b=reflected_passage(**params)
            maximum=max(maximum,abs(a.probability-b.probability),
                        abs(a.discounted-b.discounted))
        self.assertLess(maximum,5e-11)

    def test_hitting_probability_domains(self):
        for x in (.0001,.06,.2,1.,4.):
            for drift in (-.2,0.,.02,.2):
                fp=integrate_passage(x,drift=drift,sigma=.3,
                                     discount=.08,horizon=2.)
                self.assertGreaterEqual(fp.probability,0.)
                self.assertLessEqual(fp.probability,1.)
                self.assertGreaterEqual(fp.discounted,0.)
                self.assertLessEqual(fp.discounted,fp.probability+1e-12)

    def test_near_boundary_layer_is_resolved(self):
        # A naive unpartitioned quad() from u0 to infinity misses O(x/sigma)
        # when x~1e-7 and falsely reports G~=F with tiny error estimates.
        for x in (1e-9,1e-7,1e-5,1e-3):
            for t in (.01,1.,10.):
                a=integrate_passage(x,drift=-.03,sigma=.25,discount=.05,horizon=t)
                b=reflected_passage(x,drift=-.03,sigma=.25,discount=.05,horizon=t)
                self.assertLess(abs(a.probability-b.probability),3e-11)
                self.assertLess(abs(a.discounted-b.discounted),3e-11)

    def test_discounted_default_strictly_decreases_in_q(self):
        values=[integrate_passage(.6,drift=-.02,sigma=.3,
                                  discount=q,horizon=2.).discounted
                for q in (.005,.05,.5,2.)]
        self.assertTrue(all(a>b for a,b in zip(values,values[1:])))

    def test_bond_decomposition_and_invalid_values(self):
        kwargs=dict(x=.7,drift=.01,sigma=.22,discount=.09,
                    horizon=3.,coupon_per_bond=2.,principal_per_bond=30.,
                    recovery_per_bond=11.)
        value, fp=independent_bond(**kwargs)
        self.assertGreater(value,0.)
        self.assertLess(value,32.)
        with self.assertRaises(ValueError):
            independent_bond(**(kwargs | {'recovery_per_bond':-1.}))
        for key,bad in [('x',0.),('sigma',0.),('discount',0.),
                        ('horizon',0.),('x',float('nan'))]:
            with self.assertRaises(ValueError):
                independent_bond(**(kwargs | {key:bad}))

    def test_quantized_boundary_discontinuity_is_not_certified(self):
        # Float32 cannot represent arbitrarily close positive-side states.
        import numpy as np
        b=64.6251766753
        asset=b*(1+1e-9)
        self.assertGreater(asset,b)
        self.assertEqual(np.float32(asset),np.float32(b))
        # This is a negative precision witness, not a float32 PASS.

    def test_exact_upstream_hx_f_g_and_bond_when_present(self):
        try:
            from .hx import HX, boundary, bond_value, default_probability, discounted_default_factor
        except ModuleNotFoundError as exc:
            # Only a genuinely absent optional HX module may skip. Missing
            # symbols or dependencies in a present HX module must fail.
            if exc.name != f'{__package__}.hx':
                raise
            self.skipTest('Exact upstream hx.py not mounted in local reference copy')
        for p in (HX(), HX(sale_fraction=.2), HX(payout=0),
                  HX(sale_fraction=0), HX(maturity=.5,volatility=.36)):
            b=boundary(p)
            for ratio in (1.02,1.2,2.5):
                asset=b*ratio
                for tau in (p.maturity*.15,p.maturity):
                    x=math.log(ratio)
                    d,fp=independent_bond(x=x,drift=p.rate-p.payout-.5*p.volatility**2,
                        sigma=p.volatility,discount=p.q,horizon=tau,
                        coupon_per_bond=p.per_bond_coupon,
                        principal_per_bond=p.per_bond_principal,
                        recovery_per_bond=p.recovery*b/p.maturity)
                    self.assertAlmostEqual(fp.probability,
                        default_probability(p,asset,tau,b),delta=3e-9)
                    self.assertAlmostEqual(fp.discounted,
                        discounted_default_factor(p,asset,tau,b),delta=3e-9)
                    self.assertAlmostEqual(d,bond_value(p,asset,tau,b),delta=3e-8)


class UpstreamImportGuardTests(unittest.TestCase):
    """Import failure classification only; no numerical oracle is evaluated."""

    def _invoke_with_import_failure(self, failure):
        import builtins
        from unittest.mock import patch

        original_import = builtins.__import__
        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if (name == 'hx' and level == 1 and globals is not None
                    and globals.get('__package__') == __package__):
                raise failure
            return original_import(name, globals, locals, fromlist, level)

        case = IndependentPassageTests(
            'test_exact_upstream_hx_f_g_and_bond_when_present')
        with patch('builtins.__import__', side_effect=guarded_import):
            case.test_exact_upstream_hx_f_g_and_bond_when_present()

    def test_absent_exact_upstream_module_is_optional(self):
        failure = ModuleNotFoundError('No upstream fixture', name=f'{__package__}.hx')
        with self.assertRaises(unittest.SkipTest) as caught:
            self._invoke_with_import_failure(failure)
        self.assertEqual(caught.exception.args,
                         ('Exact upstream hx.py not mounted in local reference copy',))

    def test_missing_transitive_or_other_module_is_not_optional(self):
        for name in ('scipy.special', 'other.hx', f'{__package__}.hx_dependency', None):
            with self.subTest(name=name):
                failure = ModuleNotFoundError('Dependency unavailable', name=name)
                with self.assertRaises(ModuleNotFoundError) as caught:
                    self._invoke_with_import_failure(failure)
                self.assertIs(caught.exception, failure)

    def test_missing_upstream_symbol_is_not_optional(self):
        failure = ImportError("cannot import name 'bond_value'", name=f'{__package__}.hx')
        with self.assertRaises(ImportError) as caught:
            self._invoke_with_import_failure(failure)
        self.assertIs(caught.exception, failure)

    def test_unrelated_import_error_is_not_optional(self):
        failure = ImportError('Upstream initialization failed')
        with self.assertRaises(ImportError) as caught:
            self._invoke_with_import_failure(failure)
        self.assertIs(caught.exception, failure)


if __name__=='__main__':
    unittest.main()
