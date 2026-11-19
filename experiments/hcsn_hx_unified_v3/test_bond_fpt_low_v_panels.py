"""Adversarial long-horizon first-passage tests with independent 120-dps witnesses.

Values were evaluated offline from the inverse-Gaussian Brownian hitting-time
normal-CDF formulas using mpmath at 120 decimal digits. These literals are
NOT results returned by the quadrature implementation under test.
The finite tests are numerical diagnostics, not validated real-number bounds.
"""
import math
import unittest

from .bond_fpt_independent import integrate_passage


class LowVPassagePanels(unittest.TestCase):
    def test_long_horizon_low_v_transition_against_120_dps_reference(self):
        # Before geometric segmentation QUADPACK missed a narrow low-v layer,
        # reporting integration error ~1e-12 while F was wrong by 2e-11 to
        # 7e-10. Include both drift signs and very different state scales.
        fixtures = (
            ((.16408143422304328, -3.1881785483898284e-05,
              4.775559250144955, 452.1760706127229, 4269.082411302018),
             .99958065581305106517152714501498804233,
             .35584985732735959767495105181714311151),
            ((2.54166517683568e-05, .002416265359773832,
              2.84299950520866, 6449.149573665547, 80717.10997611906),
             .99999996656619729328274615597123344478,
             .99898517637766179009867328797748642309),
            ((4.647631055394124e-08, -5.4962375836745406e-05,
              .03748643850194153, 3511.642597476255, 76306.47353468504),
             .99999999794694001052717296750264597690,
             .99989610432804660004203109817948100201),
            ((.0036269731668275174, -4.955073084959888e-06,
              .3483745017674351, 38.79282364372593, 77461.16082502685),
             .99997030116261268931650815674837617833,
             .91237523135974390967541813465798883641),
        )
        for (x, drift, sigma, discount, horizon), f_ref, g_ref in fixtures:
            with self.subTest(x=x, drift=drift, sigma=sigma,
                              discount=discount, horizon=horizon):
                passage = integrate_passage(x, drift=drift, sigma=sigma,
                              discount=discount, horizon=horizon)
                self.assertTrue(math.isfinite(passage.absolute_error_bound))
                self.assertGreaterEqual(passage.absolute_error_bound, 0)
                self.assertGreaterEqual(passage.probability, passage.discounted)
                self.assertLessEqual(passage.probability, 1)
                self.assertLess(abs(passage.probability-f_ref), 1e-12)
                self.assertLess(abs(passage.discounted-g_ref), 1e-12)


if __name__ == '__main__':
    unittest.main()
