"""P0: independently bound an unresolved sharp second-leg first-hit transition.

All tests use real source code and a separate one-leg Brownian reflection / time-
density reference. A tiny remaining observation interval with compensating
large slope creates an O(sqrt(remaining)) transition INSIDE a broad Gaussian.
The ordinary fixed z panels of #4485 can silently misintegrate it.
Research-only; this does not certify a general interval error bound.
"""
import unittest

import mpmath as mp

from experiments.hcsn_hx_unified_v3.piecewise_boundary_oracle import two_segment_first_hit


class NarrowSecondLegTransitionTests(unittest.TestCase):
    @staticmethod
    def _independent_limit(z, q):
        """First hit before switch + absorbed endpoint below deterministic cut.

        For nu1=0 and s=1, the absorbed endpoint density is the free normal
        started at a minus its reflected image started at -a. No project
        first-passage or convolution function is used to get this reference.
        """
        a, sigma, switch = mp.mpf(1), mp.mpf("0.5"), mp.mpf(1)
        remaining = mp.mpf("1e-40")
        T = switch + remaining
        scale = sigma * mp.sqrt(switch)
        cut = a + scale * z
        phi = lambda u: mp.erfc(-u / mp.sqrt(2)) / 2
        first_f = 2 * phi(-a / scale)
        killed_cdf = (phi((cut-a)/scale) - phi(-a/scale)
                      - phi((cut+a)/scale) + phi(a/scale))
        # The first-leg discounted hit is independently obtained from its
        # *time* density, not from the production research oracle.
        if q:
            density = lambda t: (a / (sigma * mp.sqrt(2*mp.pi*t**3))
                     * mp.exp(-a*a/(2*sigma*sigma*t)-q*t))
            first_g = mp.quad(density, [0, mp.mpf(".125"),
                                        mp.mpf(".5"), switch])
        else:
            first_g = first_f
        # Bound the second-leg indicator/step mismatch by the event
        # sup|sigma*W(t)| > 16 sigma sqrt(remaining) (reflection union bound)
        # or a surviving gap within +/- that width of the deterministic cut.
        # Since killed density <= free normal peak, this is an analytic bound.
        K = mp.mpf(16)
        physical_bound = (2*K*mp.sqrt(remaining/switch)/mp.sqrt(2*mp.pi)
                          + 2*mp.erfc(K/mp.sqrt(2)))
        return (first_f+killed_cdf,
                first_g + mp.exp(-q*T)*killed_cdf,
                physical_bound + q*remaining,
                T, cut/remaining)

    def _check(self, q):
        with mp.workdps(110):
            q = mp.mpf(q)
            for raw_z in ("0.7", "1.7", "2.35"):
                with self.subTest(q=str(q), z=raw_z):
                    z = mp.mpf(raw_z)
                    expected_f, expected_g, bound, T, c2 = self._independent_limit(z, q)
                    got = two_segment_first_hit(
                        "1", "0", "0", "0.5", "0",
                        mp.nstr(c2, 110), "1", mp.nstr(T, 110),
                        mp.nstr(q, 30), dps=50
                    )
                    self.assertLess(abs(got.probability-expected_f), bound)
                    self.assertLess(abs(got.discounted-expected_g), bound)
                    self.assertGreater(got.probability, 0)
                    self.assertLess(got.probability, 1)
                    self.assertLessEqual(got.discounted, got.probability)

    def test_sharp_second_leg_zero_discount(self):
        self._check(mp.mpf(0))

    def test_sharp_second_leg_positive_discount(self):
        self._check("0.2")

    def test_normal_two_slope_case_unaffected(self):
        got = two_segment_first_hit(1,0,0,".4",".8",0,".5",1,".2",dps=75)
        with mp.workdps(100):
            self.assertLess(abs(got.probability-mp.mpf("0.13034319097200746")),
                            mp.mpf("1e-16"))
            self.assertLess(abs(got.discounted-mp.mpf("0.11371219839348145")),
                            mp.mpf("1e-16"))

    def test_invalid_second_segment_rejected(self):
        with self.assertRaises(ValueError):
            two_segment_first_hit(1,0,0,.5,0,"inf",1,2,0)


if __name__ == "__main__":
    unittest.main()
