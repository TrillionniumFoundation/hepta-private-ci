"""P2 positive occupation and monotone expected-count numerical gates.

Independent Decimal small-step integration; research-only two-state CTMC.
This is not an HCSN long-memory or production Rust/GPU test.
"""
from decimal import Decimal, localcontext
import math
import unittest

from scipy.integrate import quad

from .renewal_event_oracle import RenewalState, advance


class PositiveRenewalCountTests(unittest.TestCase):
    def test_small_refractory_steps_retain_second_order_count(self):
        # The old O(dt)-O(dt) occupation cancels at dt=1e-17,1e-20,
        # though the true expected count is approximately dt^2/2.
        for dt in (1e-7,1e-10,1e-12,1e-14,1e-16,1e-17,1e-20):
            with self.subTest(dt=dt):
                actual=advance(RenewalState.initial(0.),1.,1.,dt)
                with localcontext() as ctx:
                    ctx.prec=120
                    t=Decimal.from_float(dt)
                    # lambda=gamma=1, start refractory:
                    # E[N] = 1/2 * (t - (1-exp(-2t))/2).
                    reference=(t-(1-(-2*t).exp())/2)/2
                target=float(reference)
                self.assertGreater(actual.expected_count,0.)
                self.assertAlmostEqual(actual.expected_count/target,1.,
                                       delta=3e-13)
                self.assertGreater(actual.ever_fired,0.)

    def test_original_cancellation_witness_is_real_and_distinct(self):
        for dt in (1e-17,1e-20):
            with self.subTest(dt=dt):
                original=math.fsum((.5*dt,(-.5)*(-math.expm1(-2*dt))/2))
                self.assertEqual(original,0.)
                actual=advance(RenewalState.initial(0.),1.,1.,dt)
                self.assertGreater(actual.expected_count,0.)

    def test_reachable_large_count_cannot_swallow_new_event_flow(self):
        checkpoint=advance(RenewalState.initial(1.),1.,1.,1e16)
        self.assertEqual(checkpoint.time,1e16)
        self.assertEqual(checkpoint.expected_count,5e15)
        self.assertEqual(math.ulp(checkpoint.expected_count),1.)
        self.assertGreater(math.fsum((checkpoint.time,2.)),checkpoint.time)
        # The positive .001 count increment is erased by rounding at 5e15.
        self.assertEqual(math.fsum((checkpoint.expected_count,.001)),
                         checkpoint.expected_count)
        with self.assertRaisesRegex(ArithmeticError, 'count erased'):
            advance(checkpoint,.001,.001,2.)
        # A resolvable larger increment is still admissible.
        admitted=advance(checkpoint,.001,.001,4096.)
        self.assertGreater(admitted.time,checkpoint.time)
        self.assertGreater(admitted.expected_count,checkpoint.expected_count)

    def test_unrepresentable_positive_event_flow_is_not_reported_as_zero(self):
        with self.assertRaisesRegex(ArithmeticError, 'increment unresolved'):
            advance(RenewalState.initial(0.),1.,1.,math.ulp(0.))

    def test_ordinary_positive_count_matches_independent_quadrature(self):
        for lam,gamma,active,dt in ((1.,2.,0.,.03),
                                     (3.,.7,.4,.2),
                                     (10.,4.,1.,.5),
                                     (.03,.09,.63,1.)):
            with self.subTest(lam=lam,gamma=gamma,active=active,dt=dt):
                s=lam+gamma
                eq=gamma/s
                reference=quad(lambda t: lam*(eq+(active-eq)*math.exp(-s*t)),
                               0.,dt,epsabs=1e-13,epsrel=1e-13)[0]
                actual=advance(RenewalState.initial(active),lam,gamma,dt)
                self.assertAlmostEqual(actual.expected_count,reference,
                                       delta=2e-12*(1+reference))


if __name__=='__main__':
    unittest.main()
