"""Authentic pinned E15/E16/ModernBERT MultiRC 4-fold training and reviewer tests.

All model input and owner ZIPs are actual original archived success artifacts.
No fixture fallback. Original validation parquet is NOT opened by this test.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import e24_pairwise_reader as train
import e24_independent_review as review


def paths():
    keys=['HEPTA_E24_MODEL', 'HEPTA_E24_PRELABEL']
    keys += [f'HEPTA_E24_E15_OWNER_{i}' for i in range(4)]
    keys += [f'HEPTA_E24_E16_OWNER_{i}' for i in range(4)]
    keys += [f'HEPTA_E24_E15_SCORE_{i}' for i in range(2)]
    keys += [f'HEPTA_E24_E16_SCORE_{i}' for i in range(2)]
    for k in keys:
        if not os.environ.get(k) or not Path(os.environ[k]).is_file():
            raise RuntimeError(f'NO SYNTHETIC FALLBACK: missing genuine original artifact {k}')
    return {k:os.environ[k] for k in keys}


class ActualOriginalFoldExperiments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=paths()
        cls.rows,cls.groups,cls.observation_sha=train.model(cls.p['HEPTA_E24_MODEL'])
        cls.score=review.score(cls.p['HEPTA_E24_MODEL'],cls.p['HEPTA_E24_PRELABEL'],
            [cls.p[f'HEPTA_E24_E16_OWNER_{i}'] for i in range(4)],
            [cls.p[f'HEPTA_E24_E15_SCORE_{i}'] for i in range(2)],
            [cls.p[f'HEPTA_E24_E16_SCORE_{i}'] for i in range(2)])

    def independent_score(self,prelabel):
        return review.score(self.p['HEPTA_E24_MODEL'],prelabel,
            [self.p[f'HEPTA_E24_E16_OWNER_{i}'] for i in range(4)],
            [self.p[f'HEPTA_E24_E15_SCORE_{i}'] for i in range(2)],
            [self.p[f'HEPTA_E24_E16_SCORE_{i}'] for i in range(2)])

    def test_01_original_source_has_real_answer_alternatives(self):
        self.assertEqual(len(self.rows),33)
        self.assertEqual(len(self.groups),4)
        self.assertEqual(len({(r['source_group'],r['question_slot']) for r in self.rows}),8)

    def test_02_training_only_three_passages_per_fold(self):
        for fold in range(4):
            labels,_=train.training_labels(self.p[f'HEPTA_E24_E15_OWNER_{fold}'],fold,
                self.rows,self.groups)
            self.assertEqual(len(labels),sum(r['source_group']!=self.groups[fold]
                                              for r in self.rows))
            self.assertTrue(all(r['task_id'] not in labels for r in self.rows
                                if r['source_group']==self.groups[fold]))

    def test_03_original_per_fold_80_step_sgd_and_training_cost(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        self.assertEqual(len(x['folds']),4)
        for fold,entry in enumerate(x['folds']):
            self.assertEqual(entry['fold'],fold)
            self.assertFalse(entry['held_label_accessed'])
            self.assertEqual(entry['training_updates_per_method'],80)
            for arm in train.METHODS:
                self.assertEqual(entry['methods'][arm]['meters']['train_steps'],80)
                self.assertGreater(entry['methods'][arm]['meters']['train_cpu_ns'],0)

    def test_04_independent_numpy_80_update_replay_and_probabilities(self):
        self.assertEqual(self.score['original_real_5param_SGD_updates'],640)
        self.assertEqual(set(self.score['results']),{
            'bce5','pairwise5','frozen_meanpool','without_conditioned_center',
            'without_meanpool_center','without_no_evidence_center',
            'without_meanpool_raw'})

    def test_05_original_human_candidate_and_whole_question_result(self):
        r=self.score['results']
        self.assertEqual((r['frozen_meanpool']['correct'],r['frozen_meanpool']['complete_questions']),(17,0))
        self.assertEqual((r['bce5']['correct'],r['bce5']['complete_questions']),(21,2))
        self.assertEqual((r['pairwise5']['correct'],r['pairwise5']['complete_questions']),(23,3))
        self.assertEqual(r['pairwise5']['complete_passages'],0)

    def test_06_hist_E16_scored_result_is_retained_control(self):
        self.assertEqual(self.score['historical_e16_scaled_correct'],20)
        self.assertAlmostEqual(self.score['historical_e16_scaled_brier'],.4679101347990239,places=10)

    def test_07_original_absence_of_natural_future_and_NDU_promotions(self):
        for x in ('source_group_independence_certified','future_task_utility_gain_established',
                  'equal_full_lifecycle_compute','reader_sufficient','ndu_system2_admitted',
                  'model_selected','production_accepted','original_pretraining_reexecuted'):
            self.assertIs(self.score[x],False)
        self.assertEqual(self.score['authority_posture'],'DENY_ALL')

    def test_08_channel_masking_is_not_physical_evidence_removal(self):
        self.assertIs(self.score['channel_mask_counterfactual_reencodes_evidence'],False)
        self.assertIs(self.score['channel_mask_arms_are_exploratory_posthoc'],True)
        self.assertEqual(self.score['results']['without_no_evidence_center']['correct'],23)
        self.assertEqual(self.score['results']['without_meanpool_center']['complete_questions'],1)

    def test_09_changed_trained_weights_denied(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        x['folds'][0]['methods']['pairwise5']['weights'][2]+=.04
        with TemporaryDirectory() as d:
            file=Path(d)/'changed.json';file.write_text(json.dumps(x))
            with self.assertRaises(review.Denied):self.independent_score(str(file))

    def test_10_changed_held_probability_denied(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        x['folds'][0]['methods']['bce5']['predictions'][0]['probability']+=.02
        with TemporaryDirectory() as d:
            file=Path(d)/'changed.json';file.write_text(json.dumps(x))
            with self.assertRaises(review.Denied):self.independent_score(str(file))

    def test_11_changed_training_normalizer_denied(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        x['folds'][0]['train_feature_profile']['center_rms_train'][1]*=2
        with TemporaryDirectory() as d:
            file=Path(d)/'changed.json';file.write_text(json.dumps(x))
            with self.assertRaises(review.Denied):self.independent_score(str(file))

    def test_12_misrepresented_pretrained_calls_denied(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        x['folds'][0]['new_pretrained_forward_calls']=4
        with TemporaryDirectory() as d:
            file=Path(d)/'changed.json';file.write_text(json.dumps(x))
            with self.assertRaises(review.Denied):self.independent_score(str(file))

    def test_13_missing_original_owner_fails_closed(self):
        with self.assertRaises((review.Denied,FileNotFoundError)):
            review.independent_original_labels(
                review.frozen_inputs(self.p['HEPTA_E24_MODEL'])[0],self.groups,
                [self.p[f'HEPTA_E24_E16_OWNER_{i}'] for i in range(3)])

    def test_14_original_model_zip_append_tamper_denied(self):
        with TemporaryDirectory() as d:
            file=Path(d)/'tamper.zip'
            file.write_bytes(Path(self.p['HEPTA_E24_MODEL']).read_bytes()+b'evil')
            with self.assertRaises(train.Denied):train.model(file)

    def test_15_training_wrong_source_owner_fold_denied(self):
        with self.assertRaises(train.Denied):
            train.training_labels(self.p['HEPTA_E24_E15_OWNER_1'],0,self.rows,self.groups)

    def test_16_join_cannot_duplicate_original_held_fold(self):
        with TemporaryDirectory() as d:
            p=Path(d)
            for i in range(4):
                train.fit_one(self.p['HEPTA_E24_MODEL'],self.p[f'HEPTA_E24_E15_OWNER_{i}'],i,p/f'{i}.json')
            with self.assertRaises(train.Denied):
                train.join(self.p['HEPTA_E24_MODEL'],[p/'0.json',p/'1.json',p/'1.json',p/'3.json'],p/'all.json')

    def test_17_label_free_phase_no_raw_human_targets(self):
        x=json.loads(Path(self.p['HEPTA_E24_PRELABEL']).read_text())
        self.assertIs(x['held_human_labels_accessed'],False)
        self.assertEqual(x['new_pretrained_forwards'],0)
        for fold in x['folds']:
            for method in train.METHODS:
                for p in fold['methods'][method]['predictions']:
                    self.assertEqual(set(p),{'task_id','probability'})

    def test_18_create_once_prevents_forged_overwrite(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'out.json'
            train.sealed(path,{'authority':'DENY_ALL'})
            with self.assertRaises(FileExistsError):train.sealed(path,{'authority':'DENY_ALL'})

if __name__=='__main__':unittest.main()
