"""REQUIRED hosted HF test: stock RANDOM ModernBERT MLM, never pretrained efficacy.

Requires pinned Transformers 4.57.1. Local suites without Transformers may skip,
but the V11 physical workflow must reject every skip and assert this case ran.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import torch

from multimodal_exact_tied_alias_v11 import DECODER, EMBEDDING, same_physical_view


@unittest.skipUnless(importlib.util.find_spec("transformers"), "installed HF physical runtime required")
class PhysicalModernBertTiedCheckpointTests(unittest.TestCase):
    def test_stock_full_mlm_roundtrip_uses_saved_embedding_without_random_fallback(self):
        from transformers import BertTokenizerFast, ModernBertConfig, ModernBertForMaskedLM
        from execution import LocalEncoder
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with torch.random.fork_rng():
                torch.manual_seed(77)
                cfg = ModernBertConfig(
                    vocab_size=32, hidden_size=16, intermediate_size=32,
                    num_hidden_layers=2, num_attention_heads=4,
                    max_position_embeddings=128, local_attention=16,
                    global_attn_every_n_layers=2, pad_token_id=0,
                    reference_compile=False,
                )
                cfg._attn_implementation = "eager"
                original = ModernBertForMaskedLM(cfg).eval().requires_grad_(False)
            original.save_pretrained(root, safe_serialization=True)
            (root / "vocab.txt").write_text(
                "[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\n"
                "birds\nmigrate\nin\nwinter\nsmall\nmodels\n"
            )
            BertTokenizerFast(vocab_file=str(root / "vocab.txt"), do_lower_case=True).save_pretrained(root)
            checksums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in root.rglob("*") if p.is_file()}
            manifest = {"revision": "c" * 40, "kind": "masked_lm", "files": checksums}
            model = LocalEncoder(root, manifest, maximum_tokens=64)
            self.assertEqual(type(model.loaded).__name__, "ModernBertForMaskedLM")
            state = model.loaded.state_dict()
            self.assertTrue(same_physical_view(state[DECODER], state[EMBEDDING]))
            self.assertEqual(set(model.reconciled_tied_aliases) - {DECODER}, set())
            with torch.no_grad():
                first = model.encode(["birds migrate in winter", "small models"],
                                     pooling="attention-mask-mean")
                again = model.encode(["birds migrate in winter", "small models"],
                                     pooling="attention-mask-mean")
            self.assertEqual(tuple(first.shape), (2, 16))
            self.assertTrue(bool(torch.isfinite(first).all()))
            torch.testing.assert_close(first, again, rtol=0, atol=0)
            self.assertEqual(model.forward_calls, 2)
            self.assertTrue(all(hashlib.sha256((root / p).read_bytes()).hexdigest() == v
                                for p, v in checksums.items()))
            model.close()


if __name__ == "__main__":
    unittest.main()
