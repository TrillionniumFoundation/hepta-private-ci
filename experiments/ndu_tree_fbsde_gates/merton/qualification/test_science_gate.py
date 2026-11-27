"""Adversarial, label-owner-free source-contract fixtures.

The passing fixture is a CONSTRUCTED MECHANISM, not original independent data.
"""
import copy
from fractions import Fraction as Q
import unittest
from science_gate import (SCHEMA, digest, stable, loads, ensure, argmax4,
                          sign_test_one_sided, holm_one_sided, prospective_structure)

FIELDS=('model_material','encoder','training','pilot','inference',
        'verifier','policy_compile','policy_load','migration')


def fixture(groups=24,windows=3):
    ids=[];labels={};pred=[]
    for i in range(groups):
        case=f'constructed:family{i}:question0'
        ids.append({'case_id':case,'source_family':f'family:{i}',
                    'window':f'future-synthetic-window:{i%windows}',
                    'source_digest':digest(case)})
        labels[case]=1
        pred.append({'case_id':case,'arms':{
            'fixed8':0,'neutral':0,'ndu_discrete':1}})
    seal={'schema':'hepta.prospective.blind.v1','rows':pred,
          'labels_present':False,'score_present':False,'digest':digest(pred)}
    costs={arm:{p:(0 if arm!='ndu_discrete' else 1) for p in FIELDS}
           for arm in ('fixed8','neutral','ndu_discrete')}
    return {'schema':SCHEMA+'.input','objective':'full_task_exact_accuracy',
            'posture':'RESEARCH_ONLY_DENY_ALL','production_accepted':False,
            'controls':['fixed8','neutral','ndu_discrete'],
            'source_inventory':ids,'held_labels':labels,
            'blind_prediction_seal':seal,'invoices':costs,
            'protocol':{'source_manifest_digest':digest(ids),
                        'candidate_frozen_before_evaluation':True,
                        'shared_encoder_digest':digest('frozen-encoder'),
                        'fixed_reader_digest':digest('original-reader'),
                        'fixed_tokenizer_digest':digest('original-tokenizer')}}


class ExactMath(unittest.TestCase):
    def test_01_no_discordant_groups_cannot_claim_win(self):
        self.assertEqual(sign_test_one_sided(0,0),1)
    def test_02_single_win_is_not_significant(self):
        self.assertEqual(sign_test_one_sided(1,0),Q(1,2))
    def test_03_nineteen_wins_no_losses(self):
        self.assertEqual(sign_test_one_sided(19,0),Q(1,2**19))
    def test_04_all_losses_one_sided_p_one(self):
        self.assertEqual(sign_test_one_sided(0,7),1)
    def test_05_balanced_discordant_sign(self):
        self.assertEqual(sign_test_one_sided(2,2),Q(11,16))
    def test_06_ties_must_not_increase_effective_n(self):
        self.assertEqual(sign_test_one_sided(2,1),Q(1,2))
    def test_07_invalid_fraction_arguments(self):
        for pair in [(-1,0),(False,1),(1,-1),(1,1.0)]:
            with self.subTest(pair=pair),self.assertRaises(ValueError):sign_test_one_sided(*pair)
    def test_08_holm_two_hypotheses(self):
        self.assertEqual(holm_one_sided((Q(1,100),Q(3,100))), (Q(1,50),Q(3,100)))
    def test_09_holm_is_monotone(self):
        self.assertEqual(holm_one_sided((Q(1,5),Q(1,100),Q(1,40))),
                         (Q(1,5),Q(3,100),Q(1,20)))
    def test_10_holm_invalid_probability_rejected(self):
        for p in ((),(Q(-1,2),),(1.2,),(Q(2),)):
            with self.assertRaises(ValueError): holm_one_sided(p)
    def test_11_prediction_tie_break_is_first(self):
        self.assertEqual(argmax4([.25]*4),0)
    def test_12_prediction_probability_shape(self):
        for p in ([-.1,.2,.3,.6],[.2,.2,.2,.2],[float('nan'),0,0,1],
                  [1,0,0],[True,0,0,0]):
            with self.subTest(p=p),self.assertRaises(ValueError):argmax4(p)
    def test_13_json_duplicate_key_refused(self):
        with self.assertRaises(ValueError): loads(b'{"a":1,"a":2}')
    def test_14_json_nonfinite_refused(self):
        with self.assertRaises(ValueError):loads(b'{"v":NaN}')
    def test_15_hash_is_order_independent_for_dict(self):
        self.assertEqual(digest({'b':1,'a':2}),digest({'a':2,'b':1}))


class SourceContract(unittest.TestCase):
    def setUp(self): self.a=fixture()
    def run_gate(self): return prospective_structure(self.a)
    def refuse(self):
        with self.assertRaises(ValueError):self.run_gate()

    def test_16_even_perfect_constructed_gain_not_production(self):
        r=self.run_gate()
        self.assertEqual(r['case_count'],24)
        self.assertEqual(r['declared_source_family_count'],24)
        self.assertEqual(r['declared_time_window_count'],3)
        self.assertFalse(r['independently_verified_new_source_efficacy'])
        self.assertFalse(r['model_promotion_qualified'])
        self.assertEqual(r['comparisons'][0]['paired_correct_delta'],24)
        self.assertLess(Q(r['comparisons'][0]['holm_adjusted_p']),Q(1,20))
    def test_17_literal_boolean_flag_cannot_authenticate_signatures(self):
        self.a['independent_evaluator_verified']=True
        self.a['independent_source_grouping_verified']=True
        self.assertFalse(self.run_gate()['model_promotion_qualified'])
    def test_18_duplicate_held_identifier(self):
        self.a['source_inventory'][1]['case_id']=self.a['source_inventory'][0]['case_id']
        self.refuse()
    def test_19_removed_held_label(self):
        self.a['held_labels'].pop(next(iter(self.a['held_labels'])))
        self.refuse()
    def test_20_added_held_label(self):
        self.a['held_labels']['outside']=1
        self.refuse()
    def test_21_unknown_prediction_case(self):
        self.a['blind_prediction_seal']['rows'][0]['case_id']='foreign'
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        self.refuse()
    def test_22_missing_candidate_output(self):
        del self.a['blind_prediction_seal']['rows'][0]['arms']['ndu_discrete']
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        self.refuse()
    def test_23_extra_candidate_output(self):
        self.a['blind_prediction_seal']['rows'][0]['arms']['unregistered']=1
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        self.refuse()
    def test_24_tampered_prediction_seal(self):
        self.a['blind_prediction_seal']['rows'][0]['arms']['ndu_discrete']=0
        self.refuse()
    def test_25_genuine_label_in_worker_seal(self):
        self.a['blind_prediction_seal']['labels_present']=True;self.refuse()
    def test_26_scored_outcome_in_worker_seal(self):
        self.a['blind_prediction_seal']['score_present']=True;self.refuse()
    def test_27_invalid_task_labels(self):
        self.a['held_labels'][next(iter(self.a['held_labels']))]=True;self.refuse()
    def test_28_missing_cost_phase_fails(self):
        self.a['invoices']['ndu_discrete'].pop('verifier');self.refuse()
    def test_29_extra_cost_phase_fails(self):
        self.a['invoices']['ndu_discrete']['magical_free_work']=0;self.refuse()
    def test_30_negative_cost_fails(self):
        self.a['invoices']['ndu_discrete']['training']=-1;self.refuse()
    def test_31_boolean_cost_fails(self):
        self.a['invoices']['ndu_discrete']['training']=False;self.refuse()
    def test_32_unknown_cost_never_becomes_free(self):
        self.a['invoices']['ndu_discrete']['training']=None
        r=self.run_gate();self.assertIsNone(r['comparisons'][0]['cost_delta_ns'])
        self.assertFalse(r['cost_complete'])
    def test_33_missing_cheap_control(self):
        self.a['controls'].remove('fixed8');self.refuse()
    def test_34_wrong_external_objective(self):
        self.a['objective']='model_self_score';self.refuse()
    def test_35_independent_family_unreported(self):
        self.a['source_inventory'][0].pop('source_family');self.refuse()
    def test_36_future_window_unreported(self):
        self.a['source_inventory'][0].pop('window');self.refuse()
    def test_37_source_digest_unbound(self):
        self.a['source_inventory'][0]['source_digest']='0'*63;self.refuse()
    def test_38_protocol_not_frozen(self):
        self.a['protocol']['candidate_frozen_before_evaluation']=False;self.refuse()
    def test_39_population_is_single_group_not_24_sources(self):
        for r in self.a['source_inventory']:r['source_family']='one-source'
        self.a['protocol']['source_manifest_digest']=digest(self.a['source_inventory'])
        res=self.run_gate();self.assertEqual(res['declared_source_family_count'],1)
        self.assertIn('fewer_than_20_independent_source_family_candidates',res['blockers'])
    def test_40_same_calendar_window_not_future_evidence(self):
        for r in self.a['source_inventory']:r['window']='same-old-day'
        self.a['protocol']['source_manifest_digest']=digest(self.a['source_inventory'])
        res=self.run_gate();self.assertEqual(res['declared_time_window_count'],1)
        self.assertIn('fewer_than_3_distinct_time_windows',res['blockers'])
    def test_41_fake_repeated_record_cannot_multiply_sample(self):
        self.a['source_inventory'].append(copy.deepcopy(self.a['source_inventory'][0]));self.refuse()
    def test_42_no_delta_means_no_significance(self):
        for r in self.a['blind_prediction_seal']['rows']:
            r['arms']['ndu_discrete']=r['arms']['fixed8']
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        r=self.run_gate();self.assertEqual(r['comparisons'][0]['holm_adjusted_p'],'1')
        self.assertIn('no_positive_multiplicity_corrected_paired_task_evidence',r['blockers'])
    def test_43_cost_not_observer_attested_even_when_complete(self):
        r=self.run_gate();self.assertTrue(r['cost_complete'])
        self.assertIn('full_cost_source_only_not_independently_authenticated',r['blockers'])
    def test_44_invalid_future_input_disposition(self):
        self.a['posture']='FINAL_USE_ALLOWED';self.refuse()
    def test_45_false_production_promotion_refused(self):
        self.a['production_accepted']=True;self.refuse()
    def test_46_missing_blind_rows(self):
        self.a['blind_prediction_seal']['rows'].pop();self.refuse()
    def test_47_wrong_blind_schema(self):
        self.a['blind_prediction_seal']['schema']='v0';self.refuse()
    def test_49_resealed_wrong_source_manifest(self):
        self.a['protocol']['source_manifest_digest']='0'*64
        self.refuse()
    def test_50_missing_registered_encoder_identity(self):
        self.a['protocol']['shared_encoder_digest']='0'*63
        self.refuse()
    def test_51_hidden_truth_embedded_in_input_inventory(self):
        self.a['source_inventory'][0]['label']=1
        self.refuse()
    def test_52_hidden_truth_embedded_in_prediction(self):
        self.a['blind_prediction_seal']['rows'][0]['correct']=True
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        self.refuse()
    def test_48_all_losses_not_significant(self):
        for r in self.a['blind_prediction_seal']['rows']:
            r['arms']['ndu_discrete']=0;r['arms']['fixed8']=1;r['arms']['neutral']=1
        self.a['blind_prediction_seal']['digest']=digest(self.a['blind_prediction_seal']['rows'])
        res=self.run_gate();self.assertEqual(res['comparisons'][0]['source_family_losses'],24)
        self.assertIn('no_positive_multiplicity_corrected_paired_task_evidence',res['blockers'])


if __name__=='__main__':unittest.main()
