"""Original human label-owner E23 acceptance: NEVER run inside a blind model job."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from e14_multirc_route import read_prelabel
from e21_whole_question import once
from e22_e16_question_gate import blind_e22, ALL
from e22_independent_human_score import question_metrics
from e23_original_owner_question_gate import (
    audit, original_owner_labels, original_human_score_receipts,
    check_e16_true_label_parameter_replay, E15_OWNERS, E16_OWNERS,
)
from e21_whole_question import E15_SCORES
from e22_independent_human_score import E16_SCORES


def inputs():
    def required(key):
        path=os.environ.get(key)
        if not path or not Path(path).is_file():
            raise RuntimeError(f'original public E23 evidence path missing: {key}')
        return path
    return dict(original=required('HEPTA_E23_ORIGINAL'),
      blind=required('HEPTA_E23_BLIND'),
      e15=[required(f'HEPTA_E23_E15_FOLD_{i}') for i in range(4)],
      e16=[required(f'HEPTA_E23_E16_FOLD_{i}') for i in range(4)],
      e15_owners=[required(f'HEPTA_E23_E15_OWNER_{i}') for i in range(4)],
      e16_owners=[required(f'HEPTA_E23_E16_OWNER_{i}') for i in range(4)],
      e15_scores=[required(f'HEPTA_E23_E15_SCORE_{x}') for x in ('SOURCE','MERGE')],
      e16_scores=[required(f'HEPTA_E23_E16_SCORE_{x}') for x in ('SOURCE','MERGE')])


class OriginalHumanTwoOwner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=inputs()
        cls.observation=read_prelabel(cls.ctx['original'])
        cls.out=audit(cls.ctx['original'],cls.ctx['e15'],cls.ctx['e16'],
                      cls.ctx['blind'],cls.ctx['e15_owners'],cls.ctx['e16_owners'],
                      cls.ctx['e15_scores'],cls.ctx['e16_scores'])
        cls.a,cls.a_evidence=original_owner_labels(cls.observation,cls.ctx['e15_owners'],E15_OWNERS,name='E15')
        cls.b,cls.b_evidence=original_owner_labels(cls.observation,cls.ctx['e16_owners'],E16_OWNERS,name='E16')

    def test_01_two_original_human_label_owners_agree_on_complete_set(self):
        self.assertEqual(self.a,self.b)
        self.assertEqual(len(self.a),33)
        self.assertEqual({i for i in self.a},{r['task_id'] for r in self.observation['rows']})

    def test_02_every_original_label_appears_in_three_train_only_views(self):
        self.assertTrue(self.a_evidence['each_label_has_three_consistent_training_only_views'])
        self.assertTrue(self.b_evidence['each_label_has_three_consistent_training_only_views'])

    def test_03_two_original_CI_source_provenance_limited(self):
        self.assertTrue(self.out['original_owner_artifact_sets_do_not_prove_independent_human_adjudication'])
        self.assertFalse(self.out['original_human_source_parquet_re_downloaded_in_this_run'])
        self.assertTrue(self.out['original_process_label_isolation_not_cryptographic_secrecy'])
        self.assertEqual(self.out['original_source_families'],1)

    def test_04_all_eight_policies_have_zero_complete_original_questions(self):
        self.assertEqual(self.out['every_method_complete_question_count'],{arm:0 for arm in ALL})
        self.assertFalse(self.out['actual_original_human_full_questions_success_by_any_registered_method'])

    def test_05_candidate_gain_not_question_gain(self):
        delta=self.out['e16_scaled_vs_frozen_mean_pool']
        self.assertEqual(delta['candidate_correct_delta'],3)
        self.assertEqual(delta['complete_question_delta'],0)
        self.assertEqual(sorted(delta['passage_correct_deltas']),[0,0,0,3])

    def test_06_four_group_signflip_is_descriptive_nonconfirmatory(self):
        d=self.out['e16_scaled_vs_frozen_mean_pool']
        self.assertEqual(d['four_passage_exact_signflip_p_descriptive_only'],1.0)
        self.assertIsNone(d['prospective_multi_hypothesis_p_value'])

    def test_07_existing_frozen_and_E15_real_human_metrics(self):
        r=self.out['eight_strategy_original_human_question_metrics']
        self.assertEqual(r['conditioned']['correct'],16)
        self.assertEqual(r['mean_pool_query_fused']['correct'],17)
        self.assertEqual(r['learned_linear_5']['correct'],17)
        self.assertEqual(r['learned_gated_3']['correct'],16)

    def test_08_existing_E16_original_human_metrics(self):
        r=self.out['eight_strategy_original_human_question_metrics']
        self.assertEqual(r['centered_raw_5']['correct'],13)
        self.assertEqual(r['centered_scaled_5']['correct'],20)
        self.assertAlmostEqual(r['centered_scaled_5']['brier'],.4679101347990239,places=11)

    def test_09_retrain_48_step_sgd_on_true_original_group_training(self):
        self.assertTrue(self.out['e16_original_three_group_label_independent_sgd_replay']
                        ['four_real_training_folds_independently_recomputed'])

    def test_10_original_E15_E16_both_external_score_profiles_are_verifiable(self):
        self.assertEqual(len(self.out['both_original_e15_score_sha256s']),2)
        self.assertEqual(len(self.out['both_original_e16_score_sha256s']),2)
        self.assertNotEqual(self.out['both_original_e15_score_sha256s'][0],
                            self.out['both_original_e15_score_sha256s'][1])

    def test_11_source_prediction_swapping_rejected_even_with_new_local_seal(self):
        value=json.loads(Path(self.ctx['blind']).read_text())
        value['rows'][0]['probs']['centered_scaled_5']+=.05
        with TemporaryDirectory() as d:
            p=Path(d)/'mutated-blind.json'
            once(str(p),value)
            with self.assertRaisesRegex(ValueError,'blind prediction changed'):
                audit(self.ctx['original'],self.ctx['e15'],self.ctx['e16'],str(p),
                      self.ctx['e15_owners'],self.ctx['e16_owners'],
                      self.ctx['e15_scores'],self.ctx['e16_scores'])

    def test_12_source_label_owner_source_bytes_tamper_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'altered-owner.zip'
            p.write_bytes(Path(self.ctx['e15_owners'][0]).read_bytes()+b'x')
            changed=[str(p)]+self.ctx['e15_owners'][1:]
            with self.assertRaises(ValueError):
                original_owner_labels(self.observation,changed,E15_OWNERS,name='wrong')

    def test_13_original_two_score_receipts_missing_rejected(self):
        with self.assertRaises(ValueError):
            audit(self.ctx['original'],self.ctx['e15'],self.ctx['e16'],self.ctx['blind'],
                  self.ctx['e15_owners'],self.ctx['e16_owners'],
                  self.ctx['e15_scores'][:1],self.ctx['e16_scores'])

    def test_14_original_question_denominator_cannot_be_faked(self):
        x=json.loads(Path(self.ctx['blind']).read_text());x['rows'].pop()
        with self.assertRaises(ValueError):question_metrics(x,self.a)

    def test_15_disjoint_training_and_held_identity_is_required(self):
        bad=self.ctx['e16_owners'][:]
        bad[2]=bad[1]
        with self.assertRaises(ValueError):original_owner_labels(self.observation,bad,E16_OWNERS,name='duplicate')

    def test_16_bogus_promotion_authority_cannot_be_scored(self):
        b=json.loads(Path(self.ctx['blind']).read_text());b['production_accepted']=True
        with self.assertRaises(ValueError):question_metrics(b,self.a)

    def test_17_bad_wrong_source_model_requires_original(self):
        with self.assertRaises((ValueError,FileNotFoundError)):
            audit('/tmp/nonexistent-e23-model-source.zip',self.ctx['e15'],self.ctx['e16'],
                  self.ctx['blind'],self.ctx['e15_owners'],self.ctx['e16_owners'],
                  self.ctx['e15_scores'],self.ctx['e16_scores'])

    def test_18_no_authorized_system2_or_real_future_claim(self):
        self.assertEqual(self.out['authority'],'DENY_ALL')
        for key in ('production_accepted','model_selected','system2_fbsde_admitted',
                    'cost_adjusted_task_improvement_established',
                    'whole_service_costs_independently_measured',
                    'independent_future_generation_gains_established'):
            self.assertIs(self.out[key],False)

if __name__ == '__main__':unittest.main()
