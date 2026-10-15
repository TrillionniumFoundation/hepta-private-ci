"""Actually trained PyTorch Readers on authentic candidate alternatives, not fabricated labels."""
import copy
import unittest
from unittest.mock import patch

import torch

from multirc_native_training import (prepare_train_slate,validate_train_slate,
                                     fit_and_evaluate,score_native_training,ARM_KEYS,
                                     READOUTS)
from multirc_materials import prepare_panels
from multirc_candidate_slate import prepare_candidate_slate
from test_multirc_real_study import fixture_rows,DummyEncoder
from next_round_matrix import _digest
from matrix_bank import state_digest


class NativeTrainingContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.train_rows=fixture_rows(7)
        cls.val_rows=fixture_rows(5,'val')
        cls.train,cls.eval,labels=prepare_panels(cls.train_rows,cls.val_rows,
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64,
            train_passages=3,val_passages=2)
        cls.test_slate,cls.labels=prepare_candidate_slate(cls.train,cls.eval,
            cls.val_rows,original_label_receipt=labels)
        cls.train_slate=prepare_train_slate(cls.train,cls.train_rows)
        cls.encoder=DummyEncoder()
        cls.obs,cls.models=fit_and_evaluate(cls.train,cls.train_slate,
            lambda:(copy.deepcopy(cls.eval),copy.deepcopy(cls.test_slate)),
            encoder=cls.encoder,question_encoder=cls.encoder.query,checkpoint_sha256='c'*64,
            steps=4)
        cls.scores=score_native_training(cls.obs,cls.test_slate,cls.labels,
            expected_observation_id=cls.obs['observation_id'],
            expected_label_digest=_digest(cls.labels))

    def test_all_authentic_train_answers_included_without_test_labels(self):
        slate=self.train_slate
        self.assertTrue(validate_train_slate(self.train,slate))
        self.assertEqual(slate['selected_passage_count'],3)
        self.assertEqual(slate['candidate_count'],12)
        self.assertEqual(slate['original_training_candidate_count'],6)
        self.assertEqual({c['label'] for r in slate['rows'] for q in r['questions'] for c in q['candidates']},{0,1})
        self.assertNotEqual(slate['material_id'],self.test_slate['slate_id'])
        self.assertTrue(all('label' not in str(q) for r in self.test_slate['rows'] for q in r['questions']))

    def test_four_real_fits_same_parameters_steps_but_unequal_exposures(self):
        self.assertEqual(set(self.obs['training']),set(ARM_KEYS))
        self.assertEqual({x['parameter_count'] for x in self.obs['training'].values()},{42})
        self.assertEqual({x['steps'] for x in self.obs['training'].values()},{4})
        self.assertEqual({x['case_count'] for k,x in self.obs['training'].items() if k.startswith('first_')},{6})
        self.assertEqual({x['case_count'] for k,x in self.obs['training'].items() if k.startswith('all_native_')},{12})
        self.assertTrue(all(x['observed_training_aten_formula_flops']>0 for x in self.obs['training'].values()))
        self.assertFalse(self.obs['full_system_compute_parity_established'])

    def test_source_encoder_reused_and_all_queries_charged(self):
        self.assertEqual(self.obs['shared_train_encoder_calls'],3)
        self.assertEqual(self.obs['shared_eval_encoder_calls'],2)
        self.assertEqual(self.obs['train_question_encoder_calls'],12)
        self.assertEqual(self.obs['eval_question_encoder_calls'],8)
        self.assertEqual(len([c for c in self.encoder.calls if c[0]=='evidence']),5)
        self.assertEqual(len([c for c in self.encoder.calls if c[0]=='query']),20)
        self.assertEqual(len({state_digest(m) for m in self.models.values()})>=1,True)

    def test_true_native_eval_all_fitted_predictions_and_paired_denominator(self):
        self.assertEqual(set(self.scores['results']),set(ARM_KEYS))
        for row in self.scores['results'].values():
            self.assertEqual(row['total'],8)
            self.assertEqual(row['question_count'],4)
        for row in self.scores['paired_update_matched'].values():
            self.assertEqual(row['descriptive_accuracy_delta'],
                             (row['all_native_recovered']-row['all_native_lost'])/8)
        self.assertFalse(self.scores['training_all_native_superiority_established'])
        self.assertFalse(self.scores['model_selected'])

    def test_future_eval_loader_is_called_only_after_four_fit_endpoints(self):
        import multirc_native_training as study
        real=study.fit_reader
        encoder=DummyEncoder()
        events=[]
        def fit(*args,**kwargs):
            events.append('fit')
            return real(*args,**kwargs)
        def load():
            events.append('evaluation')
            return self.eval,self.test_slate
        with patch.object(study,'fit_reader',side_effect=fit):
            study.fit_and_evaluate(self.train,self.train_slate,load,
                encoder=encoder,question_encoder=encoder.query,checkpoint_sha256='c'*64,steps=1)
        self.assertEqual(events,['fit']*4+['evaluation'])

    def test_training_order_and_first_canonical_candidate_do_not_change(self):
        shuffled=copy.deepcopy(self.train_rows)
        shuffled.reverse()
        self.assertEqual(self.train_slate,prepare_train_slate(self.train,shuffled))
        anchor=[(q['original_task_id'],q['candidates'][0]['task_id'])
                for r in self.train_slate['rows'] for q in r['questions']]
        self.assertTrue(all(a==b for a,b in anchor))

    def test_extra_train_label_flip_changes_target_not_selection_or_eval(self):
        swapped=copy.deepcopy(self.train_rows)
        for row in swapped:
            if row['idx']['answer']>0:row['label']=1-row['label']
        different=prepare_train_slate(self.train,swapped)
        self.assertEqual([r['source_group'] for r in different['rows']],
                         [r['source_group'] for r in self.train_slate['rows']])
        self.assertNotEqual(different['material_id'],self.train_slate['material_id'])
        self.assertEqual([[(q['original_task_id'],[c['task_id'] for c in q['candidates']]) for q in r['questions']] for r in different['rows']],
                         [[(q['original_task_id'],[c['task_id'] for c in q['candidates']]) for q in r['questions']] for r in self.train_slate['rows']])

    def test_missing_real_alternative_cannot_train_on_partial_slate(self):
        corrupted=copy.deepcopy(self.train_rows)
        target=next(row for row in corrupted if row['paragraph'] == self.train['rows'][0]['evidence'] and row['idx']['answer']==1)
        corrupted.remove(target)
        with self.assertRaises(ValueError):prepare_train_slate(self.train,corrupted)

    def test_train_bundle_identity_and_candidate_order_fail_closed(self):
        for defect in ('id','missing','label','order','owner'):
            altered=copy.deepcopy(self.train_slate)
            if defect=='id':altered['rows'][0]['questions'][0]['candidates'][0]['task_id']='x'
            elif defect=='missing':altered['rows'][0]['questions'][0]['candidates'].pop()
            elif defect=='label':altered['rows'][0]['questions'][0]['candidates'][0]['label']=True
            elif defect=='order':altered['rows'][0]['questions'][0]['candidates'].reverse()
            elif defect=='owner':altered['source_panel_id']='f'*64
            altered['material_id']=_digest({k:v for k,v in altered.items() if k!='material_id'})
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                validate_train_slate(self.train,altered)

    def test_first_candidate_controls_exactly_replay_predecessor_v1_reader_weights(self):
        from multirc_reader_study import train_then_predict
        predecessor_encoder=DummyEncoder()
        original,original_models=train_then_predict(self.train,lambda:copy.deepcopy(self.eval),
            encoder=predecessor_encoder,question_encoder=predecessor_encoder.query,
            checkpoint_sha256='c'*64,seed=7347,steps=4)
        for readout in READOUTS:
            with self.subTest(readout=readout):
                self.assertEqual(state_digest(original_models[readout]),
                                 state_digest(self.models['first_'+readout]))
                self.assertEqual(original['training'][readout]['weights_sha256'],
                                 self.obs['training']['first_'+readout]['weights_sha256'])

    def test_no_real_holdout_labels_accepted_in_source_eval_loader(self):
        bad=copy.deepcopy(self.test_slate)
        bad['rows'][0]['questions'][0]['candidates'][0]['label']=1
        with self.assertRaises(ValueError):fit_and_evaluate(self.train,self.train_slate,
            lambda:(self.eval,bad),encoder=DummyEncoder(),question_encoder=DummyEncoder().query,
            checkpoint_sha256='c'*64,steps=1)

    def test_external_eval_label_tampering_and_missing_denominators_refused(self):
        for defect in ('missing','bad_type','wrong_slate','mutated_logits','row_order'):
            labels=copy.deepcopy(self.labels);obs=copy.deepcopy(self.obs)
            if defect=='missing':labels['labels'].pop(next(iter(labels['labels'])))
            elif defect=='bad_type':labels['labels'][next(iter(labels['labels']))]=True
            elif defect=='wrong_slate':labels['slate_id']='f'*64
            elif defect=='mutated_logits':obs['predictions']['first_conditioned'][0]['logits'][0]+=.1
            else:obs['rows'].reverse()
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                score_native_training(obs,self.test_slate,labels,
                    expected_observation_id=self.obs['observation_id'],
                    expected_label_digest=_digest(labels))

    def test_score_separate_labels_recompute_without_retraining(self):
        altered=copy.deepcopy(self.labels)
        altered['labels']={k:1-v for k,v in altered['labels'].items()}
        with patch('multirc_native_training.fit_reader',side_effect=AssertionError('must not train')):
            scores=score_native_training(self.obs,self.test_slate,altered,
                expected_observation_id=self.obs['observation_id'],expected_label_digest=_digest(altered))
        self.assertNotEqual(scores['external_labels_sha256'],self.scores['external_labels_sha256'])

    def test_unmetered_train_query_forbidden_and_no_fake_cost(self):
        class Unknown(DummyEncoder):
            def query(self,text):return torch.atan(super().query(text))
        encoder=Unknown()
        with self.assertRaises(Exception):fit_and_evaluate(self.train,self.train_slate,
            lambda:(self.eval,self.test_slate),encoder=encoder,question_encoder=encoder.query,
            checkpoint_sha256='c'*64,steps=1)

    def test_byte_budget_refuses_before_publishing_model_result(self):
        class LargeEvidence(DummyEncoder):
            def __call__(self,text):
                self.calls.append(('evidence',text,self.trained))
                return torch.ones((64,4),dtype=torch.float32)
        encoder=LargeEvidence()
        with self.assertRaisesRegex(ValueError,'retained native training feature budget'):
            fit_and_evaluate(self.train,self.train_slate,lambda:(self.eval,self.test_slate),
                encoder=encoder,question_encoder=encoder.query,
                checkpoint_sha256='c'*64,steps=1,max_total_feature_bytes=1024)


if __name__=='__main__':unittest.main()
