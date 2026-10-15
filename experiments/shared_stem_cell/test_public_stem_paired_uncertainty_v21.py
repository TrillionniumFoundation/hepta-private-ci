"""Offline synthetic paired uncertainty tests: no real model-efficacy claim."""
import copy
import unittest
from public_stem_paired_uncertainty_v21 import (
    paired_posthoc, PairedEvidenceError, CANDIDATES,
)
from public_stem_agnews_pilot_v20 import evaluate
from test_public_stem_agnews_pilot_v20 import fixture, mock_results

HASH='a'*64

def synthetic(only_m=0, only_g=0):
    cases=[{'case_id':f'te-{i:020x}','label':i//16} for i in range(64)]
    def probability(label, correct):
        best = label if correct else (label+1)%4
        return [0.85 if k==best else 0.05 for k in range(4)]
    predictions={}
    for arm in CANDIDATES:
        rows=[]
        for i,row in enumerate(cases):
            if i<only_m: good=arm=='mmbert-small'
            elif i<only_m+only_g: good=arm=='granite-97m-r2'
            else: good=True
            rows.append({'case_id':row['case_id'],
                         'probabilities':probability(row['label'],good)})
        predictions[arm]=rows
    return cases,predictions

class PairedPosthocContractTests(unittest.TestCase):
    def test_all_equal_predictions_have_zero_delta_and_p_one(self):
        target,preds=synthetic()
        out=paired_posthoc(target,preds,plan_sha256=HASH,target_sha256=HASH)
        self.assertEqual(out['paired_contingency']['both_correct'],64)
        self.assertEqual(out['mcnemar_exact_two_sided_p'],1.0)
        for stat in out['mmbert_minus_granite'].values():
            self.assertEqual(stat['observed'],0.0)
            self.assertEqual(stat['class_stratified_bootstrap95'],[0.0,0.0])
        self.assertFalse(out['significance_or_model_superiority_qualified'])
        self.assertFalse(out['deployed_no_change_observed'])
        self.assertIsNone(out['experiment_winner'])

    def test_discordant_case_counts_are_paired(self):
        cases,preds=synthetic(only_m=3,only_g=2)
        r=paired_posthoc(cases,preds,plan_sha256=HASH,target_sha256=HASH)
        self.assertEqual(r['paired_contingency'],{
            'both_correct':59,'mmbert_only_correct':3,
            'granite_only_correct':2,'both_incorrect':0})
        self.assertEqual(r['mcnemar_exact_two_sided_p'],1.0)
        self.assertAlmostEqual(r['mmbert_minus_granite']['accuracy']['observed'],1/64)

    def test_small_exact_p_does_not_authorize_model_selection(self):
        cases,preds=synthetic(only_m=6)
        r=paired_posthoc(cases,preds,plan_sha256=HASH,target_sha256=HASH)
        self.assertAlmostEqual(r['mcnemar_exact_two_sided_p'],0.03125)
        self.assertAlmostEqual(r['mmbert_minus_granite']['accuracy']['observed'],6/64)
        self.assertFalse(r['significance_or_model_superiority_qualified'])
        self.assertIsNone(r['experiment_winner'])
        self.assertEqual(r['authority'],'DENY_ALL')

    def test_bootstrap_is_reproducible_and_orientation_preserved(self):
        target,preds=synthetic(only_m=3,only_g=2)
        r=paired_posthoc(target,preds,plan_sha256=HASH,target_sha256=HASH)
        self.assertEqual(r,paired_posthoc(target,preds,plan_sha256=HASH,target_sha256=HASH))
        self.assertEqual(r['bootstrap_replicates'],4096)
        for name in ('accuracy','multiclass_brier','log_loss'):
            stat=r['mmbert_minus_granite'][name]
            self.assertLessEqual(stat['class_stratified_bootstrap95'][0],
                                 stat['class_stratified_bootstrap95'][1])
        self.assertLess(r['mmbert_minus_granite']['multiclass_brier']['observed'],0.0)

    def test_incomplete_or_unmatched_model_arms_rejected(self):
        target,preds=synthetic()
        bad=copy.deepcopy(preds);bad.pop('mmbert-small')
        with self.assertRaisesRegex(PairedEvidenceError,'coverage'):
            paired_posthoc(target,bad,plan_sha256=HASH,target_sha256=HASH)
        bad=copy.deepcopy(preds);bad['granite-97m-r2'][0]['case_id']='bad'
        with self.assertRaisesRegex(PairedEvidenceError,'census'):
            paired_posthoc(target,bad,plan_sha256=HASH,target_sha256=HASH)

    def test_corrupted_probabilities_fail_closed(self):
        targets,preds=synthetic()
        for p in ([float('nan'),0,0,1],[-0.01,0,0,1.01],[.1,.2,.3,.2],[.25]*3):
            bad=copy.deepcopy(preds)
            bad['mmbert-small'][0]['probabilities']=p
            with self.subTest(p=p),self.assertRaisesRegex(PairedEvidenceError,'probability'):
                paired_posthoc(targets,bad,plan_sha256=HASH,target_sha256=HASH)

    def test_wrong_class_strata_and_untrusted_digest_fail(self):
        targets,preds=synthetic()
        changed=copy.deepcopy(targets);changed[0]['label']=1
        with self.assertRaisesRegex(PairedEvidenceError,'strata'):
            paired_posthoc(changed,preds,plan_sha256=HASH,target_sha256=HASH)
        with self.assertRaisesRegex(PairedEvidenceError,'commitment'):
            paired_posthoc(targets,preds,plan_sha256='main',target_sha256=HASH)

    def test_independent_v20_evaluator_integrates_posthoc_without_approval(self):
        _,_,targets,plan=fixture()
        report=evaluate(plan,targets,mock_results(plan,targets))
        p=report['paired_exploratory_posthoc']
        self.assertEqual(p['case_count'],64)
        self.assertEqual(p['mcnemar_exact_two_sided_p'],1.0)
        self.assertEqual(p['plan_sha256'],report['source_plan_sha256'])
        self.assertEqual(p['heldout_targets_sha256'],report['heldout_targets_sha256'])
        self.assertFalse(p['significance_or_model_superiority_qualified'])
        self.assertFalse(report['deployed_no_change_baseline_observed'])
        self.assertFalse(report['production_accepted'])
        self.assertIsNone(report['winner'])

if __name__=='__main__': unittest.main()
