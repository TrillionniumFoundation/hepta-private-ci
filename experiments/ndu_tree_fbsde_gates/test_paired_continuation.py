"""Positive and adversarial mechanism regressions; no natural task claims."""
import copy
import json
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path
from random import Random
from paired_continuation import (ACTIONS,ARMS,FEATURE_DIM,action_report,
    choose_exact,digest,expected_values,features,fit,generate_public,produce_seal,
    public_case,public_panel,realized,world_for_training)
from paired_continuation_evaluator import score
from paired_trial_prepare import prepare


class PairedContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=prepare(n_train=128,n_future=40)
        cls.worlds=[tuple(v) for v in cls.data['train_worlds']['worlds']]
        cls.seal=produce_seal(cls.data['train_rows'],cls.worlds,
                               {k:cls.data[k] for k in ('future_1','future_2')})
        cls.sha=digest(cls.seal)

    def test_paired_policy_reality_matches_exact_expectation(self):
        row=self.data['future_1'][0]
        p=tuple(F(v) for v in row['prior'])
        for i,action in enumerate(ACTIONS):
            total=F(0)
            for a in (0,1):
                for b in (0,1):
                    prob=(p[0] if a else 1-p[0])*(p[1] if b else 1-p[1])
                    total+=prob*realized(row,action,(a,b))
            self.assertEqual(total,expected_values(row)[i])

    def test_actual_fit_and_complete_actions(self):
        model=fit(self.data['train_rows'],self.worlds)
        self.assertEqual(model['head_parameters'],45)
        self.assertEqual(model['training_pairs_observed'],384)
        self.assertGreater(model['training_cpu_ns'],0)
        preds,meters=action_report(self.data['future_1'],model)
        self.assertEqual(set(preds),set(ARMS))
        self.assertTrue(all(len(x)==40 for x in preds.values()))
        self.assertEqual(meters['learned_critic']['legal_actions_compared'],120)

    def test_two_window_score(self):
        for w,seed in [('future_1',919),('future_2',929)]:
            res=score(self.data[w],self.seal,sealed_sha256=self.sha,window=w,world_seed=seed)
            self.assertEqual(res['n'],40)
            self.assertGreaterEqual(res['arms']['learned_critic']['expected_regret_to_exact_tree'],-1e-12)
            self.assertEqual(res['arms']['exact_tree']['expected_regret_to_exact_tree'],0.)
            self.assertFalse(res['production_accepted'])

    def test_source_only_future_and_truth_not_in_seal(self):
        for split in ('future_1','future_2'):
            self.assertTrue(all(set(v)=={'case_id','group_id','observed_at','split','prior','cost'}
                                for v in self.data[split]))
        self.assertNotIn('worlds',self.seal)
        self.assertFalse(self.seal['future_labels_provided_to_critic'])

    def test_tampered_prediction_digest(self):
        bad=copy.deepcopy(self.seal)
        bad['predictions']['future_1']['no_search'][self.data['future_1'][0]['case_id']]='observe_0'
        with self.assertRaisesRegex(ValueError,'digest'):
            score(self.data['future_1'],bad,sealed_sha256=self.sha,window='future_1',world_seed=919)

    def test_missing_arm_even_with_valid_new_digest(self):
        bad=copy.deepcopy(self.seal)
        del bad['predictions']['future_1']['fixed_depth_1']
        with self.assertRaises(ValueError):
            score(self.data['future_1'],bad,sealed_sha256=digest(bad),window='future_1',world_seed=919)

    def test_candidate_promotion_refused(self):
        bad=copy.deepcopy(self.seal)
        bad['production_accepted']=True
        with self.assertRaises(ValueError):
            score(self.data['future_1'],bad,sealed_sha256=digest(bad),window='future_1',world_seed=919)

    def test_missing_future_action_rejected(self):
        bad=copy.deepcopy(self.seal)
        del bad['predictions']['future_2']['learned_critic'][self.data['future_2'][0]['case_id']]
        with self.assertRaises(ValueError):
            score(self.data['future_2'],bad,sealed_sha256=digest(bad),window='future_2',world_seed=929)

    def test_fabricated_cost_inventory_rejected(self):
        bad=copy.deepcopy(self.seal)
        bad['meters']['future_1']['learned_critic']['observation_action_count']=0
        with self.assertRaises(ValueError):
            score(self.data['future_1'],bad,sealed_sha256=digest(bad),window='future_1',world_seed=919)

    def test_fake_exact_tree_policy_rejected(self):
        bad=copy.deepcopy(self.seal)
        for case_id in bad['predictions']['future_1']['exact_tree']:
            bad['predictions']['future_1']['exact_tree'][case_id]='stop'
        with self.assertRaises(ValueError):
            score(self.data['future_1'],bad,sealed_sha256=digest(bad),window='future_1',world_seed=919)

    def test_reused_groups_refused(self):
        dup=copy.deepcopy(self.data['future_1'])
        dup[1]=copy.deepcopy(dup[0]);dup[1]['case_id']='future_1-alt'
        with self.assertRaises(ValueError):public_panel(dup,'future_1')

    def test_cross_window_group_rejected(self):
        bad=copy.deepcopy(self.data['future_2'])
        fromsrc=self.data['future_1'][0]
        bad[0]['prior']=fromsrc['prior'];bad[0]['cost']=fromsrc['cost'];bad[0]['group_id']=fromsrc['group_id']
        with self.assertRaises(ValueError):
            produce_seal(self.data['train_rows'],self.worlds,{'future_1':self.data['future_1'],'future_2':bad})

    def test_future_worlds_in_source_refused(self):
        bad=copy.deepcopy(self.data['future_1'])
        bad[0]['world']=[1,0]
        with self.assertRaises(ValueError):public_panel(bad,'future_1')

    def test_future_label_in_train_feature_refused(self):
        bad=copy.deepcopy(self.data['train_rows'])
        bad[0]['teacher_label']=1
        with self.assertRaises(ValueError):fit(bad,self.worlds)

    def test_noncanonical_rational_and_invalid_probability_refused(self):
        for v in ['2/4','-1/2','3/2','nan','0.2']:
            bad=copy.deepcopy(self.data['future_1'][0]);bad['prior'][0]=v
            with self.assertRaises(ValueError):public_case(bad)

    def test_invalid_claimed_model_rejected(self):
        bad=copy.deepcopy(self.seal)
        bad['future_labels_provided_to_critic']=True
        with self.assertRaises(ValueError):
            score(self.data['future_1'],bad,sealed_sha256=digest(bad),window='future_1',world_seed=919)

    def test_temporal_overlap_refused(self):
        bad=copy.deepcopy(self.data['future_1']);bad[0]['observed_at']=5
        with self.assertRaises(ValueError):public_panel(bad,'future_1')

    def test_no_negative_costs(self):
        bad=copy.deepcopy(self.data['train_rows'])
        bad[0]['cost'][0]='-1/3'
        with self.assertRaises(ValueError):fit(bad,self.worlds)

    def test_world_validation(self):
        model=copy.deepcopy(self.worlds)
        model[0]=(True,0)
        with self.assertRaises(ValueError):fit(self.data['train_rows'],model)

    def test_different_seed_splits_are_disjoint(self):
        d=self.data
        self.assertFalse(set(r['group_id'] for r in d['train_rows']) &
                         set(r['group_id'] for r in d['future_1']))

if __name__=='__main__':unittest.main()
