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


    def test_stock_dynamic_cache_matches_full_prefix_each_step(self):
        from causal_cache import RequestKV, freeze_cache
        from matrix_bank import state_digest
        # Real stock random architecture, not pretrained or generalization evidence.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(21)
            cfg = GPT2Config(vocab_size=31, n_positions=64, n_embd=24, n_layer=2, n_head=3)
            cfg._attn_implementation = "eager"
            model = GPT2LMHeadModel(cfg).eval().requires_grad_(False)
            before = state_digest(model)
            policy = freeze_cache(layers=2, heads=3, head_dim=8, max_cache_bytes=65536,
                                  cache_format="hf_dynamic_gpt2_4_57_1")
            tokens = torch.tensor([[2, 4, 6, 8]])
            session = RequestKV(model, policy, prompt_tokens=4, max_new_tokens=6)
            try:
                with torch.inference_mode():
                    for step in range(6):
                        reference = model(input_ids=tokens, attention_mask=torch.ones_like(tokens),
                                          use_cache=False, return_dict=True).logits[:, -1]
                        cached, query = session.forward(tokens)
                        torch.testing.assert_close(cached[:, -1], reference, rtol=1e-5, atol=2e-6)
                        self.assertTrue(torch.equal(cached[:, -1].argmax(-1), reference.argmax(-1)))
                        self.assertEqual(query, 4 if step == 0 else 1)
                        tokens = torch.cat((tokens, reference.argmax(-1).unsqueeze(1)), dim=1)
            finally:
                session.close()
            self.assertIsNone(session.cache)
            self.assertEqual(session.receipt()["forwarded_tokens"], 9)
            self.assertEqual(state_digest(model), before)


if __name__=='__main__':unittest.main()
