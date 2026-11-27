"""Precision gate for the small-positive-h Lambert-W transition (research only)."""
import unittest

from .stopping import Stop, regenerative_boundary
from .test_stop_branchpoint import high_precision_boundary


class RenewalTransitionPrecisionTests(unittest.TestCase):
    def test_frozen_lambertw_near_branchpoint_cancellation_witness(self):
        # Deterministic failure on the original #4424 SHA: relative error 1.85e-13.
        p=Stop(.93340750611343,.0047551657491855005,
               .016955702658376082,0.,-.009317243124568796,0.)
        result=regenerative_boundary(p)
        oracle=high_precision_boundary(p)
        self.assertLess(abs(result-oracle)/oracle,5e-14)

    def test_series_to_lambert_transition_decimal_panel(self):
        # The repaired branch is exercised on both sides of h=1e-3.
        k=Stop(0.,1.,.1,0.,-1.,0.).kappa
        for h in (1.0001e-4,1.7e-4,3e-4,5e-4,9.9e-4,1e-3,1.001e-3,1.1e-3):
            p=Stop(0.,1.,.1,0.,-h/k,0.)
            with self.subTest(h=h):
                result=regenerative_boundary(p)
                oracle=high_precision_boundary(p)
                self.assertLess(abs(result-oracle)/oracle,5e-14)


if __name__=='__main__':
    unittest.main()
