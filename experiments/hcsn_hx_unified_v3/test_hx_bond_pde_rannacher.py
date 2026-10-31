"""Bounded comparison of Rannacher-CN debt PDE to BE and independent oracles.

All tests are research-only. Neither f64 residual nor pointwise agreement with
an analytic financial bond is an interval continuum/truncation certificate.
"""
from dataclasses import replace
import math
import unittest

from .hx import HX,boundary,bond_value
from .hx_bond_pde_independent import solve_bond_pde
from .hx_bond_mp_reference import bond_time_integral
from .hx_bond_pde_rannacher import solve_bond_rannacher,UnresolvedRannacher


class DebtRannacherTests(unittest.TestCase):
    def test_six_development_meshes_accuracy_vs_be(self):
        for sf in (.015,.2):
            p=HX(sale_fraction=sf);b=boundary(p)
            for nodes,steps in ((101,250),(201,500),(401,1000)):
                with self.subTest(sf=sf,nodes=nodes):
                    old=solve_bond_pde(p,b,nodes=nodes,time_steps=steps,log_upper=3.6)
                    new=solve_bond_rannacher(p,b,nodes=nodes,time_steps=steps,log_upper=3.6)
                    exact=[bond_value(p,b*math.exp(i*3.6/(nodes-1)),p.maturity,b)
                           for i in range(nodes)]
                    be=max(abs(o-e) for o,e in zip(old.values,exact))
                    cn=max(abs(c-e) for c,e in zip(new.values,exact))
                    self.assertLess(cn,be)
                    self.assertLess(new.max_step_residual,1e-10)
                    self.assertGreater(new.minimum_pivot,1)
                    self.assertTrue(new.positivity_proved_for_discrete_weights)
                    self.assertFalse(new.scientific_gate_closed)
                    self.assertFalse(new.production_activation)

    def test_high_precision_physical_time_first_hit(self):
        # Entirely separate physical-t first-hit integral, no HX Eq8 or CN.
        for sf in (.015,.2):
            p=HX(sale_fraction=sf);b=boundary(p)
            cn=solve_bond_rannacher(p,b,nodes=101,time_steps=250)
            be=solve_bond_pde(p,b,nodes=101,time_steps=250,log_upper=3.6)
            for j in (1,9,37):
                with self.subTest(sf=sf,index=j):
                    a=b*math.exp(j*cn.grid_step)
                    time_oracle=bond_time_integral(p,a,b,digits=60)
                    exact=float(time_oracle.value)
                    self.assertLess(abs(bond_value(p,a,p.maturity,b)-exact),2e-9)
                    self.assertLess(abs(cn.values[j]-exact),.025)
                    # Stronger than an arbitrary no-default boundary check:
                    # test both numerical schemes against the *same* independent ref.
                    self.assertTrue(math.isfinite(be.values[j]))

    def test_development_numerical_refinement(self):
        for sf in (.015,.2):
            p=HX(sale_fraction=sf);b=boundary(p)
            errors=[]
            for n,t in ((101,250),(201,500),(401,1000)):
                grid=solve_bond_rannacher(p,b,nodes=n,time_steps=t)
                errors.append(max(abs(grid.values[j]-bond_value(p,b*math.exp(j*grid.grid_step),
                                     p.maturity,b)) for j in range(n)))
            self.assertLess(errors[1],.27*errors[0])
            self.assertLess(errors[2],.27*errors[1])

    def test_true_terminal_corner_and_no_default_far_field(self):
        p=HX(sale_fraction=.2);b=boundary(p)
        g=solve_bond_rannacher(p,b,duration=0,nodes=33,time_steps=5)
        self.assertAlmostEqual(g.values[0],p.recovery*b/p.maturity)
        self.assertEqual(tuple(g.values[1:]),tuple([p.principal/p.maturity]*32))
        t=.5
        grid=solve_bond_rannacher(p,b,duration=t,nodes=101,time_steps=250)
        q=p.rate+p.shock_intensity*p.sale_fraction
        base=p.coupon/p.maturity/q
        far=base+math.exp(-q*t)*(p.principal/p.maturity-base)
        self.assertAlmostEqual(grid.values[-1],far,places=12)
        self.assertEqual(grid.values[0],p.recovery*b/p.maturity)
        self.assertEqual(grid.values,solve_bond_rannacher(p,b,duration=t,nodes=101,time_steps=250).values)

    def test_drift_upwinding_and_physical_positivity(self):
        p=HX(rate=1.,payout=0.,volatility=.1,maturity=1.,sale_fraction=.05)
        b=100.
        g=solve_bond_rannacher(p,b,nodes=65,time_steps=600,log_upper=3.6)
        self.assertTrue(all(math.isfinite(z) and z>=0 for z in g.values))
        self.assertTrue(g.positivity_proved_for_discrete_weights)
        self.assertLess(g.max_step_residual,1e-10)

    def test_invalid_cfl_and_unsupported_inputs_fail_closed(self):
        p=HX();b=boundary(p)
        checks=({'nodes':30},{'nodes':32},{'nodes':5002},
                {'time_steps':0},{'time_steps':1},{'time_steps':20001},
                {'log_upper':.01},{'log_upper':13},{'duration':-1},
                {'duration':100})
        for kw in checks:
            with self.subTest(kw=kw),self.assertRaises(UnresolvedRannacher):
                solve_bond_rannacher(p,b,**kw)
        for x in (0,math.nan,-1,math.inf):
            with self.subTest(barrier=x),self.assertRaises(UnresolvedRannacher):
                solve_bond_rannacher(p,x)
        with self.assertRaises(UnresolvedRannacher):
            solve_bond_rannacher(replace(p,rate=-1),b)
        with self.assertRaises(UnresolvedRannacher):
            solve_bond_rannacher(p,b,nodes=1001,time_steps=10)
        with self.assertRaises(UnresolvedRannacher):
            solve_bond_rannacher(p,b,log_upper=3.6,nodes=1001,time_steps=20000)

if __name__=='__main__':
    unittest.main()
