import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from shared_learning_probe import fit_controls, freeze_study, score_sealed, TOPOLOGIES
from matrix_materials import file_sha256


def rows(split):
    return [dict(sample_id=f'{split}:{i}',state=f'{split} category {i}',
                 question='Choose the topic.',options=['World','Sports','Business','Science']) for i in range(4)]


class Encoder:
    def __init__(self, fail=False): self.calls=0;self.seen=[];self.fail=fail
    def __call__(self,row):
        self.calls+=1;self.seen.append(copy.deepcopy(row))
        if self.fail: raise RuntimeError('fixture failed encoder')
        # Real inference tensors mimic frozen Encoder outputs; destination
        # materialization must remain usable by normal autograd Head training.
        with torch.inference_mode():
            x=torch.zeros(4);x[int(row['state'][-1])]=1.
            return x,12


class SharedLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'study'
        self.cfg=freeze_study(train_steps=3,batch_size=4,width_units=3)

    def run_case(self,root=None,encoder=None):
        return fit_controls(encoder or Encoder(),rows('train'),[0,1,2,3],rows('eval'),
                            root or self.root,dimension=4,study=self.cfg)

    def test_actual_training_parameter_parity_and_sparse_execution(self):
        backend=Encoder();seal=self.run_case(encoder=backend)
        run=json.loads((self.root/'predictions.json').read_text())
        self.assertEqual(backend.calls,8)
        self.assertTrue(all(set(r)=={'sample_id','state','question','options'} for r in backend.seen))
        self.assertEqual([a['status'] for a in run['arms']],['completed']*3)
        self.assertEqual([a['inventory']['parameters'] for a in run['arms']],[864]*3)
        self.assertEqual(run['arms'][0]['initial_sha256'],run['arms'][1]['initial_sha256'])
        self.assertTrue(all(a['trained_sha256']!=a['initial_sha256'] for a in run['arms']))
        self.assertGreater(sum(run['arms'][0]['inventory']['executed_rows']),sum(run['arms'][1]['inventory']['executed_rows']))
        self.assertTrue(all(not a['work']['unknown_operators'] for a in run['arms']))
        scored=score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])
        self.assertTrue(scored['parameter_matched'])
        self.assertFalse(scored['observed_training_work_matched_within_one_percent'])
        self.assertFalse(scored['learning_superiority_established'])

    def test_scoring_labels_do_not_trigger_training_or_modify_parameters(self):
        seal=self.run_case()
        paths=[self.root/t[0]/'bank.safetensors' for t in TOPOLOGIES]
        original=[file_sha256(p) for p in paths]
        with patch('shared_learning_probe.train_bank',side_effect=AssertionError('no retraining')):
            a=score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])
            b=score_sealed(self.root,[3,2,1,0],expected_seal_id=seal['seal_id'])
        self.assertNotEqual(a['labels_sha256'],b['labels_sha256'])
        self.assertEqual(original,[file_sha256(p) for p in paths])

    def test_eval_labels_are_rejected_before_encoder_and_output_creation(self):
        evaluation=rows('eval');evaluation[0]['label']=0
        backend=Encoder()
        with self.assertRaises(ValueError):
            fit_controls(backend,rows('train'),[0,1,2,3],evaluation,self.root,dimension=4,study=self.cfg)
        self.assertEqual(backend.calls,0);self.assertFalse(self.root.exists())

    def test_scoring_denominator_and_prediction_mutation_reject(self):
        seal=self.run_case()
        for labels in ([0],[True,1,2,3],[4,1,2,3]):
            with self.subTest(labels=labels),self.assertRaises(ValueError):
                score_sealed(self.root,labels,expected_seal_id=seal['seal_id'])
        p=self.root/'predictions.json';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])

    def test_altered_bank_and_reused_output_reject(self):
        seal=self.run_case();p=self.root/'dense16'/'bank.safetensors'
        p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])
        with self.assertRaises(FileExistsError):self.run_case()

    def test_failed_shared_encoding_retains_inventory_not_success(self):
        backend=Encoder(fail=True)
        with self.assertRaises(RuntimeError):self.run_case(encoder=backend)
        failure=json.loads((self.root/'FAILED.json').read_text())
        self.assertEqual(failure['expected_arms'],[t[0] for t in TOPOLOGIES])
        self.assertIsNone(failure['work']['phase_flops']['train'])
        self.assertFalse((self.root/'COMMITTED.json').exists())

    def test_failed_training_arms_are_all_retained_with_unknown_work(self):
        with patch('shared_learning_probe.train_bank',side_effect=RuntimeError('fit failed')):
            seal=self.run_case()
        scored=score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])
        self.assertEqual([a['status'] for a in scored['arms']],['failed']*3)
        self.assertFalse(scored['all_arms_completed'])
        self.assertFalse(scored['parameter_matched'])
        self.assertTrue(all(a['after'] is None for a in scored['arms']))

    def test_unknown_encoder_operator_is_not_zero_cost(self):
        base=Encoder()
        def unknown(row):
            v,n=base(row);return torch.special.erfc(v),n
        with self.assertRaises(RuntimeError):self.run_case(encoder=unknown)
        self.assertTrue((self.root/'FAILED.json').exists())

    def test_fixed_seed_produces_same_predictions_and_weights(self):
        self.run_case()
        other=self.root.parent/'other';self.run_case(root=other)
        a=json.loads((self.root/'predictions.json').read_text())
        b=json.loads((other/'predictions.json').read_text())
        self.assertEqual(a['predictions'],b['predictions'])
        self.assertEqual([r['trained_sha256'] for r in a['arms']],[r['trained_sha256'] for r in b['arms']])

    def test_poisoned_shared_features_stop_later_training(self):
        calls=[]
        def corrupt(bank,features,labels,config,seed):
            calls.append(1);features.add_(1)
            return {'steps':config['train_steps']}
        with patch('shared_learning_probe.train_bank',side_effect=corrupt):
            seal=self.run_case()
        self.assertEqual(len(calls),1)
        result=score_sealed(self.root,[0,1,2,3],expected_seal_id=seal['seal_id'])
        self.assertTrue(all(a['status']=='failed' for a in result['arms']))

    def test_missing_hf_dependency_leaves_explicit_failure(self):
        from shared_learning_probe import run_public_learning
        with patch.dict('sys.modules',{'transformers':None}):
            with self.assertRaises(ModuleNotFoundError):
                run_public_learning('unused','unused',self.root)
        result=json.loads((self.root/'FAILED.json').read_text())
        self.assertFalse(result['completed'])
        self.assertFalse((self.root/'COMMITTED.json').exists())

    def test_configuration_caps_cannot_be_mutated(self):
        self.cfg['phase_caps']['train']+=1
        with self.assertRaises(ValueError):self.run_case()
        for value in (True,0,129):
            with self.subTest(value=value),self.assertRaises(ValueError):freeze_study(train_steps=value)


if __name__=='__main__':
    unittest.main()
