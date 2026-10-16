"""Adversarial prospective-mechanism tests; all constructed, not task evidence."""
import unittest
import math
import tempfile
from pathlib import Path
from fractions import Fraction as Q
from roi_frontier import (reject, original_labels, class_id, inspect_row, pareto_pair,
                          exact_net_delta, break_even_step_tariff, read_json, original_frontier,
                          STEPS,ARMS,SCHEMA)
import zipfile
import json


def make_row(arm='fixed8', repeat=0, steps=8, cpu=10000, ids=None, probs=None):
    ids=['sample'+str(i) for i in range(32)] if ids is None else ids
    probs=[[1.,0.,0.,0.]]*32 if probs is None else probs
    return {'arm':arm,'repeat':repeat,'actual_steps':steps,
            'selected_steps':0 if steps==0 else 8 if arm not in ('fixed32','fixed128') else steps,
            'cpu_ns':cpu,'wall_ns':cpu,'phases':{'fit':{'cpu_ns':cpu//2,'wall_ns':cpu//2}},
            'holdout_ids':ids,'probabilities':probs}


class ExactPrice(unittest.TestCase):
    def test_01_costlier_equal_success_is_negative(self):
        self.assertEqual(exact_net_delta(0,120,Q(1),Q(1,256)),Q(-15,32))
    def test_02_costlier_equal_success_never_positive_at_nonnegative_step_tariff(self):
        for k in range(12):
            self.assertLessEqual(exact_net_delta(0,120,Q(10000),Q(k,31)),0)
    def test_03_positive_lift_can_offset_higher_cost(self):
        self.assertEqual(exact_net_delta(3,8,Q(1),Q(1,4)),1)
    def test_04_cost_saved_can_offset_loss_under_declared_tariff(self):
        self.assertEqual(exact_net_delta(-1,-100,Q(1),Q(1,2)),49)
    def test_05_break_even_positive_lift(self):
        self.assertEqual(break_even_step_tariff(2,12),6)
    def test_06_no_lift_has_no_finite_break_even(self):
        self.assertIsNone(break_even_step_tariff(0,120))
    def test_07_negative_lift_has_no_positive_lift_threshold(self):
        self.assertIsNone(break_even_step_tariff(-1,-200))
    def test_08_cheaper_successful_policy_needs_no_positive_reward_threshold(self):
        self.assertEqual(break_even_step_tariff(1,-20),0)
    def test_09_zero_fee_is_allowed(self):
        self.assertEqual(exact_net_delta(0,5,Q(0),Q(0)),0)
    def test_10_negative_fee_rejected(self):
        with self.assertRaises(ValueError):exact_net_delta(0,5,Q(-1),Q(1))
    def test_11_float_fee_rejected(self):
        with self.assertRaises(ValueError):exact_net_delta(0,5,.1,Q(1))
    def test_12_boolean_evidence_rejected(self):
        for args in ((True,2,Q(1),Q(1)),(1,False,Q(1),Q(1))):
            with self.assertRaises(ValueError):exact_net_delta(*args)
    def test_13_noninteger_break_even_rejected(self):
        with self.assertRaises(ValueError):break_even_step_tariff(1.0,8)


class OriginalStructure(unittest.TestCase):
    def setUp(self):
        self.ids=['sample'+str(i) for i in range(32)]
        self.labels={i:0 for i in self.ids}
        self.sample=make_row(ids=self.ids)

    def check(self,fn):
        with self.assertRaises(ValueError): fn()

    def test_14_exact_four_probability_classes(self):
        self.assertEqual(class_id([0.1,0.1,0.3,0.5]),3)
    def test_15_tied_class_chooses_first(self):
        self.assertEqual(class_id([.25]*4),0)
    def test_16_probabilities_do_not_allow_nan(self):
        self.check(lambda:class_id([float('nan'),0,0,1]))
    def test_17_negative_class_probability(self):
        self.check(lambda:class_id([-1,0,1,1]))
    def test_18_unnormalized_probability(self):
        self.check(lambda:class_id([.2]*4))
    def test_19_bool_probability_rejected(self):
        self.check(lambda:class_id([True,0,0,0]))
    def test_20_wrong_arm_is_rejected(self):
        self.check(lambda:inspect_row(self.sample,'ndu_discrete',0,self.labels))
    def test_21_unearned_8_checkpoint_refused(self):
        x=make_row(ids=self.ids);x['selected_steps']=128
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_22_fake_update_census_refused(self):
        x=make_row(ids=self.ids);x['actual_steps']=128
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_23_boolean_cpu_refused(self):
        x=make_row(ids=self.ids);x['cpu_ns']=True
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_24_phase_exceeds_total_refused(self):
        x=make_row(ids=self.ids);x['phases']['fit']['cpu_ns']=x['cpu_ns']+1
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_25_missing_source_refused(self):
        x=make_row(ids=self.ids[:-1],probs=[[1,0,0,0]]*31)
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_26_duplicate_source_refused(self):
        ids=self.ids.copy();ids[-1]=ids[-2];x=make_row(ids=ids)
        self.check(lambda:inspect_row(x,'fixed8',0,self.labels))
    def test_27_same_original_outputs_strictly_more_steps_dominated(self):
        a=inspect_row(self.sample,'fixed8',0,self.labels)
        b=inspect_row(make_row('ndu_discrete',0,128,20000,ids=self.ids),
                      'ndu_discrete',0,self.labels)
        v=pareto_pair(b,a)
        self.assertTrue(v['observed_two_dimension_dominance'])
        self.assertTrue(v['same_original_probabilities'])
        self.assertEqual(v['step_delta'],120)
    def test_28_better_accuracy_can_justify_cost_not_pareto_dominated(self):
        a=inspect_row(self.sample,'fixed8',0,self.labels)
        p=[[1,0,0,0] for _ in self.ids];p[0]=[0,1,0,0]
        b=inspect_row(make_row('ndu_discrete',0,128,20000,ids=self.ids,probs=p),
                      'ndu_discrete',0,self.labels)
        self.assertFalse(pareto_pair(b,a)['observed_two_dimension_dominance'])
    def test_29_cpu_undercut_blocks_two_dimensional_dominance(self):
        a=inspect_row(self.sample,'fixed8',0,self.labels)
        b=inspect_row(make_row('ndu_discrete',0,128,9000,ids=self.ids),
                      'ndu_discrete',0,self.labels)
        self.assertFalse(pareto_pair(b,a)['observed_two_dimension_dominance'])
    def test_30_same_accuracy_can_hide_changed_task_outcomes(self):
        truth=dict(self.labels);truth[self.ids[1]]=1
        a=inspect_row(self.sample,'fixed8',0,truth)
        p=[[1,0,0,0] for _ in self.ids];p[0]=[0,1,0,0];p[1]=[0,1,0,0]
        b=inspect_row(make_row('ndu_discrete',0,128,20000,ids=self.ids,probs=p),
                      'ndu_discrete',0,truth)
        self.assertEqual(a['correct'],b['correct'])
        self.assertFalse(pareto_pair(b,a)['same_per_task_outcomes'])
        self.assertFalse(pareto_pair(b,a)['observed_two_dimension_dominance'])
    def test_34_same_classes_but_different_calibration_not_full_dominance(self):
        a=inspect_row(self.sample,'fixed8',0,self.labels)
        q=[[.8,.2,0,0] for _ in self.ids]
        b=inspect_row(make_row('ndu_discrete',0,128,20000,ids=self.ids,probs=q),
                      'ndu_discrete',0,self.labels)
        result=pareto_pair(b,a)
        self.assertTrue(result['same_per_task_outcomes'])
        self.assertFalse(result['same_original_probabilities'])
        self.assertFalse(result['observed_two_dimension_dominance'])


class ArchiveContracts(unittest.TestCase):
    def test_31_unknown_archive_fails_without_substitute(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fake.zip';p.write_bytes(b'not a true source')
            with self.assertRaises(ValueError):original_frontier(p,p)
    def test_32_duplicate_json_keys_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dupe.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('x.json','{"a":1,"a":2}')
            with zipfile.ZipFile(p) as z:
                with self.assertRaises(ValueError):read_json(z,'x.json')
    def test_33_corrupt_json_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('x.json','{"a":NaN}')
            with zipfile.ZipFile(p) as z:
                with self.assertRaises(ValueError):read_json(z,'x.json')


if __name__=='__main__':unittest.main()
