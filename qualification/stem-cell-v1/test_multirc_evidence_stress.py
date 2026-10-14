"""Use genuinely trained PyTorch MultiRC Readers, not hand-written predictions."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from matrix_bank import state_digest
from multirc_evidence_stress import (SCHEMA,NEUTRAL,audit_evidence,
                                     load_conditioned_bank,main)
from multirc_reader_study import train_then_predict,publish
from test_multirc_real_study import panels,DummyEncoder
from next_round_matrix import _digest


class EvidenceStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.train,cls.heldout,cls.owner_labels=panels()
        cls.real_encoder=DummyEncoder()
        cls.obs,cls.readers=train_then_predict(cls.train,lambda:copy.deepcopy(cls.heldout),
            encoder=cls.real_encoder,question_encoder=cls.real_encoder.query,
            checkpoint_sha256='c'*64,steps=8)
        cls.reader=cls.readers['conditioned']
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.run_dir=Path(cls.tmp.name)/'sealed-model'
        cls.seal=publish(cls.run_dir,cls.obs,cls.readers)

    def fresh(self):
        return DummyEncoder()

    def audit(self,**kwargs):
        encoder=kwargs.pop('encoder',self.fresh())
        return audit_evidence(self.train,self.heldout,self.obs,self.reader,
            encoder=encoder,question_encoder=encoder.query,
            checkpoint_sha256='c'*64,**kwargs)

    def test_actual_heldout_original_parity_and_extra_work_charged(self):
        enc=self.fresh()
        before=state_digest(self.reader)
        r=self.audit(encoder=enc)
        self.assertEqual(r['schema'],SCHEMA)
        self.assertEqual(r['task_count'],8)
        self.assertEqual(r['passage_count'],4)
        self.assertEqual(r['encoder_calls'],5)
        self.assertEqual(r['query_calls'],8)
        self.assertEqual(r['conditioned_reader_calls'],32)
        self.assertEqual(len([t for t in enc.calls if t[0]=='evidence']),5)
        self.assertTrue(any(t[1]==NEUTRAL for t in enc.calls))
        self.assertEqual(state_digest(self.reader),before)
        self.assertTrue(r['factual_original_replay_validated'])
        self.assertGreater(r['stress_work']['phase_flops']['inference'],0)
        self.assertEqual(r['stress_work']['unknown_operators'],{})
        self.assertTrue(r['stress_work_not_in_original_phase_receipt'])
        self.assertFalse(r['missing_premise_correctness_certified'])

    def test_each_source_is_donor_only_for_other_group(self):
        r=self.audit()
        self.assertEqual(len(set(x['source_group'] for x in r['observations'])),4)
        for x in r['observations']:
            self.assertNotEqual(x['source_group'],x['donor_source_group'])
            self.assertEqual(set(x['absolute_positive_probability_change']),
                             {'neutral_evidence','different_passage','other_question'})
            self.assertTrue(all(0<=v<=1 for v in x['absolute_positive_probability_change'].values()))

    def test_no_labels_read_or_invented_for_modified_evidence(self):
        r=self.audit()
        self.assertFalse(r['independent_training_gain_established'])
        self.assertTrue(r['counterfactual_answer_labels_undefined'])
        self.assertFalse(r['statistical_superiority_established'])
        self.assertFalse(r['production_authorized'])
        self.assertFalse(any('label' in key for row in r['observations'] for key in row))

    def test_restore_actual_safetensors_reader_and_reject_tampered_weights(self):
        loaded=load_conditioned_bank(self.run_dir/'conditioned.safetensors',self.obs)
        self.assertEqual(state_digest(loaded),state_digest(self.reader))
        enc=self.fresh()
        r=audit_evidence(self.train,self.heldout,self.obs,loaded,
            encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64)
        self.assertEqual(r['task_count'],8)
        corrupted=copy.deepcopy(self.obs)
        corrupted['training']['conditioned']['weights_sha256']='a'*64
        with self.assertRaises(ValueError):load_conditioned_bank(self.run_dir/'conditioned.safetensors',corrupted)

    def test_sealed_prediction_mutation_rejected_before_measuring(self):
        for case in ('logits','sample_order','owner','snapshot'):
            obs=copy.deepcopy(self.obs)
            if case=='logits':obs['predictions']['conditioned'][0]['logits'][0]+=1
            elif case=='sample_order':obs['predictions']['conditioned'].reverse()
            elif case=='owner':obs['training']['conditioned']['weights_sha256']='0'*64
            elif case=='snapshot':obs['model_snapshot_sha256']='0'*64
            enc=self.fresh()
            with self.subTest(case=case),self.assertRaises(ValueError):
                audit_evidence(self.train,self.heldout,obs,self.reader,encoder=enc,
                    question_encoder=enc.query,checkpoint_sha256='c'*64)

    def test_model_that_changes_outputs_may_not_be_reported_as_counterfactual_gain(self):
        class Unstable(DummyEncoder):
            def __call__(self,text):
                output=super().__call__(text)
                return output + len(self.calls)*0.3
        enc=Unstable()
        with self.assertRaisesRegex(ValueError,'replayed original'):
            self.audit(encoder=enc)

    def test_cross_split_or_blind_label_injection_rejected(self):
        for case in ('eval_label','source_collision','panel_id'):
            ev=copy.deepcopy(self.heldout)
            if case=='eval_label':ev['rows'][0]['questions'][0]['label']=1
            elif case=='source_collision':ev['rows'][0]['source_group']=self.train['rows'][0]['source_group']
            else:ev['panel_id']='0'*64
            enc=self.fresh()
            with self.subTest(case=case),self.assertRaises(ValueError):
                audit_evidence(self.train,ev,self.obs,self.reader,encoder=enc,
                               question_encoder=enc.query,checkpoint_sha256='c'*64)

    def test_storage_limit_and_input_types_fail_closed(self):
        with self.assertRaises(ValueError):self.audit(max_cached_bytes=1023)
        class LargeEncoder(DummyEncoder):
            def __call__(self,text):
                return torch.stack([super(LargeEncoder,self).__call__(text)[0]]*120)
        with self.assertRaisesRegex(ValueError,'retained passage storage'):
            self.audit(encoder=LargeEncoder(),max_cached_bytes=1024)
        for x in (True,-1,0.001,float('nan')):
            with self.subTest(x=x),self.assertRaises(ValueError):
                self.audit(replay_abs_tolerance=x)

    def test_unknown_atten_operation_or_tiny_budget_never_masquerades_as_success(self):
        class AtanEncoder(DummyEncoder):
            def __call__(self,text):return torch.atan(super().__call__(text))
        enc=AtanEncoder()
        from execution_meter import BudgetStop
        with self.assertRaises(BudgetStop):self.audit(encoder=enc)

    def test_complete_cli_seal_and_failures_without_training(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            training=root/'training.json';training.write_text(json.dumps(self.train))
            blind=root/'blind.json';blind.write_text(json.dumps(self.heldout))
            output=root/'stress'
            def mocked_snapshot(_):
                enc=DummyEncoder()
                return enc,enc.query,lambda:None,'c'*64,None,None
            args=['stress','--train-bundle',str(training),'--blind-eval-bundle',str(blind),
                  '--run-dir',str(self.run_dir),'--expected-seal-id',self.seal['seal_id'],
                  '--snapshot','/pinned-test','--output',str(output)]
            with patch.object(sys,'argv',args),patch('multirc_evidence_stress.safe_encoder',side_effect=mocked_snapshot):
                main()
            self.assertTrue((output/'COMMITTED.json').exists())
            self.assertFalse((output/'FAILED.json').exists())
            result=json.loads((output/'stress.json').read_text())
            self.assertEqual(result['task_count'],8)
            self.assertNotIn('label',result['observations'][0])
            broken=root/'failed';bad=args[:]
            bad[bad.index('--expected-seal-id')+1]='f'*64
            bad[bad.index('--output')+1]=str(broken)
            with patch.object(sys,'argv',bad),patch('multirc_evidence_stress.safe_encoder',side_effect=mocked_snapshot):
                with self.assertRaises(ValueError):main()
            self.assertTrue((broken/'FAILED.json').exists())
            self.assertFalse((broken/'COMMITTED.json').exists())


if __name__=='__main__':unittest.main()
