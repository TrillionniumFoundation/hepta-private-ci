"""Actual trained PyTorch V1 Readers audited on all legitimate MultiRC answers."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from multirc_materials import prepare_panels
from multirc_candidate_slate import prepare_candidate_slate,validate_candidate_slate
from multirc_candidate_audit import (run_slate_audit,score_candidate_slate,load_frozen_readers)
from multirc_reader_study import (train_then_predict,publish,check_seal,ARMS)
from test_multirc_real_study import DummyEncoder,fixture_rows
from next_round_matrix import _digest
from matrix_bank import state_digest
from execution_meter import BudgetStop

class GenuineCandidateSlateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.source=fixture_rows(4,'val')
        cls.train,cls.evaluation,cls.original_labels=prepare_panels(
            fixture_rows(5),cls.source,train_passages=3,val_passages=2,
            dataset_sha256_train='a'*64,dataset_sha256_val='b'*64)
        cls.slate,cls.candidate_labels=prepare_candidate_slate(
            cls.train,cls.evaluation,cls.source,original_label_receipt=cls.original_labels)
        encoder=DummyEncoder()
        cls.owner,cls.banks=train_then_predict(cls.train,lambda:copy.deepcopy(cls.evaluation),
            encoder=encoder,question_encoder=encoder.query,checkpoint_sha256='c'*64,steps=3)
        cls.temp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base=Path(cls.temp.name)
        cls.seal=publish(cls.base/'original',cls.owner,cls.banks)
        cls.reader_copies=load_frozen_readers(cls.base/'original',
                                              check_seal(cls.base/'original',cls.seal['seal_id']))
        cls.encoder=DummyEncoder()
        cls.audit=run_slate_audit(cls.train,cls.evaluation,cls.slate,cls.owner,
            cls.reader_copies,encoder=cls.encoder,question_encoder=cls.encoder.query,
            checkpoint_sha256='c'*64)
        cls.scores=score_candidate_slate(cls.audit,cls.slate,cls.candidate_labels,
            expected_observation_id=cls.audit['observation_id'],
            expected_labels_sha256=_digest(cls.candidate_labels))

    def test_genuine_candidates_count_and_original_anchor_replay(self):
        self.assertTrue(validate_candidate_slate(self.train,self.evaluation,self.slate))
        self.assertEqual(self.audit['question_count'],4)
        self.assertEqual(self.audit['actual_candidate_count'],8)
        self.assertEqual(self.audit['original_v1_anchors_replayed'],4)
        self.assertEqual(self.audit['shared_evidence_encoder_calls'],2)
        self.assertEqual(self.audit['actual_question_encoder_calls'],8)
        self.assertEqual(self.audit['actual_reader_calls'],32)
        self.assertEqual(set(self.audit['predictions']),set(ARMS))
        self.assertEqual(self.audit['additional_work_observation']['unknown_operators'],{})
        self.assertGreater(self.audit['additional_work_observation']['phase_flops']['inference'],0)
        self.assertEqual(len([x for x in self.encoder.calls if x[0]=='evidence']),2)

    def test_only_authentic_same_question_candidates_have_human_labels(self):
        self.assertEqual(self.scores['candidate_count'],8)
        self.assertEqual(self.scores['question_count'],4)
        self.assertEqual(len(self.candidate_labels['labels']),8)
        self.assertTrue(all('label' not in str(entry) for row in self.slate['rows']
                            for q in row['questions'] for entry in q['candidates']))
        for arm in ARMS:
            self.assertEqual(self.scores['results'][arm]['total'],8)
            self.assertEqual(self.scores['results'][arm]['registered_questions'],4)
            self.assertGreaterEqual(self.scores['results'][arm]['complete_question_count'],0)
            self.assertLessEqual(self.scores['results'][arm]['complete_question_count'],4)
        self.assertFalse(self.scores['official_multirc_score_established'])

    def test_label_flip_does_not_change_any_blind_evaluation_input(self):
        flipped=copy.deepcopy(self.source)
        for row in flipped:
            if row['idx']['answer']>0:row['label']=1-row['label']
        flipped.reverse()
        slate,labels=prepare_candidate_slate(self.train,self.evaluation,flipped,
                                             original_label_receipt=self.original_labels)
        self.assertEqual(self.slate,slate)
        self.assertNotEqual(self.candidate_labels['labels'],labels['labels'])

    def test_source_row_order_does_not_change_candidate_panel(self):
        order=copy.deepcopy(self.source)
        order[:]=reversed(order)
        s,l=prepare_candidate_slate(self.train,self.evaluation,order,
                                    original_label_receipt=self.original_labels)
        self.assertEqual(s,self.slate)
        self.assertEqual(l,self.candidate_labels)

    def test_no_candidate_missing_or_capped_slate_without_refusal(self):
        bad=[r for r in self.source if not (r['idx']['paragraph']==0 and r['idx']['answer']==1)]
        # Some selected passage may not be paragraph 0. Remove an answer
        # for whichever first group actually appears in the blind panel.
        chosen={v['evidence'] for v in self.evaluation['rows']}
        target=next(r for r in self.source if r['paragraph'] in chosen and r['idx']['answer']==1)
        bad=[r for r in self.source if not (r['idx']==target['idx'])]
        with self.assertRaises(ValueError):
            prepare_candidate_slate(self.train,self.evaluation,bad,
                original_label_receipt=self.original_labels)
        duplicates=self.source+[copy.deepcopy(self.source[0])]
        if self.source[0]['paragraph'] in chosen:
            with self.assertRaises(ValueError):prepare_candidate_slate(self.train,self.evaluation,duplicates,
                original_label_receipt=self.original_labels)

    def test_corrupt_original_candidate_label_rejected(self):
        bad=copy.deepcopy(self.source)
        text=self.evaluation['rows'][0]['evidence']
        original_answer=self.evaluation['rows'][0]['questions'][0]['answer']
        for row in bad:
            if row['paragraph']==text and row['answer']==original_answer and row['idx']['question']==0:
                row['label']=1-row['label']
        with self.assertRaises(ValueError):prepare_candidate_slate(self.train,self.evaluation,bad,
            original_label_receipt=self.original_labels)

    def test_blind_bundle_rejects_reordered_missing_extra_labels(self):
        for method in ('reorder','missing','label','other_parent','altered_question'):
            slate=copy.deepcopy(self.slate)
            if method=='reorder':slate['rows'].reverse()
            elif method=='missing':slate['rows'][0]['questions'][0]['candidates'].pop()
            elif method=='label':slate['rows'][0]['questions'][0]['candidates'][0]['label']=1
            elif method=='other_parent':slate['source_panel_id']='d'*64
            else:slate['rows'][0]['questions'][0]['question']='not original'
            slate['slate_id']=_digest({k:v for k,v in slate.items() if k!='slate_id'})
            with self.subTest(method=method),self.assertRaises(ValueError):
                validate_candidate_slate(self.train,self.evaluation,slate)

    def test_train_owner_weights_are_unchanged_by_blind_audit(self):
        copied={key:state_digest(m) for key,m in self.reader_copies.items()}
        enc=DummyEncoder()
        new=run_slate_audit(self.train,self.evaluation,self.slate,self.owner,self.reader_copies,
            encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64)
        self.assertEqual(new['predictions'],self.audit['predictions'])
        self.assertEqual(copied,{key:state_digest(m) for key,m in self.reader_copies.items()})
        self.assertFalse(new['evaluation_labels_loaded'])

    def test_original_prediction_mutation_is_refused(self):
        bad=copy.deepcopy(self.owner)
        bad['predictions']['conditioned'][0]['logits'][0]+=.125
        bad['observation_id']=_digest({k:v for k,v in bad.items() if k!='observation_id'})
        with self.assertRaises(ValueError):run_slate_audit(self.train,self.evaluation,self.slate,bad,
            self.reader_copies,encoder=DummyEncoder(),question_encoder=DummyEncoder().query,
            checkpoint_sha256='c'*64)

    def test_wrong_trained_weight_or_wrong_snapshot_rejected(self):
        for how in ('weight','snapshot'):
            bad=copy.deepcopy(self.owner)
            if how=='weight':bad['training']['conditioned']['weights_sha256']='f'*64
            else:bad['model_snapshot_sha256']='f'*64
            bad['observation_id']=_digest({k:v for k,v in bad.items() if k!='observation_id'})
            with self.subTest(how=how),self.assertRaises(ValueError):run_slate_audit(
                self.train,self.evaluation,self.slate,bad,self.reader_copies,
                encoder=DummyEncoder(),question_encoder=DummyEncoder().query,checkpoint_sha256='c'*64)

    def test_unknown_operators_fail_closed_and_do_not_publish_complete_cost(self):
        class Unknown(DummyEncoder):
            def query(self,text):
                return torch.atan(super().query(text))
        encoder=Unknown()
        with self.assertRaises(Exception):run_slate_audit(
            self.train,self.evaluation,self.slate,self.owner,self.reader_copies,
            encoder=encoder,question_encoder=encoder.query,checkpoint_sha256='c'*64)

    def test_actual_extra_feature_storage_cap_terminates(self):
        class BackedStorage(DummyEncoder):
            def __call__(self,text):
                super().__call__(text)
                return torch.zeros(2048,dtype=torch.float32)[:12].reshape(3,4)
        encoder=BackedStorage()
        with self.assertRaisesRegex(ValueError,'budget exceeded'):
            run_slate_audit(self.train,self.evaluation,self.slate,self.owner,self.reader_copies,
                encoder=encoder,question_encoder=encoder.query,checkpoint_sha256='c'*64,
                max_feature_bytes=1024)

    def test_sealed_scoring_rejects_missing_wrong_labels_and_modified_logits(self):
        for how in ('missing','nonboolean','wrong_slate','wrong_prediction'):
            obs=copy.deepcopy(self.audit)
            labels=copy.deepcopy(self.candidate_labels)
            if how=='missing':labels['labels'].pop(next(iter(labels['labels'])))
            if how=='nonboolean':labels['labels'][next(iter(labels['labels']))]=True
            if how=='wrong_slate':labels['slate_id']='e'*64
            if how=='wrong_prediction':obs['predictions']['conditioned'][0]['logits'][0]+=.1
            with self.subTest(how=how),self.assertRaises(ValueError):score_candidate_slate(
                obs,self.slate,labels,expected_observation_id=self.audit['observation_id'],
                expected_labels_sha256=_digest(labels))

    def test_actual_paired_outcomes_preserve_every_candidate(self):
        for ctrl,p in self.scores['paired'].items():
            self.assertEqual(p['recovered']+p['lost']+p['other_outcomes'],8)
            self.assertEqual(p['recovered']-p['lost'],
                             self.scores['results']['conditioned']['correct']-
                             self.scores['results'][ctrl]['correct'])
        self.assertTrue(self.scores['original_v1_training_unchanged'])
        self.assertFalse(self.scores['independent_test_quality_established'])

    def test_external_labels_never_trigger_training(self):
        alternate=copy.deepcopy(self.candidate_labels)
        for key in alternate['labels']:alternate['labels'][key]=1-alternate['labels'][key]
        with patch('conditional_evidence.fit_reader',side_effect=AssertionError('never retrain')):
            result=score_candidate_slate(self.audit,self.slate,alternate,
                    expected_observation_id=self.audit['observation_id'],
                    expected_labels_sha256=_digest(alternate))
        self.assertNotEqual(self.scores['owner_labels_sha256'],result['owner_labels_sha256'])


if __name__=='__main__':unittest.main()
