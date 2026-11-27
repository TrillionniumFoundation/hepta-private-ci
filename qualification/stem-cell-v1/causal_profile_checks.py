"""Required installed-HF checks, independent of the dependency-light unit suite.

Tiny Llama weights are locally TRAINED below, not pretrained model evidence.
No skip on missing packages. Real public checkpoint work is a separate canary.
"""
import copy
import tempfile
import unittest
from pathlib import Path

import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

from hf_causal_generator import DecodeLimits, LocalCausalProposer, load_local_causal
from hf_encoder_kernel import snapshot_digest
from public_causal_probe import probe
from system2_execution import PublicTask


class InstalledCausalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.root=Path(cls.tmp.name)
        with torch.random.fork_rng():
            torch.manual_seed(319)
            config=LlamaConfig(vocab_size=16,hidden_size=16,intermediate_size=32,num_hidden_layers=1,
                num_attention_heads=2,num_key_value_heads=1,max_position_embeddings=512,
                bos_token_id=1,eos_token_id=2,pad_token_id=0,tie_word_embeddings=True)
            config._attn_implementation='eager'
            cls.model=LlamaForCausalLM(config)
        # Train next-token probabilities, not a hardcoded generation callback.
        optimizer=torch.optim.Adam(cls.model.parameters(),lr=.01)
        x=torch.tensor([[3,4,5,6]]);y=torch.tensor([4,5,6,2])
        for _ in range(80):
            optimizer.zero_grad(set_to_none=True)
            loss=torch.nn.functional.cross_entropy(cls.model(x,use_cache=False).logits.reshape(-1,16),y)
            loss.backward();optimizer.step()
        cls.model.eval().requires_grad_(False).save_pretrained(cls.root,safe_serialization=True)
        vocabulary={'[PAD]':0,'[BOS]':1,'[EOS]':2,'[UNK]':3,'answer':4,'is':5,'5':6}
        vocabulary.update({f'w{i}':i for i in range(7,16)})
        token=Tokenizer(WordLevel(vocabulary,unk_token='[UNK]'));token.pre_tokenizer=Whitespace()
        fast=PreTrainedTokenizerFast(tokenizer_object=token,unk_token='[UNK]',bos_token='[BOS]',
            eos_token='[EOS]',pad_token='[PAD]',model_input_names=['input_ids','attention_mask'])
        fast.chat_template="{% for m in messages %}{{m['content']}} {% endfor %}[UNK]"
        fast.save_pretrained(cls.root)
    def test_real_causal_weight_roundtrip_and_physical_tie(self):
        model,_,receipt=load_local_causal(self.root)
        self.assertIs(model.lm_head.weight,model.model.embed_tokens.weight)
        self.assertTrue(receipt['materialization']['all_state_dict_tensors_accounted'])
        for k,v in self.model.state_dict().items():torch.testing.assert_close(v,model.state_dict()[k],rtol=0,atol=0)
    def test_actual_trained_causal_model_generates_and_restarts(self):
        proposer=LocalCausalProposer(self.root,expected_snapshot_sha256=snapshot_digest(self.root),limits=DecodeLimits(new_tokens=8))
        a=proposer(PublicTask('unknown',10),None,None)
        proposer(PublicTask('different prompt',11),'old answer','revise')
        b=proposer(PublicTask('unknown',10),None,None)
        self.assertEqual(a,b);self.assertTrue(a);proposer.reverify()
    def test_real_hf_model_flows_through_capture_and_late_objective_join(self):
        with tempfile.TemporaryDirectory() as td:
            result=probe(self.root,Path(td))
            self.assertEqual(result['captured_pairs'],4)
            self.assertEqual(result['pair_statuses'],['completed']*4)
            self.assertFalse(result['efficacy_established'])
            self.assertTrue((Path(td)/'objective-scores.json').is_file())


if __name__=='__main__':
    unittest.main()
