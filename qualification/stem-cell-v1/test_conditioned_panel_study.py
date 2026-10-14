"""Independent panels, real tensor training, original/missing premise controls."""
import copy
import unittest
from unittest.mock import patch

import torch

from conditioned_panel_study import (ARMS, build_panel, validate_panel,train_panel,
                                     score_panel,remove_premise)
from execution_meter import CONDITIONAL_READER_POLICY_SCHEMA
from next_round_matrix import _digest
from reader_work_v1 import PROFILE

POLICY=dict(schema=CONDITIONAL_READER_POLICY_SCHEMA,arithmetic_profile=PROFILE,
            mode='strict',wall_time_ns=20_000_000_000,
            max_process_rss_bytes=None,rapl_zone=None,rapl_max_power_watts=None)


class ToyEncoder:
    """Two real source-state tensor writes; no label enters either callback."""
    def __init__(self):
        self.calls=0
        self.sources=[]
    def __call__(self,ev):
        self.calls+=1
        self.sources.append(ev)
        import re
        lamp=re.search(r'amber lamp is switched (on|off)',ev.text)
        fan=re.search(r'cobalt fan is (running|stopped)',ev.text)
        a=0. if lamp is None else (1. if lamp.group(1)=='on' else -1.)
        b=0. if fan is None else (1. if fan.group(1)=='running' else -1.)
        return torch.tensor([[1.,0.,a,0.],[0.,1.,b,0.]],dtype=torch.float32)


class ToyQuery:
    def __init__(self):self.calls=0
    def __call__(self,text,options):
        self.calls+=1
        if text.startswith('Is the amber lamp'):return torch.tensor([6.,0.,0.,0.])
        if text.startswith('Is the cobalt fan'):return torch.tensor([0.,6.,0.,0.])
        raise AssertionError('unregistered query')


class ConditionedPanelStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.train,cls.test,cls.labels=build_panel('a'*64,train_groups=4,eval_groups=2)
        cls.encoder=ToyEncoder();cls.query=ToyQuery()
        cls.observation,cls.models=train_panel(cls.train,cls.test,
            evidence_encoder=cls.encoder,query_encoder=cls.query,
            checkpoint_sha256='a'*64,steps=96,seed=7347,policy=POLICY)
        cls.scores=score_panel(cls.observation,cls.labels,
            expected_observation_id=cls.observation['observation_id'],
            expected_labels_sha256=_digest(cls.labels))

    def test_future_evaluation_evidence_not_encoded_before_all_training_finishes(self):
        import conditioned_panel_study as study
        from conditional_evidence import fit_reader as real_fit_reader
        tr,ev,_=build_panel('a'*64,train_groups=2,eval_groups=1)
        encoder=ToyEncoder()
        observations=[]
        def inspected_fit(*args,**kwargs):
            observations.append((len(encoder.sources),
                any(row.available_at_ns>=20 for row in encoder.sources)))
            return real_fit_reader(*args,**kwargs)
        with patch.object(study,'fit_reader',side_effect=inspected_fit):
            study.train_panel(tr,ev,evidence_encoder=encoder,query_encoder=ToyQuery(),
                checkpoint_sha256='a'*64,steps=4,policy=POLICY)
        self.assertEqual(len(observations),4)
        self.assertEqual(observations,[(len(tr),False)]*4)

    def test_all_arms_actually_trained_with_equal_parameter_count(self):
        o=self.observation
        self.assertEqual(set(o['predictions']),set(ARMS))
        self.assertEqual(len(set(o['arm_parameter_counts'].values())),1)
        self.assertTrue(all(v['steps']==96 for v in o['fitting'].values()))
        self.assertTrue(all(v['observed_training_aten_formula_flops']>0 for v in o['fitting'].values()))
        self.assertNotEqual(o['fitting']['mean_pool']['weights_digest'],
                            o['fitting']['conditioned']['weights_digest'])
        self.assertFalse(o['identical_training_flops_claimed'])

    def test_train_eval_only_expose_admitted_source_fields(self):
        self.assertTrue(all(case.targets is None and case.label_observed_ns is None for case in self.test))
        self.assertTrue(all(case.targets is not None for case in self.train))
        self.assertEqual(len(self.labels),len(self.test)*2)
        self.assertFalse(self.observation['final_labels_read_during_training'])

    def test_real_encoder_executed_once_per_document_plus_separately_charged_ablations(self):
        n=len(self.train)+len(self.test)
        self.assertEqual(self.observation['encoder_calls'],n)
        self.assertEqual(self.observation['ablation_encoder_calls'],2*len(self.test))
        self.assertEqual(self.encoder.calls,n+2*len(self.test))
        self.assertEqual(self.query.calls,2*n)
        self.assertTrue(all(r['task_id'] in self.labels for r in self.observation['ablation_predictions']))
        self.assertEqual(self.observation['ablation_work']['unknown_operators'],{})

    def test_all_four_hypotheses_scored_without_automatic_winner(self):
        r=self.scores
        self.assertEqual(set(r['results']),set(ARMS))
        for arm in ARMS:
            self.assertEqual(r['results'][arm]['total'],16)
            self.assertEqual(r['results'][arm]['group_count'],2)
            self.assertIsNone(r['evidence_removal_sensitivity']['actual_missing_premise_answer_accuracy'])
        self.assertFalse(r['condition_reading_winner_selected'])
        self.assertFalse(r['real_world_qa_established'])

    def test_readout_uses_evidence_on_toy_balanced_labels(self):
        # Mechanism sufficiency on one synthetic distribution ONLY.
        self.assertGreaterEqual(self.scores['results']['conditioned']['correct'],10)
        self.assertLessEqual(self.scores['results']['no_evidence']['correct'],10)

    def test_ablations_have_different_evidence_and_no_imputed_ground_truth(self):
        original=self.test[0].evidence.text
        for side in (0,1):
            ablated=remove_premise(original,side)
            self.assertNotEqual(original,ablated)
            self.assertIn('not provided',ablated)
        self.assertGreaterEqual(self.scores['evidence_removal_sensitivity']['relevant_premise_probability_shift'],0)
        with self.assertRaises(ValueError):remove_premise(original,2)
        with self.assertRaises(ValueError):remove_premise('no premises here',0)

    def test_heldout_labels_not_in_training_api(self):
        altered={k:1-v for k,v in self.labels.items()}
        with patch('conditional_evidence.fit_reader',side_effect=AssertionError('must not re-train')):
            rescored=score_panel(self.observation,altered,
                    expected_observation_id=self.observation['observation_id'],
                    expected_labels_sha256=_digest(altered))
        self.assertNotEqual(self.scores['labels_sha256'],rescored['labels_sha256'])
        self.assertEqual(self.scores['results']['conditioned']['total'],
                         rescored['results']['conditioned']['total'])

    def test_wrong_external_seal_or_label_receipt_rejects(self):
        for bad in ('b'*64,None):
            with self.assertRaises(ValueError):score_panel(self.observation,self.labels,
                expected_observation_id=bad,expected_labels_sha256=_digest(self.labels))
        with self.assertRaises(ValueError):score_panel(self.observation,self.labels,
                expected_observation_id=self.observation['observation_id'],
                expected_labels_sha256='f'*64)

    def test_rehashed_logits_cannot_replace_externally_retained_seal(self):
        altered=copy.deepcopy(self.observation)
        altered['predictions']['conditioned'][0]['logits'][0]+=5
        altered['observation_id']=_digest({k:v for k,v in altered.items() if k!='observation_id'})
        with self.assertRaises(ValueError):score_panel(altered,self.labels,
            expected_observation_id=self.observation['observation_id'],
            expected_labels_sha256=_digest(self.labels))

    def test_reordered_task_or_source_identity_rejects(self):
        for key in ('task_id','source_group','question_slot'):
            altered=copy.deepcopy(self.observation)
            altered['predictions']['mean_pool'][0][key]='different' if key!='question_slot' else 1
            altered['observation_id']=_digest({k:v for k,v in altered.items() if k!='observation_id'})
            with self.subTest(key=key),self.assertRaises(ValueError):score_panel(altered,self.labels,
                expected_observation_id=altered['observation_id'],
                expected_labels_sha256=_digest(self.labels))

    def test_missing_result_or_ablated_logits_reject(self):
        for key in ('predictions','ablation_predictions'):
            altered=copy.deepcopy(self.observation)
            if key=='predictions': altered[key]['conditioned'].pop()
            else: altered[key].pop()
            altered['observation_id']=_digest({k:v for k,v in altered.items() if k!='observation_id'})
            with self.subTest(key=key), self.assertRaises(ValueError):score_panel(altered,self.labels,
                expected_observation_id=altered['observation_id'],
                expected_labels_sha256=_digest(self.labels))

    def test_group_overlap_and_future_train_labels_rejected(self):
        train,final,_=build_panel('a'*64,train_groups=2,eval_groups=1)
        for case in (train[0], final[0]):
            modified=copy.deepcopy(train)
            modified[0]=case if case is final[0] else case.__class__(case.case_id,case.source_group,case.evidence,case.task_ids,case.targets,12)
            with self.assertRaises(ValueError):validate_panel(modified,final,cutoff_ns=10,evaluation_ns=20)

    def test_incomplete_training_group_or_unbalanced_labels_reject(self):
        train,final,_=build_panel('a'*64,train_groups=2,eval_groups=1)
        with self.assertRaises(ValueError):validate_panel(train[1:],final,cutoff_ns=10,evaluation_ns=20)
        modified=copy.deepcopy(train)
        modified[1]=modified[1].__class__(modified[1].case_id,modified[1].source_group,modified[1].evidence,
                                         modified[1].task_ids,modified[0].targets,modified[1].label_observed_ns)
        with self.assertRaises(ValueError):validate_panel(modified,final,cutoff_ns=10,evaluation_ns=20)

    def test_retained_feature_payload_exhaustion_blocks_before_training(self):
        train,final,_=build_panel('a'*64,train_groups=16,eval_groups=4)
        with patch('conditional_evidence.fit_reader',side_effect=AssertionError('training must not run')):
            with self.assertRaisesRegex(ValueError,'cache budget'):
                train_panel(train,final,evidence_encoder=ToyEncoder(),query_encoder=ToyQuery(),
                    checkpoint_sha256='a'*64,policy=POLICY,max_retained_bytes=4096)

    def test_wrong_checkpoint_identity_rejected_before_encoder(self):
        enc=ToyEncoder()
        with self.assertRaisesRegex(ValueError,'mixed or changed'):
            train_panel(self.train,self.test,evidence_encoder=enc,query_encoder=ToyQuery(),
                checkpoint_sha256='b'*64,policy=POLICY)
        self.assertEqual(enc.calls,0)


if __name__=='__main__':
    unittest.main()
