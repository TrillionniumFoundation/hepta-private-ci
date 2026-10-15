"""Research-only byte-level original tokenizer and physical Llama regression."""
from pathlib import Path
import hashlib
import os
import unittest

from amcn_original_text_reader import (
    ArchivedByteLevelBPE, ArchivedLlama, WEIGHT_SHA256, check_file, file_sha,
    format_archived_chat,
)

ROOT_ENV = os.environ.get('HEPTA_AMCN_ORIGINAL_ROOT')


class ArchivedTokenizerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ROOT_ENV:
            cls.root=Path(ROOT_ENV)/'reader'
            cls.tok=ArchivedByteLevelBPE(cls.root,
                      expected_tokenizer_sha256=file_sha(cls.root/'tokenizer.json'))
        else:
            cls.root=None
            cls.tok=None

    def test_source_absent_no_success(self):
        with self.assertRaises(ValueError):
            check_file(Path('/surely/not/an/original/model.safetensors'),max_bytes=200)

    def test_missing_original_vocab_must_refuse(self):
        if not ROOT_ENV:self.skipTest('physical tokenizer files must be provided externally')
        with self.assertRaisesRegex(ValueError, 'SHA mismatch'):
            ArchivedByteLevelBPE(self.root,expected_tokenizer_sha256='0'*64)

    def test_unicode_and_original_chat_bytelevel_roundtrip(self):
        if not ROOT_ENV:self.skipTest('only original model archive certifies byte tokens')
        texts=["Hello world!", "Caroline went to an LGBTQ support group yesterday.",
               "Chinese 中文, French français, emoji 😀", "2023, 2024, and 12345",
               "newlines\n\t punctuation...", "<|im_start|>assistant\nHello<|im_end|>"]
        for original in texts:
            self.assertEqual(self.tok.decode(self.tok.encode(original),skip_special=False),original)

    def test_original_fixed_token_ids_and_special_chat(self):
        if not ROOT_ENV:self.skipTest('original tokenizer material absent')
        self.assertEqual(self.tok.encode('Hello world!'),[19556,905,17])
        self.assertEqual(self.tok.encode('<|im_start|>assistant\n'),[1,520,9531,198])

    def test_prompt_binding_not_gold_answer(self):
        p=format_archived_chat('When was it?',['Session dated 8 May. She went yesterday.'])
        self.assertIn('[E1]',p)
        self.assertNotIn('model_answer:',p)


class OriginalLlamaPhysicalContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ROOT_ENV:
            import torch
            torch.set_num_threads(2)
            cls.model=ArchivedLlama(Path(ROOT_ENV)/'reader')
        else:
            cls.model=None

    def test_original_archived_logits_match_prior_independent_reference(self):
        if self.model is None:self.skipTest('actual original model weights absent')
        import torch
        with torch.inference_mode():
            logits=self.model.forward([1,420,35,177],reset=True)
        raw=logits.cpu().float().contiguous().numpy().astype('<f4').tobytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            '0e213cba29020f3140dee7e72d5b8737ebcb2ce0e0189e5662b8415a09f71776')

    def test_incremental_kv_logits_match_original_full_forward_with_tolerance(self):
        if self.model is None:self.skipTest('actual original model weights absent')
        import torch
        full=self.model.forward([1,420,35,177],reset=True)
        self.model.forward([1,420,35],reset=True)
        incremental=self.model.forward([177])
        self.assertLessEqual(float((full-incremental).abs().max()), 0.0001)
        self.assertEqual(full.topk(5).indices.tolist(), incremental.topk(5).indices.tolist())

    def test_disallow_generated_answer_without_original_source(self):
        if self.model is None:self.skipTest('actual original model weights absent')
        with self.assertRaises(ValueError):
            self.model.generate([1]*1000,max_new_tokens=96)

    def test_tampered_original_model_refused(self):
        if self.model is None:self.skipTest('actual original model weights absent')
        with self.assertRaisesRegex(ValueError,'SHA mismatch'):
            ArchivedLlama(Path(ROOT_ENV)/'reader',expected_sha256='0'*64)


if __name__=='__main__':unittest.main()
