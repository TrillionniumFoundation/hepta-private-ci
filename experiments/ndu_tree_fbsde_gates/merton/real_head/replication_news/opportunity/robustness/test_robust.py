import itertools
import json
import os
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

from robust import (choose, delayed_gain_counterexample, descriptive_nested_audit,
                    exact_worst, gate_prior_before_fitting, law, q, report,
                    total_variation)


class RobustBound(unittest.TestCase):
    def test_unknown_types(self):
        for x in (True, False, .25, None, object()):
            with self.subTest(value=str(x)), self.assertRaises(ValueError):q(x)
    def test_bad_laws(self):
        for p,reward,e in [((F(1,2),), (0,), 0),((1,0),(0,),0),((2,-1),(0,1),0),
                           ((0,1),(0,1),2),((0,1),(0,1),-1)]:
            with self.subTest(p=p,e=e), self.assertRaises(ValueError):law(p,reward,e)
    def test_identity(self):
        prior=(F(3,4),F(1,4));returns=(F(3,4),F(1,2))
        val,dist,_=exact_worst(prior,returns,0)
        self.assertEqual((val,dist),(F(11,16),prior))
    def test_one_sided_worst(self):
        val,p,_=exact_worst((F(7,10),F(3,10)),(F(19,20),F(9,20)),F(3,20))
        self.assertEqual(p,(F(11,20),F(9,20)))
        self.assertEqual(val,F(29,40))
    def test_supremum_radius(self):
        val,p,_=exact_worst((F(3,4),F(1,4)),(F(9,10),F(1,10)),1)
        self.assertEqual((val,p),(F(1,10),(F(0),F(1))))
    def test_equal_returns(self):
        for e in (0,F(1,4),1):
            self.assertEqual(exact_worst((F(1,2),F(1,2)),(4,4),e)[0],4)
    def test_tv_transport_budget(self):
        p=(F(1,8),F(3,8),F(1,2));v=(-1,2,3)
        for e in (0,F(1,8),F(3,8),1):
            value,new,_=exact_worst(p,v,e)
            self.assertLessEqual(total_variation(p,new),e)
            self.assertEqual(value,sum(a*b for a,b in zip(new,v)))
    def test_brute_grid_oracle(self):
        # Enumerate all distributions on an exact quarter grid, with TV radius 1/4.
        rewards=(F(-1),F(1,2),F(2))
        for a in range(5):
            for b in range(5-a):
                p=(F(a,4),F(b,4),F(4-a-b,4))
                val,_,_=exact_worst(p,rewards,F(1,4))
                vals=[]
                for x in range(5):
                    for y in range(5-x):
                        candidate=(F(x,4),F(y,4),F(4-x-y,4))
                        if total_variation(p,candidate)<=F(1,4):
                            vals.append(sum(u*v for u,v in zip(candidate,rewards)))
                self.assertEqual(val,min(vals))
    def test_monotonic_radii(self):
        p=(F(1,2),F(1,3),F(1,6));v=(4,1,0)
        scores=[exact_worst(p,v,F(i,12))[0] for i in range(13)]
        self.assertEqual(scores,sorted(scores,reverse=True))
    def test_risk_monotonicity(self):
        p=(F(7,10),F(3,10));v=(F(19,20),F(9,20))
        robust=[F(choose(p,v,0,F(1,10),F(i,8)).robust_continuation) for i in range(5)]
        self.assertEqual(robust,sorted(robust,reverse=True))
    def test_ambiguity_reverses_decision(self):
        x=delayed_gain_counterexample()
        self.assertEqual((x['nominal']['decision'],x['robust']['decision']),('continue','stop'))
    def test_not_uniformly_optimal(self):
        x=delayed_gain_counterexample()
        self.assertGreater(F(x['good_world_continue_net']),F(x['common_stop_net']))
        self.assertLess(F(x['bad_world_continue_net']),F(x['common_stop_net']))
    def test_cold_start_upper_bound(self):
        self.assertFalse(gate_prior_before_fitting(1,0,1)['admit'])
        self.assertFalse(gate_prior_before_fitting(1,0,F(3,2))['admit'])
        self.assertTrue(gate_prior_before_fitting(1,0,F(1,2))['admit'])
        self.assertFalse(gate_prior_before_fitting(1,F(3,4),F(1,4))['admit'])
    def test_invalid_admission(self):
        for args in ((0,0,0),(1,F(3,2),0),(1,0,-1)):
            with self.assertRaises(ValueError):gate_prior_before_fitting(*args)
    def test_bad_alpha(self):
        with self.assertRaises(ValueError):choose((1,),(0,),0,0,F(3,4))
    def test_stop_on_tie(self):
        self.assertEqual(choose((1,),(F(1,2),),F(1,2)).decision,'stop')
    def test_nested_is_not_new_source(self):
        path=Path(os.environ['NESTED_SUMMARY'])
        r=descriptive_nested_audit(path)
        self.assertEqual((r['fixed8_correct'],r['ndu_correct']),(49,49))
        self.assertFalse(r['qualifies_transfer'])
    def test_tampered_nested_claim_fails(self):
        path=Path(os.environ['NESTED_SUMMARY'])
        o=json.loads(path.read_text())
        for k,value in (('transfer_qualified',True),('new_sources',1),
                        ('original32_holdout_used_for_new_training_or_scoring',True),
                        ('source_family_independence_verified',True)):
            with tempfile.TemporaryDirectory() as d:
                mutated=o.copy();mutated[k]=value
                f=Path(d)/'mutated.json';f.write_text(json.dumps(mutated))
                with self.subTest(field=k),self.assertRaises(ValueError):descriptive_nested_audit(f)
    def test_descriptive_only(self):
        r=report(os.environ['NESTED_SUMMARY'])
        self.assertFalse(r['real_task_superiority_established'])
        self.assertEqual(r['new_independent_source_groups'],0)
        self.assertEqual(len(r['registered_sensitivity']),10)
    def test_no_production_capability(self):
        d=choose((F(1,2),F(1,2)),(1,0),F(1,2))
        self.assertTrue(d.unsupported_source)
        self.assertFalse(d.production_permission)
        self.assertEqual(d.source_new_model_calls,0)


if __name__=='__main__':unittest.main()
