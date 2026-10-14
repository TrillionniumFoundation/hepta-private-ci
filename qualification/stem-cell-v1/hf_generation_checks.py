"""Opt-in stock Transformers tests; never a pretrained-model quality experiment.

Run separately from the dependency-light suite; missing Transformers is a hard
import failure, not a skip counted as passing. No network acquisition occurs.
"""
import tempfile
import unittest
from pathlib import Path

import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

from causal_generation import GenerationIncomplete
from causal_snapshot import load_local_causal
from hf_encoder_kernel import snapshot_digest
from system2_execution import PublicTask


class StockCausalChecks(unittest.TestCase):
    def test_real_stock_checkpoint_load_and_exact_tied_inventory(self):
        with tempfile.TemporaryDirectory() as td, torch.random.fork_rng(devices=[]):
            torch.manual_seed(4)
            model=GPT2LMHeadModel(GPT2Config(vocab_size=8,n_positions=128,n_embd=12,n_layer=1,n_head=3,eos_token_id=1))
            model.save_pretrained(td,safe_serialization=True)
            graph=Tokenizer(WordLevel({'<unk>':0,'<eos>':1,'colour':2,'red':3,'task':4,'previous':5,'feedback':6,'ANSWER':7},unk_token='<unk>'))
            graph.pre_tokenizer=Whitespace()
            tokenizer=PreTrainedTokenizerFast(tokenizer_object=graph,eos_token='<eos>',unk_token='<unk>')
            tokenizer.save_pretrained(td)
            proposer,receipt=load_local_causal(td,expected_snapshot_sha256=snapshot_digest(td),
                                               material_approval_sha256='a'*64,context_tokens=128,max_new_tokens=4)
            self.assertTrue(receipt['materialization']['all_state_dict_tensors_accounted'])
            self.assertFalse(receipt['pretrained_provenance_verified'])
            # Random stock weights may never emit EOS or emit it immediately.
            # Both are genuine generation failures, not fixed by changing logits.
            try:
                output=proposer(PublicTask('colour red',5),None,None)
                self.assertIsInstance(output,str)
            except GenerationIncomplete:
                self.assertEqual(proposer.receipt()['last_generation']['status'],'failed')
            self.assertGreater(proposer.receipt()['last_generation']['forward_attempts'],0)
            self.assertEqual(snapshot_digest(td),receipt['snapshot_sha256'])


if __name__=='__main__':unittest.main()
