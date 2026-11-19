"""Research tests: a changing slope is not an averaged/frozen slope."""
import unittest
import mpmath as mp
from experiments.hcsn_hx_unified_v3.moving_boundary_enclosure import linear_boundary_first_hit
from experiments.hcsn_hx_unified_v3.piecewise_boundary_oracle import two_segment_first_hit as two


class PiecewiseFirstHitTests(unittest.TestCase):
    def assert_close(self, got, want, tol="1e-37"):
        self.assertLess(abs(got - want), mp.mpf(tol))

    def test_degenerate_switches(self):
        for c1, c2, at, selected in [(-.1,.7,0,.7),(-.1,.7,1.5,-.1),(.3,.3,.7,.3)]:
            actual = two(.8,0,.2,.5,c1,c2,at,1.5,.1)
            expected = linear_boundary_first_hit(.8,0,.2,.5,selected,1.5,.1)
            for field in ('probability','discounted'):
                self.assert_close(getattr(actual, field), getattr(expected, field), '1e-60')

    def test_two_segment_vs_high_precision_density_convolution(self):
        # Independent *time* first-hit density integration for constant slope
        # is already tested in test_moving_boundary_enclosure.py. Here the
        # test numerically integrates an *endpoint* killed transition.
        z = two(1,0,0,.6,-.2,.7,.6,1.3,.3)
        slow = linear_boundary_first_hit(1,0,0,.6,-.2,1.3,.3)
        fast = linear_boundary_first_hit(1,0,0,.6,.7,1.3,.3)
        self.assertGreater(z.probability, slow.probability)
        self.assertLess(z.probability, fast.probability)
        self.assertGreater(z.discounted, slow.discounted)
        self.assertLess(z.discounted, fast.discounted)
        self.assertLess(z.discounted, z.probability)

    def test_absorbing_density_mass_matches_independent_reflection(self):
        # Exponential tilt of driftless killed Gaussian, integrated in *space*;
        # a free Gaussian would count paths that hit zero and then returned.
        with mp.workdps(60):
            a, nu, sigma, t = map(mp.mpf, ('.8','-.2','.5','.6'))
            var = sigma*sigma*t
            def killed(y):
                if y <= 0: return mp.mpf(0)
                return (mp.exp(nu*(y-a)/sigma**2-nu**2*t/(2*sigma**2)
                               -(y-a)**2/(2*var)) / mp.sqrt(2*mp.pi*var)
                        * (-mp.expm1(-2*a*y/var)))
            mass = mp.quad(killed,[0,a/4,a/2,a,2*a,mp.inf])
            expected = 1-linear_boundary_first_hit(a,0,nu,sigma,0,t,0,dps=60).probability
            self.assert_close(mass,expected,'1e-50')

    def test_reference_precision_stability(self):
        args = (1,0,0,.6,-.2,.7,.6,1.3,.3)
        a = two(*args, dps=50)
        b = two(*args, dps=80)
        for field in ('probability','discounted'):
            self.assert_close(getattr(a,field),getattr(b,field),'1e-43')

    def test_reverse_slope_and_q_zero(self):
        p = two(.8,0,-.2,.5,.8,-.4,.5,1.1,0)
        self.assert_close(p.probability, p.discounted)
        bounds = [linear_boundary_first_hit(.8,0,-.2,.5,c,1.1,0)
                  for c in (-.4,.8)]
        self.assertLess(bounds[0].probability, p.probability)
        self.assertLess(p.probability, bounds[1].probability)

    def test_not_endpoint_averaging(self):
        p = two(1,0,0,.4,.8,0,.5,1,.2)
        averaged = linear_boundary_first_hit(1,0,0,.4,.4,1,.2)
        self.assertGreater(abs(p.probability - averaged.probability),mp.mpf('1e-4'))

    def test_immediate_and_zero_time(self):
        self.assertEqual(two(0,0,0,.4,.5,.2,0,0,.3), (1,1))
        self.assertEqual(two(1,0,0,.4,.5,.2,0,0,.3), (0,0))

    def test_invalid_fail_closed(self):
        for args in [ (1,0,0,0,.1,.2,.5,1,0),
                      (1,0,0,.3,.1,.2,-.1,1,0),
                      (1,0,0,.3,.1,.2,1.1,1,0),
                      (1,0,0,.3,.1,.2,.5,1,-.1),
                      (1,0,0,.3,.1,mp.inf,.5,1,0) ]:
            with self.assertRaises(ValueError): two(*args)
        with self.assertRaises(ValueError): two(1,0,0,.3,.1,.2,.5,1,dps=10)


if __name__ == '__main__': unittest.main()
