"""Model-free boundary, mutation, numerical and cost-accounting research tests."""
import copy
from decimal import Decimal, localcontext
import math
import random
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ndu-p5-fast-outward'))
sys.path.insert(0,str(ROOT/'ndu-p5-roundoff'))
sys.path.insert(0,str(ROOT/'ndu-p5-decision-cert'))
from fast_tanh import tanh_point,tanh_interval,fast_action_bounds,REDUCTIONS,TERMS
from rigorous_tree import I,SCALE,MAX_EXP_ARG,Unqualified,action_bounds,resolve
from compare import compare,verify_inputs,ReplayError
from study import plan,predict,hexdigest
from independent_score import replay

class TanhBounds(unittest.TestCase):
    def test_parameters_fixed(self):
        self.assertEqual((REDUCTIONS,TERMS),(6,16))
    def test_domain(self):
        for i in (-(MAX_EXP_ARG//2+1),MAX_EXP_ARG//2+1):
            with self.assertRaises(Unqualified):tanh_point(i)
    def test_stops_outside_domain(self):
        with self.assertRaises(Unqualified):tanh_point(17*SCALE)
    def test_zero_exact(self):
        self.assertEqual(tanh_point(0),I(0,0))
    def test_odd_symmetry(self):
        for z in (1,17,SCALE//100,SCALE,4*SCALE,16*SCALE):
            a,b=tanh_point(z),tanh_point(-z)
            self.assertEqual((a.lo,a.hi),(-b.hi,-b.lo))
    def test_high_precision_random_with_endpoints(self):
        rng=random.Random(170215)
        samples=[0,1,-1,2,-2,SCALE//13,-SCALE//13,SCALE,-SCALE,16*SCALE,-16*SCALE]
        samples += [int(rng.uniform(-16,16)*SCALE) for _ in range(160)]
        with localcontext() as ctx:
            ctx.prec=120
            for v in samples:
                bound=tanh_point(v)
                x=Decimal(v)/Decimal(SCALE)
                e=(2*x).exp()
                exact=(e-1)/(e+1)
                self.assertLessEqual(Decimal(bound.lo)/Decimal(SCALE),exact)
                self.assertGreaterEqual(Decimal(bound.hi)/Decimal(SCALE),exact)
    def test_tanh_matches_original_overlap(self):
        from rigorous_tree import tanh_point as original
        for v in [-16,-8,-3,-1,-.0001,0,.0001,1,3,8,16]:
            z=int(v*SCALE)
            a,b=tanh_point(z),original(z)
            self.assertLessEqual(a.lo,b.hi)
            self.assertLessEqual(b.lo,a.hi)
    def test_monotonic_interval(self):
        a=tanh_interval(I(-SCALE//5,SCALE//3))
        self.assertLess(a.lo,0);self.assertGreater(a.hi,0)
        self.assertLess(a.lo,a.hi)
    def test_noninteger_ticks_rejected(self):
        with self.assertRaises(Unqualified):tanh_point(1.5)
    def test_q_reject(self):
        task=plan()['cases'][0];option=dict(task['options'][2]);option['a']=3.
        with self.assertRaises(Unqualified):fast_action_bounds(task,option,[0.]*15)
    def test_bad_nan(self):
        task=plan()['cases'][0];option=task['options'][0]
        with self.assertRaises((ValueError,Unqualified,TypeError)):
            fast_action_bounds(task,option,[float('nan')]*15)
    def test_wrong_y_length(self):
        task=plan()['cases'][0];option=task['options'][0]
        with self.assertRaises(Unqualified):fast_action_bounds(task,option,[0.]*14)
    def test_nonfinite_option(self):
        task=plan()['cases'][0];option=dict(task['options'][0]);option['cost']=float('inf')
        with self.assertRaises(Unqualified):fast_action_bounds(task,option,[0.]*15)
    def test_one_exact_action_overlaps_reference(self):
        task=plan()['cases'][0];o=task['options'][1]
        a,b=fast_action_bounds(task,o,[0.]*15),action_bounds(task,o,[0.]*15)
        self.assertLessEqual(a['lower_ticks'],b['upper_ticks'])
        self.assertLessEqual(b['lower_ticks'],a['upper_ticks'])
        self.assertEqual(a['q_exact_numerator']*b['q_exact_denominator'],
                         b['q_exact_numerator']*a['q_exact_denominator'])

class AuditedCohort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=plan()
        cls.sealed=predict(cls.plan)
        cls.prior=replay(cls.plan,cls.sealed)
    def test_source_reproducible(self):
        self.assertEqual(hexdigest(self.plan),'e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2')
    def test_seal_prerequisite(self):
        self.assertEqual(len(verify_inputs(self.plan,self.sealed,self.prior)),192)
    def test_missing_slot_reject(self):
        x=copy.deepcopy(self.sealed);x['entries'].pop()
        with self.assertRaises(ReplayError):verify_inputs(self.plan,x,self.prior)
    def test_objective_change_reject(self):
        x=copy.deepcopy(self.plan);x['cases'][0]['x0']+=0.1
        with self.assertRaises(ReplayError):verify_inputs(x,self.sealed,self.prior)
    def test_fabricated_authority_reject(self):
        x=copy.deepcopy(self.sealed);x['production_accepted']=True
        with self.assertRaises(ReplayError):verify_inputs(self.plan,x,self.prior)
    def test_changed_seal_digest_reject(self):
        x=copy.deepcopy(self.prior);x['sealed_prediction_sha256']='1'*64
        with self.assertRaises(ReplayError):verify_inputs(self.plan,self.sealed,x)
    def test_overclaim_continuum_reject(self):
        x=copy.deepcopy(self.prior);x['continuous_FBSDE_or_roundoff_rigorous']=True
        with self.assertRaises(ReplayError):verify_inputs(self.plan,self.sealed,x)
    def test_missing_early_trajectory_reject(self):
        x=copy.deepcopy(self.sealed);x['entries'][0]['nominal_early']['per_action'].pop()
        z=copy.deepcopy(self.prior);z['sealed_prediction_sha256']=hexdigest(x)
        with self.assertRaises(ReplayError):compare(self.plan,x,z)
    def test_duplicate_results_reject(self):
        x=copy.deepcopy(self.prior);x['rows'][1]['task_id']=x['rows'][0]['task_id']
        with self.assertRaises(ReplayError):verify_inputs(self.plan,self.sealed,x)
    def test_tampered_paid_work_with_resigned_digest_reject(self):
        x=copy.deepcopy(self.sealed)
        x['entries'][0]['nominal_early']['per_action'][0]['y'][0]+=.001
        z=copy.deepcopy(self.prior);z['sealed_prediction_sha256']=hexdigest(x)
        with self.assertRaises(ReplayError):compare(self.plan,x,z)
    def test_full_192_pair(self):
        result=compare(self.plan,self.sealed,self.prior)
        self.assertEqual((result['old_certified'],result['new_certified']),(192,192))
        self.assertEqual(result['original_nominal_map_calls'],1511)
        self.assertEqual(result['task_count'],192)
        self.assertFalse(result['production_accepted'])
        self.assertFalse(result['cost_adjusted_online_gain_established'])
        self.assertFalse(result['continuous_time_fbsde_certified'])
        self.assertGreater(result['new_interval_cpu_ms'],0)
        self.assertGreater(result['old_interval_cpu_ms'],0)
    def test_negative_budget_count(self):
        x=copy.deepcopy(self.sealed)
        x['entries'][0]['nominal_early']['work_calls']+=1
        z=copy.deepcopy(self.prior);z['sealed_prediction_sha256']=hexdigest(x)
        with self.assertRaises(ReplayError):compare(self.plan,x,z)

if __name__=='__main__':unittest.main()
