"""Independent parabolic debt PDE / elliptic equity QVI disagreement audit."""
from dataclasses import replace
import math
import unittest
from .hx import HX, boundary, bond_value
from .hx_bond_pde_independent import solve_bond_pde, UnresolvedBondPDE
from .hx_joint_pde_obstacle import audit_fixed_barrier_from_bond_pde, UnresolvedCoupledAudit
from .hx_obstacle_grid_tail_v2 import solve_fixed_boundary_obstacle as density_qvi


class IndependentFinancialPDETests(unittest.TestCase):
    def test_backward_bond_pde_refines_against_distinct_bond_formula(self):
        for sale in (.015,.2):
            p=HX(sale_fraction=sale)
            b=boundary(p)
            errors=[]
            for n,t in ((101,250),(201,500),(401,1000)):
                result=solve_bond_pde(p,b,nodes=n,time_steps=t)
                targets=(1.001,1.05,1.5,3.,10.)
                err=max(abs(result.at(b*r)-bond_value(p,b*r,p.maturity,b))
                        for r in targets)
                errors.append(err)
                self.assertLess(result.max_time_residual,1e-7)
                self.assertGreater(result.minimum_pivot,0)
                self.assertAlmostEqual(result.values[0],p.recovery*b/p.maturity,places=10)
            self.assertGreater(errors[0],errors[1])
            self.assertGreater(errors[1],errors[2])
            self.assertLess(errors[-1],.004)

    def test_incompatible_terminal_default_corner_kept_explicit(self):
        p=HX(sale_fraction=.2);b=boundary(p)
        result=solve_bond_pde(p,b,duration=0.,nodes=65,time_steps=10)
        self.assertEqual(result.at(b),p.recovery*b/p.maturity)
        self.assertEqual(result.at(b*math.exp(.1)),p.principal/p.maturity)
        self.assertIn('default wins',result.corner_contract)
        result_tiny=solve_bond_pde(p,b,duration=.01,nodes=201,time_steps=50)
        self.assertEqual(result_tiny.at(b),p.recovery*b/p.maturity)
        self.assertGreater(result_tiny.at(b*math.exp(.5)),0.)

    def test_financial_obstacle_stability_is_not_automatic_at_coarse_mesh(self):
        p=HX(sale_fraction=.2);b=boundary(p)
        pde=[];dens=[]
        for n,t in ((101,250),(201,500),(401,1000)):
            pde.append(audit_fixed_barrier_from_bond_pde(p,b,nodes=n,bond_time_steps=t))
            dens.append(density_qvi(p,b,nodes=n))
        # Coarse parabolic debt approximation can miss a narrow STOP strip.
        # The audit PRESERVES this disagreement rather than silently passing.
        self.assertIsNone(pde[0].last_stop_asset)
        self.assertIsNotNone(dens[0].last_stop_asset)
        for x,y in zip(pde[1:],dens[1:]):
            self.assertIsNotNone(x.last_stop_asset)
            self.assertAlmostEqual(x.last_stop_asset,y.last_stop_asset,places=8)
            self.assertLess(x.max_equity_bellman_residual,1e-7)
            self.assertTrue(x.exercise_runs)

    def test_nominal_financial_regime_has_no_extra_stop_on_checked_meshes(self):
        p=HX();b=boundary(p)
        for n,t in ((101,250),(201,500),(401,1000)):
            x=audit_fixed_barrier_from_bond_pde(p,b,nodes=n,bond_time_steps=t)
            self.assertIsNone(x.last_stop_asset)
            self.assertEqual(x.exercise_runs,())
            self.assertLess(x.max_equity_bellman_residual,1e-7)

    def test_upwind_generator_and_valid_finite_state_bond(self):
        p=HX(rate=.2,payout=0,volatility=.05)
        b=boundary(p)
        out=solve_bond_pde(p,b,log_upper=3.6,nodes=65,time_steps=100)
        self.assertGreater(out.left_jump_rate,0)
        self.assertGreater(out.right_jump_rate,0)
        self.assertTrue(all(math.isfinite(v) for v in out.values))

    def test_fail_closed_inputs_and_budgets(self):
        p=HX();b=boundary(p)
        for kw in ({'duration':-1},{'duration':p.maturity+1},
                   {'nodes':16},{'time_steps':0},{'log_upper':20},
                   {'nodes':5001,'time_steps':10000}):
            with self.subTest(kw=kw),self.assertRaises(UnresolvedBondPDE):
                solve_bond_pde(p,b,**kw)
        with self.assertRaises(UnresolvedBondPDE):
            solve_bond_pde(replace(p,volatility=0.),b)
        with self.assertRaises(UnresolvedBondPDE):
            solve_bond_pde(p,float('nan'))
        with self.assertRaises(UnresolvedCoupledAudit):
            audit_fixed_barrier_from_bond_pde(p,b,max_policy_iterations=0)
        with self.assertRaises(UnresolvedBondPDE):
            solve_bond_pde(p,b,nodes=101).at(b/2.)


if __name__=='__main__':
    unittest.main()
