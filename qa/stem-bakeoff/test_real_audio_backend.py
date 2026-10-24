"""Regression for official EG2/Gemma4 audio attention dispatch, not quality."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from real_encoder import CANDIDATES, FrozenRealEncoder, attention_implementation
from teacher_snapshot import inventory


class RealAudioBackendTests(unittest.TestCase):
    def test_real_audio_tower_load_uses_eager_without_changing_text_attention(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import (AutoModel, EmbeddingGemma2Config, EmbeddingGemma2TextConfig,
                                  Gemma4AudioConfig, PreTrainedTokenizerFast)
        text_config = EmbeddingGemma2TextConfig(vocab_size=16, hidden_size=8,
            intermediate_size=16, num_hidden_layers=1, num_attention_heads=2,
            num_key_value_heads=1, head_dim=4, global_head_dim=4,
            hidden_size_per_layer_input=8, embedding_dim=8, layer_types=["full_attention"])
        audio_config = Gemma4AudioConfig(hidden_size=8, num_hidden_layers=1,
            num_attention_heads=2, subsampling_conv_channels=[8, 2], output_proj_dims=8)
        config = EmbeddingGemma2Config(text_config=text_config, audio_config=audio_config,
            vision_config=None, image_token_id=12, audio_token_id=13, video_token_id=14)
        dispatch = attention_implementation("embeddinggemma2_740m", "text_audio")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = AutoModel.from_config(config, attn_implementation=dispatch)
            model.save_pretrained(root)
            tokenizer = Tokenizer(models.WordLevel({"[PAD]": 0, "[UNK]": 1, "A": 2},
                                                   unk_token="[UNK]"))
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="[PAD]",
                                    unk_token="[UNK]").save_pretrained(root)
            data = inventory(root)
            weight_hash = next(x["sha256"] for x in data["entries"]
                               if x["path"] == "model.safetensors")
            with patch.dict(CANDIDATES["embeddinggemma2_740m"],
                            {"weight_sha256": weight_hash, "width": 8}):
                owner = FrozenRealEncoder(candidate="embeddinggemma2_740m", snapshot=root,
                    revision=CANDIDATES["embeddinggemma2_740m"]["revision"],
                    expected_inventory_sha256=data["inventory_sha256"],
                    operator_accepted_terms=True, profile="text_audio")
            self.assertEqual(owner._model.audio_tower.config._attn_implementation, "eager")
            self.assertEqual(owner._model.config.text_config._attn_implementation, "sdpa")
            self.assertEqual(owner.accounting["trainable_parameter_count"], 0)
            with torch.inference_mode():
                audio = owner._model.audio_tower(input_features=torch.ones(1, 32, 8),
                    input_features_mask=torch.ones(1, 32, dtype=torch.bool)).last_hidden_state
            self.assertEqual(tuple(audio.shape), (1, 8, 8))
            self.assertTrue(bool(torch.isfinite(audio).all()))
            self.assertIsNotNone(owner.encode_text(["A"]).read_global())
            self.assertEqual(owner.last_receipt["model_forward_calls"], 1)
        self.assertEqual(attention_implementation("granite97m", "text"), "sdpa")
        self.assertEqual(attention_implementation("embeddinggemma2_740m", "text_image"), "sdpa")


if __name__ == "__main__":
    unittest.main()
