"""Installed-HF physical test, random stock MLM and original-byte-only forced Meta recovery."""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import torch
from multimodal_exact_tied_alias_v11 import DECODER, EMBEDDING, same_physical_view

@unittest.skipUnless(importlib.util.find_spec("transformers"), "hosted HF required")
class StockSavedTiedAliasTest(unittest.TestCase):
    def test_random_stock_mlm_source_restored_into_forced_meta_pair(self):
        from transformers import (
            AutoModelForMaskedLM,BertTokenizerFast,ModernBertConfig,ModernBertForMaskedLM,
        )
        from execution import LocalEncoder
        from public_stem_material_v8 import PINNED_RELEASES
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with torch.random.fork_rng():
                torch.manual_seed(171)
                cfg=ModernBertConfig(
                    vocab_size=32,hidden_size=16,intermediate_size=32,
                    num_hidden_layers=2,num_attention_heads=4,
                    max_position_embeddings=128,local_attention=16,
                    global_attn_every_n_layers=2,pad_token_id=0,reference_compile=False)
                cfg._attn_implementation="eager"
                stock=ModernBertForMaskedLM(cfg).eval().requires_grad_(False)
            stock.save_pretrained(root,safe_serialization=True)
            # Reproduce the actual JHU safetensors convention observed in
            # the independent V17 artifact: decoder.weight is serialized,
            # whereas model.embeddings.tok_embeddings.weight is omitted.
            # This conversion is ONLY on the tiny random test fixture.
            from safetensors.torch import load_file, save_file
            checkpoint = root/"model.safetensors"
            original_weights = load_file(str(checkpoint))
            if EMBEDDING in original_weights:
                embedding_value = original_weights.pop(EMBEDDING)
                if DECODER in original_weights:
                    torch.testing.assert_close(
                        original_weights[DECODER], embedding_value, rtol=0, atol=0)
                else:
                    original_weights[DECODER] = embedding_value
            self.assertIn(DECODER, original_weights)
            self.assertNotIn(EMBEDDING, original_weights)
            save_file(original_weights, str(checkpoint))
            (root/"vocab.txt").write_text(
                "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\n"
            )
            BertTokenizerFast(vocab_file=str(root/"vocab.txt"),
                              do_lower_case=True).save_pretrained(root)
            files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in root.rglob("*") if p.is_file()}
            # Synthetic fixture is NOT an assertion of provenance for the
            # actual upstream revision, despite occupying the same namespace.
            manifest={"revision":PINNED_RELEASES["mmbert-small"],
                      "kind":"masked_lm","files":files}
            true_load=AutoModelForMaskedLM.from_pretrained
            def inject_meta(*args,**kwargs):
                loaded,info=true_load(*args,**kwargs)
                emb=loaded.get_input_embeddings()
                placeholder=torch.nn.Parameter(
                    torch.empty(emb.weight.shape,dtype=emb.weight.dtype,device="meta"),
                    requires_grad=False)
                emb.weight=placeholder
                loaded.decoder.weight=placeholder
                self.assertTrue(emb.weight.is_meta)
                return loaded,info
            with patch.object(AutoModelForMaskedLM,"from_pretrained",
                              side_effect=inject_meta):
                model=LocalEncoder(root,manifest,maximum_tokens=64)
            proof=model.original_tied_source_recovery
            self.assertIsNotNone(proof)
            self.assertFalse(proof["production_accepted"])
            state=model.loaded.state_dict()
            self.assertTrue(same_physical_view(state[EMBEDDING],state[DECODER]))
            torch.testing.assert_close(state[EMBEDDING],stock.state_dict()[EMBEDDING],rtol=0,atol=0)
            z=model.encode(["hello world","hello"])
            zz=model.encode(["hello world","hello"])
            torch.testing.assert_close(z,zz,rtol=0,atol=0)
            self.assertEqual(model.forward_calls,2)
            model.close()

if __name__=="__main__":
    unittest.main()
