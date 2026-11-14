import unittest
from unittest.mock import patch
from .hx import HX, equity_closed, equity_resolvent
from .hx_admissibility_diagnostic import diagnose_local_admissibility

class LocalAdmissibilityTests(unittest.TestCase):
    def test_original_witness_rejected_locally_not_clamped(self):
        p=HX(sale_fraction=.2);d=diagnose_local_admissibility(p)
        self.assertEqual(d.local_status,'POSITIVE_CASHFLOW_NEGATIVE_CURVATURE')
        self.assertGreater(d.boundary_cashflow,.43)
        self.assertLess(d.equity_asset_curvature,0)
        self.assertAlmostEqual(d.equity_log_curvature,-13.98174211186474,places=10)
        self.assertLess(equity_closed(p,1.01*d.asset_boundary),-.00048)
        self.assertAlmostEqual(equity_closed(p,1.01*d.asset_boundary),
                               equity_resolvent(p,1.01*d.asset_boundary),places=10)
        self.assertEqual(d.global_status,'NOT_CERTIFIED')
        self.assertFalse(d.numerical_certificate)

    def test_recovery_below_par_is_not_sufficient(self):
        p=HX(payout=.08,maturity=3.5,coupon=4,recovery=.7,sale_fraction=.28)
        d=diagnose_local_admissibility(p)
        self.assertLess(d.recovery_to_principal,1)
        self.assertEqual(d.local_status,'POSITIVE_CASHFLOW_NEGATIVE_CURVATURE')
        self.assertLess(equity_resolvent(p,1.001*d.asset_boundary),-7e-6)

    def test_default_is_not_global_pass(self):
        d=diagnose_local_admissibility(HX())
        self.assertEqual(d.local_status,'NO_LOCAL_REJECTION')
        self.assertEqual(d.global_status,'NOT_CERTIFIED')
        self.assertFalse(d.numerical_certificate)

    def test_transition_roundoff_is_unresolved(self):
        d=diagnose_local_admissibility(HX(sale_fraction=.19245741532456426))
        self.assertEqual(d.local_status,'ROUNDING_UNRESOLVED')
        self.assertEqual(d.global_status,'NOT_CERTIFIED')

    def test_unsupported_cashflow_does_not_certify(self):
        with patch('experiments.hcsn_hx_unified_v3.hx_admissibility_diagnostic.boundary',return_value=float('inf')):
            with self.assertRaises(ArithmeticError):
                diagnose_local_admissibility(HX())

if __name__=='__main__': unittest.main()
