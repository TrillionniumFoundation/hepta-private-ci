"""Installed Transformers: physically recover a saved tied alias, never pretrained efficacy."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import torch
from multimodal_exact_tied_alias_v11 import DECODER, EMBEDDING, same_physical_view

@unittest.skipUnless(importlib.util.find_spec('transformers'), 'hosted HF required')
class PhysicalSavedTiedAliasTests(unittest.TestCase):
    def test_actual_stock_mlm_original_bytes_recovered_from_forced_meta_pair(self):
        from transformers import AutoModelForMaskedLM, BertTokenizerFast, ModernBertConfig, ModernBertForMaskedLM
        from execution import LocalEncoder
        from public_stem_material_v8 import PINNED_RELEASES
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with torch.random.fork_rng():
                torch.manual_seed(171)
                cfg=ModernBertConfig(vocab_size=32,hidden_size=16,intermediate_size=32,
                    num_hidden_layers=2,num_attention_heads=4,max_position_embeddings=128,
                    local_attention=16,global_attn_every_n_layers=2,pad_token_id=0,
                    reference_compile=False)
                cfg._attn_implementation='eager'
                stock=ModernBertForMaskedLM(cfg).eval().requires_grad_(False)
            stock.save_pretrained(root,safe_serialization=True)
            (root/'vocab.txt').write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\n')
            BertTokenizerFast(vocab_file=str(root/'vocab.txt'),do_lower_case=True).save_pretrained(root)
            inventory={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in root.rglob('*') if p.is_file()}
            # Revision-name fixture alone is not authority: all bytes here are random
            # mini stock weights. Do not cite this as pretrained source evidence.
            manifest={'revision':PINNED_RELEASES['mmbert-small'],'kind':'masked_lm','files':inventory}
            loader=AutoModelForMaskedLM.from_pretrained
            def meta_pair(*args,**kw):
                loaded,info=loader(*args,**kw)
                embed=loaded.get_input_embeddings()
                absent=torch.nn.Parameter(torch.empty(embed.weight.shape,dtype=embed.weight.dtype,device='meta'),requires_grad=False)
                embed.weight=absent;loaded.decoder.weight=absent
                self.assertTrue(embed.weight.is_meta)
                return loaded,info
            with patch.object(AutoModelForMaskedLM,'from_pretrained',side_effect=meta_pair):
                runtime=LocalEncoder(root,manifest,maximum_tokens=64)
            self.assertIsNotNone(runtime.original_tied_source_recovery)
            self.assertFalse(runtime.original_tied_source_recovery['production_accepted'])
            state=runtime.loaded.state_dict()
            self.assertTrue(same_physical_view(state[EMBEDDING],state[DECODER]))
            torch.testing.assert_close(state[EMBEDDING],stock.state_dict()[EMBEDDING],rtol=0,atol=0)
            first=runtime.encode(['hello world','hello'])
            second=runtime.encode(['hello world','hello'])
            torch.testing.assert_close(first,second,rtol=0,atol=0)
            runtime.close()
