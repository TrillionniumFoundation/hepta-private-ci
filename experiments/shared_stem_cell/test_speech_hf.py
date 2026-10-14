"""Mandatory stock-HF shared-state/ordinary generate parity; random, not efficacy."""
from copy import deepcopy
import unittest

import torch
from transformers import WhisperConfig, WhisperForConditionalGeneration
from experiments.shared_stem_cell import speech_control as c


class SpeechHfTests(unittest.TestCase):
    def test_actual_native_decoder_matches_full_generate_without_second_encoder(self):
        torch.set_num_threads(1)
        torch.manual_seed(17)
        config = WhisperConfig(vocab_size=32, d_model=8, encoder_layers=1, decoder_layers=1,
            encoder_attention_heads=2, decoder_attention_heads=2, encoder_ffn_dim=16,
            decoder_ffn_dim=16, max_source_positions=1500, max_target_positions=64,
            pad_token_id=0, bos_token_id=1, eos_token_id=2, decoder_start_token_id=1,
            suppress_tokens=[], begin_suppress_tokens=[])
        config._attn_implementation = "eager"
        model = WhisperForConditionalGeneration(config).eval().requires_grad_(False)
        model.generation_config.no_timestamps_token_id = 3
        model.generation_config.is_multilingual = False
        model.generation_config.forced_decoder_ids = None
        features = torch.zeros(1, 80, 3000)
        encoder_calls = []
        hook = model.model.encoder.register_forward_hook(lambda *args: encoder_calls.append(1))
        try:
            with torch.no_grad(): hidden = model.model.encoder(input_features=features).last_hidden_state
            class Tokenizer:
                def decode(self, tokens, **kwargs): return "zero"
            result = c.decode_shared(model, Tokenizer(), hidden.clone())
            self.assertEqual(len(encoder_calls), 1)
            cfg = deepcopy(model.generation_config)
            cfg.do_sample = False; cfg.num_beams = 1; cfg.num_return_sequences = 1
            cfg.max_new_tokens = c.MAX_NEW_TOKENS; cfg.return_dict_in_generate = True
            cfg.output_scores = False; cfg.output_attentions = False; cfg.output_hidden_states = False
            with torch.no_grad():
                direct = model.generate(input_features=features, generation_config=cfg,
                    return_timestamps=False, temperature=0.0, condition_on_prev_tokens=False,
                    compression_ratio_threshold=None, logprob_threshold=None, no_speech_threshold=None,
                    force_unique_generate_call=True)
            self.assertEqual(len(encoder_calls), 2)
            self.assertEqual(result["token_ids"], direct.sequences[0].tolist())
            self.assertGreater(result["decoder_forwards"], 0)
        finally:
            hook.remove()


if __name__ == "__main__": unittest.main()
