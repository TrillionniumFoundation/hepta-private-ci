"""Bounded analytic/rational reflection oracle with independent density controls."""
from fractions import Fraction as F
import unittest
from unittest.mock import patch

from .first_hit_time_interval import bound_first_hit,UnresolvedFirstHit
from .first_hit_reflection_interval import (
    _tail,_tail_positive,bound_first_hit_reflection,
)
from .hx import HX,boundary
from .hx_bond_pde_rannacher import solve_bond_rannacher
from .rannacher_reflection_full_grid import certify_reflection_full_grid
from .rannacher_all_node_certificate import UnresolvedAllNode


class ReflectionIntervalTests(unittest.TestCase):
    def test_analytic_reflection_overlap_independent_time_density(self):
        count=0
        for mu in (-.5,-.01125,0.,.2,.7):
            for y in (.036,.3,1.,3.6):
                with self.subTest(mu=mu,y=y):
                    a=bound_first_hit_reflection(distance=y,drift=mu,
                              diffusion=.25,maturity=2.,discount=.25)
                    b=bound_first_hit(distance=y,drift=mu,
                              diffusion=.25,maturity=2.,discount=.25,
                              tolerance='.0005',max_cells=10000)
                    self.assertLessEqual(a.first_lower,b.first_upper)
                    self.assertLessEqual(b.first_lower,a.first_upper)
                    self.assertLessEqual(a.discounted_lower,b.discounted_upper)
                    self.assertLessEqual(b.discounted_lower,a.discounted_upper)
                    self.assertFalse(a.global_financial_equilibrium_certified)
                    count+=1
        self.assertEqual(count,20)

    def test_gaussian_series_and_mills_tail_are_ordered(self):
        for z in (F(0),F(1,100000),F(1),F(5),F(11,2),F(8),F(100)):
            low,high=_tail_positive(z)
            self.assertTrue(F(0)<=low<=high<=F(1,2))
        for z in (F(-4),F(-1),F(0),F(1),F(4)):
            lo,hi=_tail(z)
            other=_tail(-z)
            self.assertTrue(0<=lo<=hi<=1)
            self.assertLessEqual(lo+other[0],1)
            self.assertGreaterEqual(hi+other[1],1)

    def test_finite_reflection_refusal(self):
        for kw in ({'distance':0},{'distance':-1},
                   {'diffusion':0},{'maturity':0},
                   {'discount':-.1},{'distance':float('nan')}):
            default=dict(distance=.3,drift=0.,diffusion=.25,
                         maturity=2.,discount=.25)
            default.update(kw)
            with self.subTest(kw=kw),self.assertRaises(UnresolvedFirstHit):
                bound_first_hit_reflection(**default)


class RannacherFullGridTests(unittest.TestCase):
    def test_six_frozen_all_node_certificate_digests(self):
        # Two sale levels x 101/201/401 spatial grids, all nodes not probes.
        frozen={
          (.015,101):'dd80647fa5cf5dcbcb3a1193188a6e99dbd3aedebb9b28a5838ff3e96d624738',
          (.2,101):'fee1a42514eb2f23857520ea8d51b5dd992c8860f4f212a8fe259897ce512363',
          (.015,201):'7266c5677148e78699f42f4eb3afa74bcb1de1d867e0857742163bca09c6943a',
          (.2,201):'0655589169b7a253dc49c4ad36661da5d1458689ad2f507a917b493b934b604b',
          (.015,401):'cf9f10c5258a0cf0ea2ba6ecea0ee4051080b49d890fb40e7a0306ef5e0fcbf7',
          (.2,401):'8d1dbc83a8e203941ea6289099c9aee323c8083e2d04f53aa0624ebec0a0abb8',
        }
        for (sf,n),digest in frozen.items():
            with self.subTest(sale_fraction=sf,nodes=n):
                p=HX(sale_fraction=sf)
                out=certify_reflection_full_grid(p,boundary(p),nodes=n,
                                               time_steps={101:250,201:500,401:1000}[n])
                self.assertEqual(len(out.rows),n)
                self.assertEqual(out.canonical()['canonical_sha256'],digest)
                self.assertTrue(out.strict_all_node_advantage)
                self.assertLess(F(out.worst_rcn_upper),F(out.worst_be_lower))
                self.assertFalse(out.global_hx_equilibrium_certified)
                self.assertFalse(out.production_activation)

    def test_equal_solvers_do_not_pass_strict_comparison(self):
        p=HX();b=boundary(p)
        candidate=solve_bond_rannacher(p,b,nodes=33,time_steps=100)
        with patch('experiments.hcsn_hx_unified_v3.rannacher_reflection_full_grid.solve_bond_pde',
                   return_value=candidate):
            r=certify_reflection_full_grid(p,b,nodes=33,time_steps=100)
        self.assertFalse(r.strict_all_node_advantage)
        self.assertLessEqual(F(r.strict_margin),0)

    def test_incomplete_or_invalid_grid_refused(self):
        p=HX();b=boundary(p)
        for kwargs in ({'nodes':32,'time_steps':100},
                       {'nodes':33,'time_steps':0},
                       {'nodes':33,'time_steps':100,'log_upper':float('inf')}):
            with self.subTest(kw=kwargs),self.assertRaises(UnresolvedAllNode):
                certify_reflection_full_grid(p,b,**kwargs)


if __name__=='__main__': unittest.main()
