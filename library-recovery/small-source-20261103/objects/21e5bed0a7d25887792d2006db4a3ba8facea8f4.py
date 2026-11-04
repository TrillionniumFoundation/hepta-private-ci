"""Standalone targeted research tests for a fail-closed panel identity guard."""
from dataclasses import dataclass, replace
import unittest

from hx_debt_panel_identity import panel_input_digest, UnboundDebtPanel, HX_FIELDS

@dataclass(frozen=True)
class Params:
    rate: float = .05
    payout: float = .03
    volatility: float = .25
    maturity: float = 2.
    principal: float = 60.
    coupon: float = 4.
    tax_shield: float = .25
    recovery: float = .6
    shock_intensity: float = 1.
    sale_fraction: float = .2

class PanelIdentityTests(unittest.TestCase):
    def digest(self, p=Params(), **kw):
        opts=dict(barrier=101.324,nodes=101,time_steps=250,log_upper=3.6)
        opts.update(kw)
        return panel_input_digest(p,**opts)

    def test_deterministic_sha_and_reconstructed_instance(self):
        self.assertEqual(self.digest(), self.digest(replace(Params())))
        self.assertEqual(len(self.digest()),64)

    def test_every_hx_field_is_bound(self):
        p=Params()
        for field in HX_FIELDS:
            with self.subTest(field=field):
                self.assertNotEqual(self.digest(), self.digest(replace(p, **{
                    field: getattr(p,field)+.001})))

    def test_all_grid_coordinates_are_bound(self):
        for change in ({'barrier':101.325},{'nodes':201},{'time_steps':500},
                       {'log_upper':4.}):
            with self.subTest(change=change):
                self.assertNotEqual(self.digest(),self.digest(**change))

    def test_bad_type_and_nonfinite_fail_closed(self):
        import math
        for change in ({'barrier':math.nan},{'barrier':True},
                       {'nodes':True},{'time_steps':0},{'log_upper':'3.6'},
                       {'barrier':0.}):
            with self.subTest(change=change),self.assertRaises(UnboundDebtPanel):
                self.digest(**change)
        with self.assertRaises(UnboundDebtPanel):
            self.digest(replace(Params(),volatility=math.inf))

    def test_missing_field_fails_closed(self):
        from types import SimpleNamespace
        with self.assertRaises(UnboundDebtPanel):
            self.digest(SimpleNamespace(rate=.05))

    def test_signed_zero_not_silently_conflated(self):
        self.assertNotEqual(self.digest(Params(payout=0.)),
                            self.digest(Params(payout=-0.)))

if __name__=='__main__': unittest.main()
