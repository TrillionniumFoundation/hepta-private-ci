"""Actual original E24 human receipt and prospective E25 research NO-PROMOTION tests."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest

from e26_frozen_admission import (METHODS,SOURCE_SHA,SPEC,OLD,load_spec,strict_json,
  original_e24_negative_control,model_free_precheck,exact_signflip,
  assess_e25_score,validate_e25_score,write_once)
from e26_second_opinion import independent_signflip

GROUPS=[f'{n:032x}' for n in range(1,7)]


def plausible_e25(primary=(0,0,0,0,0,0),control=(0,0,0,0,0,0),
                  brier_diff=0.0):
    """SYNTHETIC contract receipt only; never claims new original inference."""
    def arm(question_counts,score):
        per={g:v for g,v in zip(GROUPS,question_counts,strict=True)}
        hits={g:2+v for g,v in per.items()}
        return dict(correct_candidates=sum(hits.values()),total_candidates=36,
            complete_questions=sum(per.values()),total_questions=12,
            complete_passages=sum(v==2 for v in per.values()),total_passages=6,
            brier=score,per_passage_candidate_correct=hits,
            per_passage_complete_question=per)
    ms={m:arm((0,0,0,0,0,0),.5) for m in METHODS}
    ms['e16_scaled_brier_5']=arm(control,.4)
    ms['question_softworst_tau_001']=arm(primary,.4+brier_diff)
    refs=ms['mean_pool_query_fused'];paired={}
    for m in ('e16_scaled_brier_5','question_softworst_tau_001'):
        src=ms[m];d=[src['per_passage_candidate_correct'][g]-refs['per_passage_candidate_correct'][g] for g in GROUPS]
        p=independent_signflip(d)
        paired[m]={'paired_candidate_gain':src['correct_candidates']-refs['correct_candidates'],
           'paired_whole_question_gain':src['complete_questions']-refs['complete_questions'],
           'six_cluster_sign_flip_descriptive':f'{int(p*64)}/64'}
    return dict(schema='hepta.e25.new-six-original-source-complete-question-score.v1',
       authority='DENY_ALL',production_accepted=False,
       original_validation_source_sha256=SOURCE_SHA,human_truth_read_only_after_seal=True,
       actual_new_reader_train_anchor_slate_evidence_forwards=20,
       original_checkpoint_probe_forwards_additional_not_in_count=True,
       original_pretrained_four_readers_newly_fitted=True,original_passages_in_new_holdout=0,
       new_holdout_passages=6,novel_source_family=False,prospective_time_window=False,
       statistical_superiority_established=False,tau_chosen_posthoc_on_original_historical_groups=True,
       fourfold_ensemble_not_five_scalar_single_head=True,
       whole_service_training_inference_energy_and_verifier_cost_established=False,
       model_selected=False,all_source_original_human_labels_are_public_annotations=True,
       methods=ms,paired=paired,blind_sha256='a'*64,independent_reference_recomputed=True)


class FrozenSixPassageTests(unittest.TestCase):
    def test_01_exact_immutable_preoutcome_preregistration(self):
        x,h=load_spec()
        self.assertEqual(x['primary_method'],'question_softworst_tau_001')
        self.assertEqual(x['primary_control'],'e16_scaled_brier_5')
        self.assertEqual(x['hypothesis_count_for_confirmatory_e25_comparison'],1)
        self.assertEqual(len(h),64)

    def test_02_original_E24_HUMAN_receipt_real_not_synthetic(self):
        r=original_e24_negative_control()
        self.assertEqual(r['old_complete_question_delta'],2)
        self.assertEqual(r['old_two_sided_source_sign_flip_p'],'1/2')
        self.assertFalse(r['old_result_proves_future_gain'])

    def test_03_original_E24_receipt_tamper_even_rehashed_rejected(self):
        with TemporaryDirectory() as tmp:
            content=json.loads(OLD.read_text());content['results']['question_softworst_tau_001']['complete_questions']=5
            p=Path(tmp)/'forgery.json';p.write_text(json.dumps(content))
            with self.assertRaises(ValueError):original_e24_negative_control(p)

    def test_04_original_one_primary_two_sided_sign_flip_floor(self):
        self.assertEqual(exact_signflip([1]*6),F(1,32))
        self.assertEqual(exact_signflip([-2]*6),F(1,32))
        self.assertEqual(exact_signflip([1]*5+[0]),F(1,16))
        self.assertEqual(exact_signflip([1,1,1,1,1,-1]),F(7,32))

    def test_05_Holm_two_planned_hypotheses_can_never_clear_alpha(self):
        r=model_free_precheck()
        self.assertTrue(r['two_primary_hypotheses_at_alpha_005_infeasible'])
        self.assertEqual(r['two_primary_hypotheses_Holm_min_adjusted_p'],'1/16')
        self.assertFalse(r['new_six_passage_model_outcome_observed'])

    def test_06_independent_DP_agrees_exhaustive_enumeration(self):
        for delta in ((1,)*6,(2,-1,1,0,0,0),(0,)*6,(-1,)*4,[16,-16,5,6,0,0]):
            self.assertEqual(exact_signflip(delta),independent_signflip(delta))

    def test_07_single_primary_exploratory_promising_requires_six_independent_gains(self):
        d=plausible_e25(primary=(1,)*6)
        score=assess_e25_score(d)
        self.assertTrue(score['research_only_followup_signal'])
        self.assertEqual(score['exact_two_sided_six_passage_sign_flip_p'],'1/32')
        self.assertFalse(score['production_admitted'])
        self.assertFalse(score['future_source_family_generalization_established'])
        self.assertFalse(score['whole_service_cost_qualified'])

    def test_08_realistic_partial_gains_are_underpowered(self):
        r=assess_e25_score(plausible_e25(primary=(1,1,0,0,0,0)))
        self.assertEqual(r['exact_two_sided_six_passage_sign_flip_p'],'1/2')
        self.assertFalse(r['research_only_followup_signal'])

    def test_09_negative_transfer_preserved(self):
        p=plausible_e25(primary=(1,1,1,1,1,0),control=(0,0,0,0,0,1))
        r=assess_e25_score(p)
        self.assertFalse(r['source_level_no_negative_transfer'])
        self.assertFalse(r['research_only_followup_signal'])

    def test_10_brier_noninferiority_cannot_be_unbounded(self):
        positive=assess_e25_score(plausible_e25(primary=(1,)*6,brier_diff=.02))
        self.assertTrue(positive['research_only_followup_signal'])
        negative=assess_e25_score(plausible_e25(primary=(1,)*6,brier_diff=.021))
        self.assertFalse(negative['research_only_followup_signal'])

    def test_11_unknown_claim_and_unverified_work_refused(self):
        raw=plausible_e25()
        for k,v in (('production_accepted',True),('original_pretrained_four_readers_newly_fitted',False),
                    ('whole_service_training_inference_energy_and_verifier_cost_established',True),
                    ('new_holdout_passages',33),('new_authority','GRANT')):
            bad=deepcopy(raw);bad[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):validate_e25_score(bad)

    def test_12_candidate_metrics_must_balance_six_source_groups(self):
        for mutate in (
            lambda a:a['per_passage_candidate_correct'].__setitem__(GROUPS[0],99),
            lambda a:a['per_passage_complete_question'].__setitem__(GROUPS[1],3),
            lambda a:a.update(complete_passages=5),
            lambda a:a.update(total_candidates=33),
            lambda a:a['per_passage_candidate_correct'].pop(GROUPS[0]),
        ):
            bad=deepcopy(plausible_e25());mutate(bad['methods']['question_softworst_tau_001'])
            with self.assertRaises(ValueError):validate_e25_score(bad)

    def test_13_summary_paired_original_base_cannot_lie(self):
        b=plausible_e25(primary=(1,)*6)
        b['paired']['question_softworst_tau_001']['paired_whole_question_gain']=0
        with self.assertRaises(ValueError):validate_e25_score(b)

    def test_14_incorrect_group_descriptive_original_p_rejected(self):
        b=plausible_e25(primary=(1,)*6)
        b['paired']['question_softworst_tau_001']['six_cluster_sign_flip_descriptive']='0/64'
        with self.assertRaises(ValueError):validate_e25_score(b)

    def test_15_no_score_artifact_cannot_claim_new_real_efficacy(self):
        self.assertNotIn('research_only_followup_signal',model_free_precheck())

    def test_16_duplicate_json_key_and_nonfinite_source_rejected(self):
        with self.assertRaises(ValueError):strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(ValueError):strict_json(b'{"a":NaN}')

    def test_17_invalid_boolean_or_fractional_group_differences_rejected(self):
        for b in ([True]*6,[1.2]*6,[],[1]*13):
            with self.assertRaises(ValueError):exact_signflip(b)

    def test_18_create_only_research_verdict(self):
        with TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'e26.json')
            sig=write_once(path,model_free_precheck())
            self.assertEqual(len(sig),64)
            with self.assertRaises(FileExistsError):write_once(path,model_free_precheck())

    def test_19_tampered_preregistered_multi_hypothesis_refused(self):
        with TemporaryDirectory() as tmp:
            d=json.loads(SPEC.read_text());d['hypothesis_count_for_confirmatory_e25_comparison']=2
            p=Path(tmp)/'bad.json';p.write_text(json.dumps(d))
            with self.assertRaises(ValueError):load_spec(p)

    def test_20_original_model_frozen_source_byte_digest_remains_pinned(self):
        self.assertEqual(load_spec()[0]['e25_original_frozen_policy_sha256'],
                         'dec01b016354733183d6feac374e6a333a22b08af8ef2d48196480064ff36a88')


if __name__=='__main__':unittest.main()
