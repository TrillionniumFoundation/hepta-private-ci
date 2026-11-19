"""Real tensor serialization / loader wiring fixtures, NOT pretrained evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch
from torch import nn
from safetensors.torch import save_file

from hf_complete_checkpoint import ENCODER_PROFILE, checked_config, verify_full_mlm
from hf_encoder_kernel import snapshot_digest, verify_loaded_safetensors
from matrix_materials import freeze_config, validate_config
from matrix_runtime import LocalHFEncoder
from matrix_test_support import setup


def loading_info():
    return dict(missing_keys=[], unexpected_keys=[], mismatched_keys=[], error_msgs=[])


def tiny_config():
    return dict(model_type='modernbert', architectures=['ModernBertForMaskedLM'],
                tie_word_embeddings=True, hidden_size=4, intermediate_size=8,
                num_hidden_layers=1, num_attention_heads=2, vocab_size=16,
                max_position_embeddings=512)


class TinyBase(nn.Module):
    def __init__(self):
        super().__init__()
        self.embeddings = nn.Module()
        self.embeddings.tok_embeddings = nn.Embedding(16, 4)
        self.config = SimpleNamespace(**tiny_config())
        self.calls = 0

    def forward(self, input_ids, attention_mask):
        self.calls += 1
        return SimpleNamespace(last_hidden_state=self.embeddings.tok_embeddings(input_ids))


class TinyMLM(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = TinyBase()
        self.config = self.model.config
        self.head = nn.Linear(4, 4)
        self.decoder = nn.Linear(4, 16, bias=False)
        self.decoder.weight = self.model.embeddings.tok_embeddings.weight


class CompleteCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = TinyMLM()
        (self.root / 'config.json').write_text(json.dumps(tiny_config()))
        self.save()

    def save(self, omit=('decoder.weight',)):
        tensors = {k: v.clone() for k, v in self.model.state_dict().items() if k not in omit}
        save_file(tensors, str(self.root / 'model.safetensors'))

    def test_default_profile_remains_strict_about_missing_keys(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            verify_loaded_safetensors(torch, self.model, self.root)

    def test_physical_tie_accounts_for_omitted_alias_without_discarding_head(self):
        info = loading_info(); info['missing_keys'] = ['decoder.weight']
        loaded, report = verify_full_mlm(torch, self.model, self.root, info)
        self.assertEqual(loaded['reported_missing_keys'], ['decoder.weight'])
        self.assertEqual(report['omitted_tied_keys'], ['decoder.weight'])
        self.assertTrue(report['all_state_dict_tensors_accounted'])
        self.assertFalse(report['all_state_dict_tensors_compared'])
        self.assertEqual(report['tensor_count'], 3)  # embedding + Head weight/bias

    def test_equal_copy_is_not_a_physical_alias(self):
        self.model.decoder.weight = nn.Parameter(self.model.decoder.weight.detach().clone())
        with self.assertRaisesRegex(ValueError, 'physical view'):
            verify_full_mlm(torch, self.model, self.root, loading_info())

    def test_same_storage_but_different_view_rejects(self):
        self.model.decoder.weight = nn.Parameter(self.model.decoder.weight.detach().T)
        with self.assertRaisesRegex(ValueError, 'physical view'):
            verify_full_mlm(torch, self.model, self.root, loading_info())

    def test_missing_prediction_head_is_not_waived(self):
        self.save(omit=('decoder.weight', 'head.bias'))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            verify_full_mlm(torch, self.model, self.root, loading_info())

    def test_both_tied_keys_on_disk_must_match(self):
        self.save(omit=())
        _, report = verify_full_mlm(torch, self.model, self.root, loading_info())
        self.assertEqual(report['omitted_tied_keys'], [])
        tensors = {k: v.clone() for k, v in self.model.state_dict().items()}
        tensors['decoder.weight'].add_(1)
        save_file(tensors, str(self.root / 'model.safetensors'))
        with self.assertRaisesRegex(ValueError, 'differs'):
            verify_full_mlm(torch, self.model, self.root, loading_info())

    def test_loading_errors_not_hidden_by_valid_tensor_inventory(self):
        for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs'):
            info = loading_info(); info[key] = ['head.weight']
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_full_mlm(torch, self.model, self.root, info)

    def test_unregistered_alias_or_chains_reject(self):
        for aliases in ({'decoder.weight': 'decoder.weight'},
                        {'decoder.weight': 'absent'},
                        {'decoder.weight': 'head.weight', 'head.weight': 'decoder.weight'}):
            with self.subTest(aliases=aliases), self.assertRaises(ValueError):
                verify_loaded_safetensors(torch, self.model, self.root, tied_aliases=aliases)

    def test_preflight_config_bounds_reject_before_model_instantiation(self):
        for key, value in (('hidden_size', True), ('vocab_size', 10**9),
                           ('architectures', ['OtherModel']), ('tie_word_embeddings', False)):
            cfg = tiny_config(); cfg[key] = value
            (self.root / 'config.json').write_text(json.dumps(cfg))
            with self.subTest(key=key), self.assertRaises(ValueError): checked_config(self.root)
        (self.root / 'config.json').write_text(json.dumps(tiny_config()))
        self.assertEqual(checked_config(self.root)['hidden_size'], 4)

    def test_raw_bin_is_never_a_loading_fallback(self):
        (self.root / 'model.safetensors').unlink()
        (self.root / 'pytorch_model.bin').write_bytes(b'not unpickled')
        with self.assertRaisesRegex(ValueError, 'safetensors'):
            checked_config(self.root)

    def test_config_v3_is_explicit_and_old_configs_still_validate(self):
        p, c, cfg, _ = setup('small_stem_matched_head_no_ndu')
        original = copy.deepcopy(cfg)
        validate_config(p, c, cfg)
        kwargs = {k:v for k,v in cfg.items() if k not in ('schema','config_id','contract_id')}
        upgraded = freeze_config(p, c, **kwargs, encoder_profile=ENCODER_PROFILE)
        self.assertEqual(upgraded['schema'], 'hepta.stem.bound-hf-config.v3')
        self.assertNotEqual(upgraded['config_id'], cfg['config_id'])
        validate_config(p, c, upgraded)
        self.assertEqual(original, cfg)
        upgraded['encoder_profile'] = None
        with self.assertRaises(ValueError): validate_config(p, c, upgraded)

    def test_loader_reuses_base_without_executing_retained_mlm_head(self):
        # Stub only the absent Transformers loader; all weights and forwards are real PyTorch.
        def auto_config(*args, **kwargs): return self.model.config
        def load(*args, **kwargs):
            self.assertTrue(kwargs['local_files_only'])
            self.assertFalse(kwargs['trust_remote_code'])
            self.assertTrue(kwargs['use_safetensors'])
            return self.model, loading_info()
        def tokenize(*args, **kwargs):
            return dict(input_ids=torch.tensor([[1, 2, 3]]), attention_mask=torch.ones(1, 3, dtype=torch.long))
        fake = SimpleNamespace(__version__='4.57.1',
            AutoConfig=SimpleNamespace(from_pretrained=auto_config),
            AutoModelForMaskedLM=SimpleNamespace(from_pretrained=load),
            AutoModel=SimpleNamespace(from_pretrained=lambda *a, **k: self.fail('must load full MLM')),
            AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: tokenize))
        p, c, cfg, _ = setup('small_stem_matched_head_no_ndu')
        values = {k:v for k,v in cfg.items() if k not in ('schema','config_id','contract_id')}
        values['snapshot_sha256'] = snapshot_digest(self.root)
        cfg = freeze_config(p, c, **values, encoder_profile=ENCODER_PROFILE)
        with patch.dict('sys.modules', {'transformers': fake}):
            encoder = LocalHFEncoder(self.root, cfg, validate_config(p, c, cfg))
        hook = self.model.head.register_forward_pre_hook(lambda *a: self.fail('MLM head executed'))
        self.addCleanup(hook.remove)
        vector, length = encoder.encode(dict(state='x', question='q', options=['a','b']))
        self.assertEqual((vector.shape, length), (torch.Size([4]), 3))
        self.assertEqual(self.model.model.calls, 1)
        self.assertIs(encoder.checkpoint_model, self.model)
        self.assertGreater(encoder.weight_bytes, 16*4*4)
        self.assertFalse(any(p.requires_grad for p in self.model.parameters()))
        with torch.no_grad(): self.model.head.bias.add_(1)
        with self.assertRaises(ValueError): encoder.reverify()


if __name__ == '__main__':
    unittest.main()
