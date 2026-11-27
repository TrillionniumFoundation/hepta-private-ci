"""Targeted mathematical, adversarial, and complete-cohort roundoff tests.

Synthetic fixtures are not pretrained/NDU production proof.
"""
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parent/'ndu-p5-decision-cert'))
from rigorous_tree import (I,SCALE,Unqualified,iv,interval_fraction,add,sub,mul,divide,
                           half,sqrt_fraction,tanh_interval,action_bounds,global_map_bounds,resolve)
from audit import AuditError,audit,digest,EXPECTED_SOURCE
import mpmath as mp


def original_row():
    # Recreate deterministic frozen source. Does not import nominal solvers.
    from study import plan
    return plan()['cases'][0]


def original_cohort():
    from study import plan,predict
    p=plan()
    return p,predict(p)


def mpvalue(x):return mp.mpf(x)
def contains(i,value):return mp.mpf(i.lo)/SCALE <= value <=mp.mpf(i.hi)/SCALE


def mp_map(row,opt,y):
    with mp.workdps(110):
        steps=row['steps'];h=mpvalue(row['horizon'])/steps
        sigma=mpvalue(row['sigma']); beta=mpvalue(row['beta']); lam=mpvalue(row['lam']);a=mpvalue(opt['a'])
        n=len(y)
        x=[mp.mpf(0)]*(2*n+1);x[0]=mpvalue(row['x0'])
        for k in range(n):
            mid=x[k]+a*h*mpvalue(y[k]);x[2*k+1]=mid-sigma*mp.sqrt(h);x[2*k+2]=mid+sigma*mp.sqrt(h)
        v=[mp.mpf(0)]*n+[mp.tanh(z) for z in x[n:]]
        for k in reversed(range(n)):
            v[k]=((v[2*k+1]+v[2*k+2])/2+h*beta*mp.tanh(x[k]))/(1+h*lam)
        return v[:n]


class DirectedOutwardIntervals(unittest.TestCase):
    def test_rational_ceil_floor(self):
        with mp.workdps(110):
            for v in [Fraction(-1,3),Fraction(1,3),Fraction(0),Fraction(17,11),Fraction(-189,7)]:
                interval=interval_fraction(v)
                x=mp.mpf(v.numerator)/v.denominator
                self.assertTrue(contains(interval,x))
    def test_exact_float_bits(self):
        with mp.workdps(110):
            for v in [1.0,-0.1,0.8,-2.0,1e-10,5e4]:
                self.assertTrue(contains(iv(v),mp.mpf(v)))
    def test_products_and_quotients_enclosed(self):
        r=random.Random(7214)
        with mp.workdps(110):
            for _ in range(150):
                a=r.uniform(-10,10);b=r.uniform(0.02,4.)
                self.assertTrue(contains(mul(iv(a),iv(b)),mp.mpf(a)*mp.mpf(b)))
                self.assertTrue(contains(divide(iv(a),iv(b)),mp.mpf(a)/mp.mpf(b)))
    def test_sum_sub_half_enclosed(self):
        with mp.workdps(110):
            a,b=0.1190384412,3.2350432
            self.assertTrue(contains(add(iv(a),iv(b)),mp.mpf(a)+mp.mpf(b)))
            self.assertTrue(contains(sub(iv(a),iv(b)),mp.mpf(a)-mp.mpf(b)))
            self.assertTrue(contains(half(iv(a)),mp.mpf(a)/2))
    def test_sqrt_exact_and_irrational(self):
        with mp.workdps(110):
            for z in [Fraction(1,4),Fraction(1,2),Fraction(4,9),Fraction(77,20),Fraction(12,5)]:
                self.assertTrue(contains(sqrt_fraction(z),mp.sqrt(mp.mpf(z.numerator)/z.denominator)))
    def test_sqrt_negative_reject(self):
        for z in (0,-1):
            with self.assertRaises(Unqualified):sqrt_fraction(Fraction(z))
    def test_tanh_nonlinear_exact_enclosure(self):
        with mp.workdps(110):
            for x in [0.,1e-15,-1e-15,.0001,.1,-.1,.3,-.3,1.,-1.,1.7,-2.1,4.5,-7.5,12.]:
                self.assertTrue(contains(tanh_interval(iv(x)),mp.tanh(mp.mpf(x))),msg=str(x))
    def test_tanh_interval_monotone(self):
        with mp.workdps(110):
            a,b=mp.mpf(-.37),mp.mpf(1.21)
            iv_a,iv_b=iv(-.37),iv(1.21)
            cert=tanh_interval(I(iv_a.lo,iv_b.hi))
            self.assertTrue(contains(cert,mp.tanh(a)))
            self.assertTrue(contains(cert,mp.tanh(b)))
    def test_tanh_huge_reject(self):
        with self.assertRaises(Unqualified):tanh_interval(iv(17.0))
    def test_interval_division_zero_reject(self):
        with self.assertRaises(Unqualified):divide(iv(1.0),I(0,5))


class WholeTreeTests(unittest.TestCase):
    def test_complete_tree_encloses_high_precision_reference(self):
        row=original_row()
        rng=random.Random(1472)
        for option in row['options']:
            for _ in range(4):
                yy=[rng.uniform(-1.3,1.4) for _ in range(2**row['steps']-1)]
                mapped,q=global_map_bounds(row,option,yy)
                reference=mp_map(row,option,yy)
                with mp.workdps(110):
                    for ivalue,expect in zip(mapped,reference):
                        self.assertTrue(contains(ivalue,expect),msg=f'node {expect}')
                self.assertTrue(0<=q<1)
    def test_original_first_case_signed_gap(self):
        from study import plan,certify
        row=plan()['cases'][0]
        from decision import Task,Option
        t=Task(task_id=row['task_id'],x0=row['x0'],horizon=row['horizon'],sigma=row['sigma'],beta=row['beta'],lam=row['lam'],steps=row['steps'],options=tuple(Option(**v) for v in row['options']))
        nominal=certify(t)
        vals=[action_bounds(row,o,entry['y']) for o,entry in zip(row['options'],nominal['per_action'])]
        action,gap=resolve(vals)
        self.assertEqual(action,nominal['choice'])
        self.assertGreater(gap,0)
    def test_fail_closed_noncontractive(self):
        row=original_row();opt=copy.deepcopy(row['options'][2]);opt['a']=3.99
        with self.assertRaises(Unqualified): action_bounds(row,opt,[0.]*15)
    def test_fail_closed_missing_tree_state(self):
        row=original_row()
        with self.assertRaises(Unqualified): global_map_bounds(row,row['options'][1],[0.]*14)
    def test_fail_closed_nonfinite(self):
        row=original_row()
        with self.assertRaises(Unqualified): global_map_bounds(row,row['options'][1],[float('nan')]*15)
    def test_fail_closed_unsupported_state_domain(self):
        row=original_row();row['x0']=100.
        with self.assertRaises(Unqualified): global_map_bounds(row,row['options'][1],[0.]*15)
    def test_tied_values_do_not_certify(self):
        self.assertIsNone(resolve([{'action_id':'control_0','lower_ticks':0,'upper_ticks':0}])[0])
        self.assertIsNone(resolve([{'action_id':'control_0','lower_ticks':-1,'upper_ticks':1}])[0])


class HistoricalReauditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p,cls.s=original_cohort()
    def test_exact_original_source_binding(self):
        self.assertEqual(digest(self.p),EXPECTED_SOURCE)
    def test_all_192_admitted(self):
        a=audit(self.p,self.s,None)
        self.assertEqual(a['roundoff_enclosed_action_count'],192)
        self.assertEqual(a['nominal_map_calls_charged'],1511)
        self.assertEqual(a['authority'],'DENY_ALL')
        self.assertFalse(a['production_accepted'])
        self.assertFalse(a['continuous_time_FBSDE_certified'])
        self.assertGreater(a['audit_cpu_ns'],0)
    def test_reject_modified_source(self):
        bad=copy.deepcopy(self.p);bad['cases'][0]['x0']+=.01
        with self.assertRaises(AuditError):audit(bad,self.s,check_replay=False)
    def test_reject_order_swap(self):
        bad=copy.deepcopy(self.s);bad['entries'][0],bad['entries'][1]=bad['entries'][1],bad['entries'][0]
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_fake_head_computation(self):
        bad=copy.deepcopy(self.s);bad['entries'][0]['nominal_early']['per_action'][1]['calls']=1
        with self.assertRaises(AuditError):audit(self.p,bad)
    def test_reject_patched_nominal_radius(self):
        bad=copy.deepcopy(self.s);bad['entries'][0]['nominal_early']['per_action'][1]['radius']=1e-10
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_patched_nominal_action_gap(self):
        bad=copy.deepcopy(self.s);bad['entries'][0]['nominal_early']['positive_gap_lower_bound']=.8
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_forged_prod(self):
        bad=copy.deepcopy(self.s);bad['production_accepted']=True
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_missing_tasks(self):
        bad=copy.deepcopy(self.s);bad['entries'].pop()
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_changed_first_action(self):
        bad=copy.deepcopy(self.s);bad['entries'][0]['nominal_early']['choice']='abstain'
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)
    def test_reject_changed_field(self):
        bad=copy.deepcopy(self.s);bad['entries'][0]['nominal_early']['per_action'][1]['y'][0]+=0.001
        with self.assertRaises(AuditError):audit(self.p,bad,check_replay=False)

if __name__=='__main__':unittest.main()
