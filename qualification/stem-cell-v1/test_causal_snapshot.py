import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import torch
from torch import nn
from safetensors.torch import save_file

from causal_snapshot import inspect_snapshot, load_local_causal
from generation_test_support import WordCodec
from hf_encoder_kernel import snapshot_digest


class TiedSnapshotModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.transformer = nn.Module()
        self.transformer.wte = nn.Embedding(15,12)
        self.lm_head = nn.Linear(12,15,bias=False)
        self.lm_head.weight = self.transformer.wte.weight
        self.config = SimpleNamespace(model_type='gpt2',_attn_implementation='eager')


class CausalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.model=TiedSnapshotModel()
        save_file({'transformer.wte.weight':self.model.transformer.wte.weight},str(self.root/'model.safetensors'))
        self.cfg=dict(model_type='gpt2',architectures=['GPT2LMHeadModel'],tie_word_embeddings=True,
                      n_embd=12,n_head=3,n_layer=1,vocab_size=15,n_positions=64)
        self.save_cfg()
        self.codec=WordCodec();self.codec.is_fast=True
        self.info=dict(missing_keys=['lm_head.weight'],unexpected_keys=[],mismatched_keys=[],error_msgs=[])
        self.loader=Mock(return_value=(self.model,self.info))
        self.tokenizer_loader=Mock(return_value=self.codec)
        self.module=SimpleNamespace(__version__='4.57.1',
               AutoModelForCausalLM=SimpleNamespace(from_pretrained=self.loader),
               AutoTokenizer=SimpleNamespace(from_pretrained=self.tokenizer_loader))

    def save_cfg(self): (self.root/'config.json').write_text(json.dumps(self.cfg))

    def load(self,**changes):
        kwargs=dict(expected_snapshot_sha256=snapshot_digest(self.root),material_approval_sha256='a'*64,
                    context_tokens=32,max_new_tokens=4)
        kwargs.update(changes)
        with patch.dict('sys.modules',transformers=self.module):
            return load_local_causal(self.root,**kwargs)

    def test_real_safetensor_alias_materialization_with_mocked_hf_factory(self):
        proposer,receipt=self.load()
        self.assertEqual(receipt['materialization']['omitted_tied_keys'],['lm_head.weight'])
        self.assertFalse(receipt['pretrained_provenance_verified'])
        self.assertFalse(any(p.requires_grad for p in self.model.parameters()))
        args=self.loader.call_args.kwargs
        self.assertEqual((args['local_files_only'],args['trust_remote_code'],args['use_safetensors']), (True,False,True))
        self.assertEqual(args['attn_implementation'],'eager')
        self.assertFalse(proposer.receipt()['policy']['persistent_kv_cache'])

    def test_equal_valued_copies_not_accepted_as_tied_views(self):
        self.model.lm_head.weight=nn.Parameter(self.model.transformer.wte.weight.detach().clone())
        with self.assertRaisesRegex(ValueError,'same physical view'): self.load()

    def test_partial_loading_or_changed_tensor_rejects(self):
        self.info['unexpected_keys']=['unloaded_head']
        with self.assertRaises(ValueError): self.load()
        self.info['unexpected_keys']=[]
        with torch.no_grad(): self.model.transformer.wte.weight.add_(1)
        with self.assertRaisesRegex(ValueError,'differs'):self.load()

    def test_context_geometry_version_and_missing_safe_weights_preflight(self):
        for change in (dict(context_tokens=65),dict(max_new_tokens=32)):
            with self.subTest(change=change),self.assertRaises(ValueError):self.load(**change)
        self.loader.assert_not_called()
        self.module.__version__='wrong'
        with self.assertRaisesRegex(ValueError,'version'):self.load()
        (self.root/'model.safetensors').unlink()
        (self.root/'pytorch_model.bin').write_bytes(b'not-to-load')
        with self.assertRaisesRegex(ValueError,'safetensors'):self.load()

    def test_noncanonical_or_unbounded_geometry_refuses_before_model_construction(self):
        original=self.cfg.copy()
        for key,value in (('model_type','other'),('n_embd',True),('n_layer',49),('n_inner',False),('auto_map',{'x':'y'})):
            self.cfg={**original,key:value};self.save_cfg()
            with self.subTest(key=key),self.assertRaises(ValueError):inspect_snapshot(self.root,snapshot_digest(self.root))
        self.loader.assert_not_called()

    def test_file_identity_and_during_load_mutation_reject(self):
        with self.assertRaisesRegex(ValueError,'admitted bytes'):self.load(expected_snapshot_sha256='0'*64)
        def changed(*a,**k):
            (self.root/'added.json').write_text('{}')
            return self.model,self.info
        self.loader.side_effect=changed
        with self.assertRaisesRegex(ValueError,'changed while'):self.load()


if __name__=='__main__':unittest.main()
