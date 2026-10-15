"""Synthetic real-nn.Module path for the E2 physical forward/mask contract.

This does NOT execute pretrained weights or authenticate source provenance.
"""
import types
import unittest
import torch
from torch import nn

from test_e2_token_query_ablation import fixture
import e2_token_query_real_cpu as r
from e2_token_query_ablation import frozen_bank


class SyntheticModel(nn.Module):
    def forward(self,input_ids,attention_mask,**kwargs):
        h=torch.arange(384,dtype=torch.float32)[None,None,:]/384
        output=(input_ids[...,None].float()/100 + h)
        return types.SimpleNamespace(last_hidden_state=output)


class FakeTokenizer:
    def __call__(self,strings,**kwargs):
        n=max(3+(len(s)%4) for s in strings)
        ids=torch.zeros((len(strings),n),dtype=torch.long)
        mask=torch.zeros_like(ids)
        for i,s in enumerate(strings):
            l=3+(len(s)%4)
            ids[i,:l]=torch.arange(1,l+1)
            mask[i,:l]=1
        return {'input_ids':ids,'attention_mask':mask}


class Backend:
    def __init__(self):
        self.model=SyntheticModel()
        self.tokenizer=FakeTokenizer()
        self.forward_calls=0
        self.loaded=types.SimpleNamespace(config=types.SimpleNamespace(model_type='modernbert'))


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(1)

    def cases(self):
        rows,_=fixture()
        for row in rows:
            row['joint_input']={'state':row['case_id'],'question':'Q','options':['0','1']}
        return rows

    def test_one_actual_torch_module_hook_per_microbatch(self):
        rows=self.cases();backend=Backend()
        tokens,receipt=r.extract(rows,backend,pooling='attention-mask-mean',width=384)
        self.assertEqual(backend.forward_calls,28)
        self.assertEqual(receipt['observed_model_module_forward_hooks'],28)
        self.assertTrue(receipt['native_pool_and_token_query_derived_from_same_hidden_tensor'])
        self.assertEqual(len(tokens),224)
        self.assertEqual(frozen_bank(rows,tokens,width=384)['case_count'],224)
        self.assertFalse(receipt['independent_model_module_execution_attested'])

    def test_reused_backend_counter_rejected(self):
        b=Backend();b.forward_calls=1
        with self.assertRaises(r.Invalid):
            r.extract(self.cases(),b,pooling='attention-mask-mean',width=384)

    def test_invalid_microbatch_rejected(self):
        with self.assertRaises(r.Invalid):
            r.extract(self.cases(),Backend(),pooling='attention-mask-mean',
                      width=384,batch_size=9)


if __name__=='__main__':unittest.main()
