"""Independent large-translation Brent residual gate; P0 research only."""

import math
import unittest
import mpmath as mp

from .stopping import Stop, regenerative_boundary_independent


def high_precision_displacement(p):
    """100-dps independent transformed Lambert-W displacement (not Brent)."""
    with mp.workdps(100):
        k = mp.mpf(repr(p.kappa))
        h = k*mp.mpf(repr(p.cost-p.reset)) + mp.mpf(repr(p.discount))*mp.mpf(repr(p.refractory))
        t = 1 + mp.lambertw(-mp.exp(-h-1), 0)
        return float(t/k)


class LargeCostRootTests(unittest.TestCase):
    def test_false_early_brent_convergence_at_cost_1e8(self):
        p=Stop(0.,1.,.005,1e8,1e8-10.,0.)
        got=regenerative_boundary_independent(p)
        want=high_precision_displacement(p)
        self.assertLessEqual(abs((got-p.cost)-want),2*math.ulp(got))

    def test_high_absolute_cost_unresolved_reward_is_explicitly_refused(self):
        p=Stop(0.,1.,.005,1e14,1e14-10.,0.)
        with self.assertRaisesRegex(ArithmeticError, 'resolution'):
            regenerative_boundary_independent(p)

    def test_small_loss_decimal_root_rejects_coarse_large_cost(self):
        # Small h uses Decimal's equation but the final float boundary still
        # cannot encode the t/k displacement at useful relative resolution.
        p=Stop(0.,1.,.005,1e10,1e10-1e-5,0.)
        with self.assertRaisesRegex(ArithmeticError, 'resolution'):
            regenerative_boundary_independent(p)

    def test_translation_invariance_at_resolved_cost_scales(self):
        for K in (0.,1e4,1e6,1e8):
            p=Stop(0.,1.,.005,K,K-32.,0.)
            with self.subTest(K=K):
                got=regenerative_boundary_independent(p)
                want=high_precision_displacement(p)
                self.assertLessEqual(abs((got-K)-want),3*math.ulp(got))

    def test_nominal_finite_renewal_not_weakened(self):
        p=Stop(.1,.4,.1,1.,0.,.3)
        b=regenerative_boundary_independent(p)
        self.assertTrue(math.isfinite(b) and b>p.cost)

if __name__=='__main__':
    unittest.main()
