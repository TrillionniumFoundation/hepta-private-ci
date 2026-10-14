"""Question-vs-answer intervention uses genuine fitted Reader, not fake logits."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from matrix_bank import state_digest
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from multirc_evidence_stress import audit_evidence
from multirc_query_factorial import (SCHEMA,audit_question_answer_factors,
                                      _verified_original_stress,main)
from multirc_reader_study import train_then_predict,publish
from next_round_matrix import _digest
from test_multirc_real_study import panels,DummyEncoder


class ReadableDummy(DummyEncoder):
    def query(self,text):
        base=super().query(text)
        if 'affirmative' in text:return base+torch.tensor([0.,0.,0.02,0.])
        if 'negative' in text:return base+torch.tensor([0.,0.,0.,0.02])
        raise AssertionError('answer identity missing')


class QuestionAnswerFactorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.tr,cls.ev,cls.labels=panels()
        enc=ReadableDummy()
        cls.obs,cls.banks=train_then_predict(cls.tr,lambda:copy.deepcopy(cls.ev),
            encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64,steps=8)
        cls.tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.run_dir=Path(cls.tmp.name)/'model'
        cls.model_seal=publish(cls.run_dir,cls.obs,cls.banks)
        enc=ReadableDummy()
        cls.old_stress=audit_evidence(cls.tr,cls.ev,cls.obs,cls.banks['conditioned'],
            encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64)
        cls.stress_dir=Path(cls.tmp.name)/'stress'
        cls.stress_dir.mkdir()
        write_json_exclusive(cls.stress_dir/'stress.json',cls.old_stress)
        cls.stress_seal=dict(schema='hepta.multirc.blind-evidence-stress-seal.v1',
            stress_id=cls.old_stress['stress_id'],stress_sha256=file_sha256(cls.stress_dir/'stress.json'))
        cls.stress_seal['seal_id']=_digest(cls.stress_seal)
        write_json_exclusive(cls.stress_dir/'COMMITTED.json',cls.stress_seal)

    def audit(self,**kwargs):
        enc=kwargs.pop('encoder',ReadableDummy())
        return audit_question_answer_factors(self.tr,self.ev,self.obs,self.banks['conditioned'],
            encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64,
            original_stress=self.old_stress,**kwargs)

    def test_real_two_by_two_question_answer_factorial_replays_old_stress(self):
        enc=ReadableDummy()
        before=state_digest(self.banks['conditioned'])
        result=self.audit(encoder=enc)
        self.assertEqual(result['schema'],SCHEMA)
        self.assertEqual((result['passage_count'],result['question_count']),(4,8))
        self.assertEqual((result['physical_encoder_calls'],result['newly_computed_question_embeddings'],
                          result['conditioned_reader_calls']),(4,16,16))
        self.assertEqual(len([x for x in enc.calls if x[0]=='evidence']),4)
        self.assertEqual(len([x for x in enc.calls if x[0]=='query']),16)
        self.assertEqual(result['related_blinded_stress_id'],self.old_stress['stress_id'])
        self.assertEqual(result['work_observation']['unknown_operators'],{})
        self.assertGreater(result['work_observation']['phase_flops']['inference'],0)
        self.assertEqual(state_digest(self.banks['conditioned']),before)

    def test_holds_passage_fixed_and_constructs_all_four_query_candidate_combinations(self):
        enc=ReadableDummy()
        self.audit(encoder=enc)
        embedded=[x[1] for x in enc.calls if x[0]=='query']
        for group in self.ev['rows']:
            questions=group['questions']
            expected={q['question']+'\nCandidate answer: '+a['answer']
                      for q in questions for a in questions}
            observed={v.split('\nIs this candidate correct?')[0] for v in embedded
                      if v.split('\nCandidate answer: ')[0] in {q['question'] for q in questions}}
            self.assertEqual(observed,expected)

    def test_no_false_counterfactual_accuracy_or_new_labels(self):
        r=self.audit()
        self.assertIsNone(r['counterfactual_accuracy'])
        self.assertTrue(r['cross_question_answer_combinations_have_no_valid_labels'])
        self.assertFalse(r['independent_question_understanding_established'])
        self.assertFalse(r['native_or_production_authorized'])
        self.assertTrue(all('label' not in x for x in r['records']))
        self.assertEqual(r['insensitive_epsilon'],0.001)
        self.assertTrue(all(0<=x<=len(r['records']) for x in r['insensitive_question_counts'].values()))

    def test_mutated_blind_panel_or_cross_split_identity_refused(self):
        for how in ('add_label','edit_passage','wrong_panel','train_overlap'):
            ev=copy.deepcopy(self.ev)
            tr=copy.deepcopy(self.tr)
            if how=='add_label':ev['rows'][0]['questions'][0]['label']=0
            elif how=='edit_passage':ev['rows'][0]['evidence']+=' altered'
            elif how=='wrong_panel':ev['panel_id']='f'*64
            else:ev['rows'][0]['source_group']=tr['rows'][0]['source_group']
            enc=ReadableDummy()
            with self.subTest(how=how),self.assertRaises(ValueError):
                audit_question_answer_factors(tr,ev,self.obs,self.banks['conditioned'],
                    encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64)
            self.assertEqual(enc.calls,[])

    def test_stale_prediction_model_identity_and_wrong_checkpoint_refused(self):
        for how in ('stale_logits','wrong_weight','wrong_snapshot'):
            obs=copy.deepcopy(self.obs)
            if how=='stale_logits':obs['predictions']['conditioned'][0]['logits'][0]+=.5
            elif how=='wrong_weight':obs['training']['conditioned']['weights_sha256']='b'*64
            else:obs['model_snapshot_sha256']='b'*64
            with self.subTest(how=how),self.assertRaises(ValueError):
                audit_question_answer_factors(self.tr,self.ev,obs,self.banks['conditioned'],
                    encoder=ReadableDummy(),question_encoder=ReadableDummy().query,
                    checkpoint_sha256='c'*64)

    def test_old_blind_stress_wrong_owner_or_modified_other_question_rejected(self):
        old=copy.deepcopy(self.old_stress)
        old['observations'][0]['other_question_logits'][0]+=0.3
        old['stress_id']=_digest({k:v for k,v in old.items() if k!='stress_id'})
        with self.assertRaisesRegex(ValueError,'old cross-question stress does not replay'):
            enc=ReadableDummy()
            audit_question_answer_factors(self.tr,self.ev,self.obs,self.banks['conditioned'],
                encoder=enc,question_encoder=enc.query,checkpoint_sha256='c'*64,
                original_stress=old)

    def test_source_stress_seal_validation_rejects_bytes_and_external_id(self):
        self.assertEqual(_verified_original_stress(self.stress_dir,self.stress_seal['seal_id'])['stress_id'],
                         self.old_stress['stress_id'])
        with self.assertRaises(ValueError):
            _verified_original_stress(self.stress_dir,'f'*64)
        with tempfile.TemporaryDirectory() as d:
            import shutil
            root=Path(d)/'s'
            shutil.copytree(self.stress_dir,root)
            (root/'stress.json').write_bytes((root/'stress.json').read_bytes()+b' ')
            with self.assertRaises(ValueError):
                _verified_original_stress(root,self.stress_seal['seal_id'])

    def test_strict_unknown_aten_and_memory_cap_stop(self):
        class Unsupported(ReadableDummy):
            def __call__(self,text):return torch.atan(super().__call__(text))
        from execution_meter import BudgetStop
        with self.assertRaises(BudgetStop):self.audit(encoder=Unsupported())
        class BloatedBacking(ReadableDummy):
            def __call__(self,text):
                super().__call__(text)
                return torch.zeros(4096,dtype=torch.float32)[:12].reshape(3,4)
        with self.assertRaisesRegex(ValueError,'exceed cap'):
            self.audit(encoder=BloatedBacking(),max_feature_bytes=1024)
        for tol in (True,-1,float('nan'),0.001):
            with self.subTest(tol=tol),self.assertRaises(ValueError):
                self.audit(replay_abs_tolerance=tol)

    def test_real_cli_writes_complete_seal_or_failed_record_not_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            train=root/'train.json';evalpath=root/'eval.json'
            train.write_text(json.dumps(self.tr));evalpath.write_text(json.dumps(self.ev))
            out=root/'factors'
            enc=ReadableDummy()
            mocked=(enc,enc.query,lambda:None,'c'*64,None,None)
            argv=['factorial','--train-bundle',str(train),'--blind-eval-bundle',str(evalpath),
                  '--run-dir',str(self.run_dir),'--expected-seal-id',self.model_seal['seal_id'],
                  '--stress-dir',str(self.stress_dir),
                  '--expected-stress-seal-id',self.stress_seal['seal_id'],
                  '--snapshot','/fake-pinned','--output',str(out)]
            with patch.object(sys,'argv',argv),patch('multirc_query_factorial.safe_encoder',return_value=mocked):
                main()
            self.assertTrue((out/'COMMITTED.json').exists())
            self.assertFalse((out/'FAILED.json').exists())
            saved=json.loads((out/'factorial.json').read_text())
            self.assertEqual(saved['question_count'],8)
            self.assertTrue(all('label' not in row for row in saved['records']))
            failed=root/'failed'
            bad=argv[:]
            bad[bad.index('--output')+1]=str(failed)
            bad[bad.index('--expected-seal-id')+1]='0'*64
            with patch.object(sys,'argv',bad),patch('multirc_query_factorial.safe_encoder',return_value=mocked):
                with self.assertRaises(ValueError):main()
            self.assertTrue((failed/'FAILED.json').exists())
            self.assertFalse((failed/'COMMITTED.json').exists())

    def test_replay_uses_same_frozen_bank_and_emits_no_artificial_accuracy(self):
        a=self.audit()
        b=self.audit()
        self.assertEqual(a['mean_absolute_positive_probability_change'],
                         b['mean_absolute_positive_probability_change'])
        self.assertEqual([x['task_id'] for x in a['records']],
                         [x['task_id'] for x in b['records']])
        self.assertNotEqual(a['source_observation_id'],None)
        self.assertFalse(a['statistical_superiority_established'])


if __name__=='__main__':
    unittest.main()
