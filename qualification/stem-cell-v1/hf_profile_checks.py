"""REQUIRED separate installed-Transformers tests; never silently skipped.

Locally generated miniature architecture weights are NOT pretrained evidence.
The standard library-only/torch suite does not import this optional dependency.
"""
import tempfile
import unittest
from pathlib import Path

import torch
from transformers import ModernBertConfig, ModernBertForMaskedLM, PreTrainedTokenizerFast
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from hf_complete_checkpoint import load_complete_mlm, ENCODER_PROFILE
from hf_encoder_kernel import snapshot_digest
from matrix_materials import freeze_config
from matrix_runtime import LocalHFEncoder, execute
from matrix_test_support import setup
from public_encoder_probe import probe


class InstalledHFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = ModernBertConfig(vocab_size=32, hidden_size=8, intermediate_size=16,
            num_hidden_layers=2, num_attention_heads=2, max_position_embeddings=512,
            local_attention=16, global_attn_every_n_layers=2,
            pad_token_id=0, bos_token_id=1, eos_token_id=2, reference_compile=False)
        config._attn_implementation = 'eager'
        self.model = ModernBertForMaskedLM(config).eval()
        self.model.save_pretrained(self.root, safe_serialization=True)
        vocabulary = {s:i for i,s in enumerate(('[PAD]','[BOS]','[EOS]','[UNK]',
            'The','engineer','repaired','electric','motor','A','garden','contains','green',
            'plants','red','flowers','Identify','subject','person','place','1','2','left','right'))}
        tokenizer = Tokenizer(WordLevel(vocabulary, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = Whitespace()
        fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token='[UNK]',
                                       pad_token='[PAD]', bos_token='[BOS]', eos_token='[EOS]',
                                       model_input_names=['input_ids', 'attention_mask'])
        fast.model_input_names = ['input_ids', 'attention_mask']
        fast.save_pretrained(self.root)

    def test_full_stock_architecture_roundtrip_and_physical_tie(self):
        full, base, receipt = load_complete_mlm(self.root)
        self.assertIs(full.decoder.weight, base.embeddings.tok_embeddings.weight)
        self.assertTrue(receipt['materialization']['all_state_dict_tensors_accounted'])
        self.assertGreater(receipt['checkpoint_parameters'], receipt['feature_parameters'])
        for key, value in self.model.state_dict().items():
            torch.testing.assert_close(value, full.state_dict()[key], rtol=0, atol=0)

    def test_stock_encoder_metered_probe_without_remote_or_mlm_execution(self):
        result = probe(self.root)
        self.assertEqual(result['inference_calls'], 3)
        self.assertTrue(result['repeated_input_exact'])
        self.assertFalse(result['efficacy_established'])
        self.assertGreater(len(result['observation']['operators']), 0)

    def test_expanded_profile_counts_all_observed_work_without_changing_features(self):
        result = probe(self.root, compare_arithmetic=True)
        self.assertEqual(result['inference_calls'], 6)
        self.assertEqual(result['observation']['unknown_operators'], {})
        self.assertGreater(result['observation']['phase_flops']['inference'], 0)
        comparison = result['arithmetic_comparison']
        self.assertEqual(comparison['previous_feature_sha256'], comparison['current_feature_sha256'])
        self.assertFalse(comparison['full_system_cost_measured'])
        self.assertFalse(result['efficacy_established'])

    def test_bound_runtime_executes_stock_encoder_and_real_cell_bank(self):
        p,c,cfg,w = setup('small_stem_matched_head_no_ndu')
        values = {k:v for k,v in cfg.items() if k not in ('schema','config_id','contract_id')}
        values['snapshot_sha256'] = snapshot_digest(self.root)
        cfg = freeze_config(p,c,**values,encoder_profile=ENCODER_PROFILE)
        profile = next(a for a in p['arms'] if a['arm_id']==cfg['arm_id'])
        encoder = LocalHFEncoder(self.root,cfg,profile)
        _, result, predictions = execute(p,c,cfg,w,encoder,clock=lambda:25)
        self.assertEqual([r['status'] for r in predictions],['completed','completed'])
        self.assertEqual(result['inventory']['cells'],16)
        self.assertNotEqual(result['initial_bank_sha256'],result['trained_bank_sha256'])
        self.assertFalse(result['independent_success_established'])


if __name__ == '__main__':
    torch.set_num_threads(1)
    unittest.main()
