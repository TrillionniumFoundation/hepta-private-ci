"""320-digit independent scalar-renewal transition regression; research only.

No claim of full-domain bounded Jacobians or mathematically certified
binary64 interval bounds. Preserve the h->0 reset-gradient singularity.
"""
import math
import random
import unittest

from .stopping import Stop, regenerative_boundary
from .test_stop_branchpoint import high_precision_boundary


class WideTransitionPrecisionTests(unittest.TestCase):
    def test_frozen_4444_transition_witness(self):
        # Original #4444: ~1.1072e-13 relative error, not a false skip.
        p = Stop(0., 1., .5, 0., -0.0011940784715932823, 0.)
        got = regenerative_boundary(p)
        reference = high_precision_boundary(p)
        self.assertLess(abs(got - reference) / reference, 5e-14)

    def test_seeded_wide_transition_and_switch_panel(self):
        rng = random.Random(20261031 + 12)
        hs = [10**rng.uniform(-3.3, -0.5) for _ in range(128)]
        hs.extend([0.000999999999999, 0.001000000000001,
                   0.09999999999999, 0.1, 0.10000000000001])
        for h in hs:
            # kappa=1 exactly; all expected values use 320-digit Decimal
            # and the original binary64 input parameters.
            p = Stop(0., 1., .5, 0., -h, 0.)
            got = regenerative_boundary(p)
            reference = high_precision_boundary(p)
            with self.subTest(h=h):
                self.assertTrue(math.isfinite(got))
                self.assertLess(abs(got - reference) / reference, 2e-14)

    def test_seeded_drift_and_diffusion_sensitivity_panel(self):
        rng = random.Random(20261031 + 13)
        for i in range(96):
            drift = rng.uniform(-2, 2)
            diffusion = 10**rng.uniform(-2, 1)
            discount = 10**rng.uniform(-2, 1)
            k = Stop(drift, diffusion, discount, 0., -1., 0.).kappa
            h = 10**rng.uniform(-3.3, -0.99)
            p = Stop(drift, diffusion, discount, 0., -h/k, 0.)
            got = regenerative_boundary(p)
            reference = high_precision_boundary(p)
            with self.subTest(i=i, h=h):
                self.assertLess(abs(got - reference) / reference, 2e-14)


if __name__ == '__main__':
    unittest.main()
