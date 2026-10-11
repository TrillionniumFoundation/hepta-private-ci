"""Numerical tensor checks only. No missing-Torch skip or random pretrained fallback."""
import tempfile
from pathlib import Path
import unittest
import torch

from fbsde_encoder import models,tensors,train_and_compare
from fbsde_encoder_cases import cases


class TensorTests(unittest.TestCase):
    def test_recurrent_parameters_are_tied_and_gradient_is_real(self):
        torch.manual_seed(1);torch.set_num_threads(2)
        semantic,head,group=models(torch)
        x=torch.randn(4,4,389);syntax=torch.randn(4,109)
        params=[id(p) for p in group.parameters()]
        y=group(x,syntax,4)
        y.square().mean().backward()
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum().item()>0 for p in group.parameters()))
        self.assertEqual(params,[id(p) for p in group.parameters()])
        self.assertEqual(head(x,syntax).shape,(4,))
        self.assertEqual(semantic(torch.randn(4,384)).shape,(4,4))

    def test_public_tensor_input_rejects_gold_field(self):
        row={'case_id':'x','utterance_ids':['u','v'],'target_intents':[0,1],'formula':('and',0,1)}
        x,s=tensors(torch,[row],{'u':torch.zeros(384),'v':torch.ones(384)})
        self.assertEqual(tuple(x.shape),(1,4,389));self.assertEqual(tuple(s.shape),(1,109))
        row['label']=True
        with self.assertRaisesRegex(ValueError,'unregistered'):tensors(torch,[row],{})

    def test_full_training_selection_and_decoding_protocol_with_explicit_fixture_features(self):
        torch.manual_seed(7);torch.set_num_threads(2)
        partitions={};features={}
        for split in ('train','validation','calibration','test'):
            partitions[split]=[]
            for j in range(32):
                uid=split+str(j);label=j%4
                partitions[split].append({'id':uid,'intent':label})
                v=torch.randn(384)*.01;v[label]=2.
                features[uid]=v
        with tempfile.TemporaryDirectory() as d:
            r=train_and_compare(torch,partitions,features,Path(d),seed=201)
            self.assertLess(r['fbsde_vs_exact_max_probability_difference'],1e-12)
            self.assertFalse(r['full_lifecycle_resource_gate_passed'])
            self.assertEqual(len(r['metrics']),8)
            self.assertTrue((Path(d)/'private-test-truths.json').is_file())


if __name__=='__main__':unittest.main()
