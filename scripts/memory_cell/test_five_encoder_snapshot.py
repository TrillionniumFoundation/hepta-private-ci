"""Exact old-BERT buffer verification on tiny random fixtures, not capability.

Weights, tokenizers, input text and file pins in this module are local fixtures.
The separate hosted audit uses the original archived pretrained model.
"""
from pathlib import Path
import tempfile
import unittest

import torch
from safetensors.torch import load_file, save_file
from transformers import BertConfig, BertModel, BertTokenizerFast

import five_causal_experiments as c
import five_causal_native  # establishes the existing repository import root
from experiments.shared_stem_cell.execution import (
    InputError, LocalEncoder, parameters, tensor_digest, verified_legacy_position_buffer,
)


class EncoderSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        with torch.random.fork_rng():
            torch.manual_seed(73)
            config = BertConfig(vocab_size=10, hidden_size=12, intermediate_size=24,
                num_hidden_layers=1, num_attention_heads=3, max_position_embeddings=32,
                hidden_dropout_prob=0.0, attention_probs_dropout_prob=0.0)
            config._attn_implementation = 'eager'
            self.model = BertModel(config).eval().requires_grad_(False)
        self.model.save_pretrained(self.root, safe_serialization=True)
        (self.root/'vocab.txt').write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\nsmall\ntext\n.\n')
        self.tokenizer = BertTokenizerFast(vocab_file=str(self.root/'vocab.txt'), do_lower_case=True)
        self.tokenizer.save_pretrained(self.root)

    def tearDown(self):
        self.directory.cleanup()

    def saved(self):
        return {k: v.detach().clone().contiguous() for k, v in load_file(str(self.root/'model.safetensors')).items()}

    def replace_saved(self, values):
        temp = self.root/'candidate.safetensors'
        save_file(values, str(temp), metadata={'format': 'pt'})
        restored = load_file(str(temp))
        self.assertEqual(set(restored), set(values))
        self.assertTrue(all(torch.equal(restored[k], v) for k, v in values.items()))
        temp.replace(self.root/'model.safetensors')

    def legacy(self, value=None):
        values = self.saved()
        values['embeddings.position_ids'] = (self.model.embeddings.position_ids.clone() if value is None else value)
        self.replace_saved(values)

    def snapshot(self):
        return {'kind': 'encoder', 'revision': 'a'*40,
                'files': {p.name: c.file_sha(p) for p in self.root.iterdir() if p.is_file()}}

    def test_original_state_only_snapshot_still_loads_without_exemption(self):
        backend = LocalEncoder(self.root, self.snapshot(), 32)
        self.assertEqual(backend.verified_legacy_buffers, [])
        self.assertEqual(parameters(backend.loaded), parameters(self.model))
        backend.close()

    def test_legacy_buffer_is_verified_instead_of_silently_ignored(self):
        self.legacy()
        before = self.snapshot()
        backend = LocalEncoder(self.root, before, 32)
        self.assertEqual(parameters(backend.loaded), parameters(self.model))
        self.assertEqual(len(backend.verified_legacy_buffers), 1)
        row = backend.verified_legacy_buffers[0]
        self.assertEqual(row['name'], 'embeddings.position_ids')
        self.assertEqual(row['shape'], [1, 32])
        self.assertEqual(row['saved_and_materialized_tensor_sha256'], tensor_digest(self.model.embeddings.position_ids))
        self.assertTrue(row['saved_and_materialized_equal'])
        self.assertNotIn('embeddings.position_ids', backend.loaded.state_dict())
        backend.close()
        self.assertEqual(self.snapshot(), before)

    def test_legacy_loaded_forward_matches_original_stock_model(self):
        self.legacy()
        backend = LocalEncoder(self.root, self.snapshot(), 32)
        texts = ['hello world', 'small text .']
        tokens = self.tokenizer(texts, padding=True, return_tensors='pt')
        with torch.no_grad():
            hidden = self.model(**tokens).last_hidden_state
            mask = tokens['attention_mask'].unsqueeze(-1).to(hidden.dtype)
            expected = (hidden*mask).sum(1)/mask.sum(1)
        observed = backend.encode(texts)
        self.assertTrue(torch.allclose(observed, expected, atol=1e-6, rtol=1e-6))
        self.assertEqual(backend.forward_calls, 1)

    def test_changed_saved_positions_are_rejected_even_with_new_file_pin(self):
        value = self.model.embeddings.position_ids.clone(); value[0, 4] = 7
        self.legacy(value)
        with self.assertRaisesRegex(InputError, 'legacy position buffer differs'):
            LocalEncoder(self.root, self.snapshot(), 32)

    def test_saved_integer_width_is_not_silently_converted(self):
        self.legacy(self.model.embeddings.position_ids.to(torch.int32))
        with self.assertRaises(InputError): LocalEncoder(self.root, self.snapshot(), 32)

    def test_same_values_with_flat_shape_are_rejected(self):
        self.legacy(self.model.embeddings.position_ids.flatten().clone())
        with self.assertRaises(InputError): LocalEncoder(self.root, self.snapshot(), 32)

    def test_unrecognized_saved_buffer_is_not_an_ignored_tensor_allowlist(self):
        values = self.saved(); values['embeddings.token_type_ids'] = self.model.embeddings.token_type_ids.clone()
        self.replace_saved(values)
        with self.assertRaises(InputError): LocalEncoder(self.root, self.snapshot(), 32)

    def test_duplicate_legacy_entry_in_second_file_is_rejected(self):
        self.legacy()
        save_file({'embeddings.position_ids': self.model.embeddings.position_ids.clone()},
                  str(self.root/'extra.safetensors'), metadata={'format': 'pt'})
        with self.assertRaisesRegex(InputError, 'duplicate saved tensor'):
            LocalEncoder(self.root, self.snapshot(), 32)

    def test_missing_learned_weight_is_still_rejected(self):
        self.legacy()
        values = self.saved(); values.pop('pooler.dense.weight')
        self.replace_saved(values)
        with self.assertRaisesRegex(InputError, 'incomplete model load'):
            LocalEncoder(self.root, self.snapshot(), 32)

    def test_unexpected_learned_head_is_not_discarded(self):
        values = self.saved(); values['classifier.weight'] = torch.zeros(2, 12)
        self.replace_saved(values)
        with self.assertRaises(InputError): LocalEncoder(self.root, self.snapshot(), 32)

    def test_saved_and_live_equal_but_shifted_positions_are_rejected(self):
        with torch.no_grad(): self.model.embeddings.position_ids.add_(1)
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'embeddings.position_ids', self.model.embeddings.position_ids.clone())

    def test_changed_live_buffer_is_not_repaired_by_verification(self):
        saved = self.model.embeddings.position_ids.clone()
        with torch.no_grad(): self.model.embeddings.position_ids[0, 0] = 9
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'embeddings.position_ids', saved)
        self.assertEqual(int(self.model.embeddings.position_ids[0, 0]), 9)

    def test_rule_does_not_apply_to_other_model_classes(self):
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(torch.nn.Linear(2, 2), 'embeddings.position_ids', torch.arange(32).unsqueeze(0))

    def test_rule_requires_actual_nonpersistent_buffer(self):
        self.model.embeddings._non_persistent_buffers_set.discard('position_ids')
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'embeddings.position_ids', self.model.embeddings.position_ids.clone())

    def test_rule_rejects_wrong_key_and_missing_live_buffer(self):
        saved = self.model.embeddings.position_ids.clone()
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'other.position_ids', saved)
        self.model.embeddings._buffers.pop('position_ids')
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'embeddings.position_ids', saved)

    def test_rule_requires_configured_position_capacity(self):
        self.model.config.max_position_embeddings = 16
        with self.assertRaises(InputError):
            verified_legacy_position_buffer(self.model, 'embeddings.position_ids', self.model.embeddings.position_ids.clone())

    def test_snapshot_identity_still_binds_exact_original_bytes(self):
        self.legacy()
        manifest = self.snapshot()
        values = self.saved(); values['embeddings.position_ids'][0, 0] = 1
        self.replace_saved(values)
        with self.assertRaisesRegex(InputError, 'snapshot content drift'):
            LocalEncoder(self.root, manifest, 32)


if __name__ == '__main__':
    unittest.main()
