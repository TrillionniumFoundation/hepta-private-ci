"""Adversarial normalized-gap checks; not full FP interval certification."""
import unittest
import mpmath as mp
from experiments.hcsn_hx_unified_v3.piecewise_boundary_oracle import two_segment_first_hit


class NarrowRemoteModeTests(unittest.TestCase):
    # The continuous final position is X(1)=5+sigma*W(1), and the
    # continuous piecewise lower boundary equals b(1)=5. Therefore
    # P(first hit by 1) >= P(X(1)<=b(1)) = 1/2, exactly for all sigma>0.
    def test_terminal_event_lower_bound_and_small_noise_limit(self):
        p = two_segment_first_hit(1, 0, 4, '1e-24', 0, 10, '.5', 1, 0, dps=50)
        self.assertGreaterEqual(p.probability, mp.mpf('.5'))
        self.assertLess(p.probability-mp.mpf('.5'), mp.mpf('1e-18'))
        self.assertEqual(p.discounted, p.probability)

    def test_narrow_mode_precision_and_discounted_weight(self):
        args = (1, 0, 4, '1e-30', 0, 10, '.5', 1, '.2')
        a = two_segment_first_hit(*args, dps=50)
        b = two_segment_first_hit(*args, dps=70)
        self.assertGreaterEqual(a.probability, mp.mpf('.5'))
        self.assertLess(abs(a.probability-b.probability), mp.mpf('1e-32'))
        self.assertLess(abs(a.discounted-b.discounted), mp.mpf('1e-32'))
        self.assertLess(a.discounted, a.probability)

    def test_unresolved_scale_must_reject_or_respect_terminal_bound(self):
        try:
            p = two_segment_first_hit(1, 0, 4, '1e-40', 0, 10, '.5', 1, 0, dps=50)
        except ArithmeticError:
            return  # Fail closed is not counted as a successful probability.
        self.assertGreaterEqual(p.probability, mp.mpf('.5'))


if __name__ == '__main__':
    unittest.main()
