"""Required hosted stock-HF API checks with small RANDOM models, never efficacy.

This module deliberately requires Transformers instead of skipping its absence.
It is run by the pretrained lane before acquiring real public checkpoint bytes.
"""
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from PIL import Image
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
import torch
from transformers import (
    CLIPConfig, CLIPImageProcessor, CLIPModel, CLIPProcessor, CLIPTextConfig,
    CLIPTokenizer, CLIPVisionConfig, ModernBertConfig, ModernBertForMaskedLM,
    PreTrainedTokenizerFast, WhisperConfig, WhisperFeatureExtractor,
    WhisperForConditionalGeneration, LlamaConfig, LlamaForCausalLM,
)

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import media_execution as m


def manifest(path, kind):
    return {"path": path.name, "kind": kind, "revision": "a" * 40,
            "files": {p.name: e.sha(p.read_bytes()) for p in path.iterdir() if p.is_file()}}


class StockHfChecks(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_stock_modernbert_full_load_and_batch_parity(self):
        path = self.root / "modernbert"
        model = ModernBertForMaskedLM(ModernBertConfig(vocab_size=8, hidden_size=8,
            intermediate_size=16, num_hidden_layers=2, num_attention_heads=2,
            max_position_embeddings=32, local_attention=16, reference_compile=False,
            pad_token_id=0, bos_token_id=1, eos_token_id=2, cls_token_id=1, sep_token_id=2))
        model.save_pretrained(path, safe_serialization=True)
        backend = Tokenizer(WordLevel({"[PAD]": 0, "[BOS]": 1, "[EOS]": 2, "[UNK]": 3,
                                      "a": 4, "b": 5, "[MASK]": 6, "c": 7}, unk_token="[UNK]"))
        backend.pre_tokenizer = Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=backend, pad_token="[PAD]", unk_token="[UNK]",
                                bos_token="[BOS]", eos_token="[EOS]", mask_token="[MASK]",
                                model_input_names=["input_ids", "attention_mask"]).save_pretrained(path)
        loaded = e.LocalEncoder(path, manifest(path, "masked_lm"), maximum_tokens=32)
        batch = loaded.encode(["a b", "b"])
        solo = torch.cat([loaded.encode([text]) for text in ("a b", "b")])
        self.assertTrue(torch.allclose(batch, solo, atol=1e-5, rtol=1e-5))
        loaded.close()

    def test_stock_causal_generator_preserves_raw_answer(self):
        path = self.root / "causal"
        LlamaForCausalLM(LlamaConfig(vocab_size=8, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
            max_position_embeddings=64, pad_token_id=0, bos_token_id=1,
            eos_token_id=2)).save_pretrained(path, safe_serialization=True)
        tokens = Tokenizer(WordLevel({"[PAD]": 0, "[BOS]": 1, "[EOS]": 2, "[UNK]": 3,
                                     "a": 4, "b": 5, "c": 6, "d": 7}, unk_token="[UNK]"))
        tokens.pre_tokenizer = Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=tokens, pad_token="[PAD]", unk_token="[UNK]",
            bos_token="[BOS]", eos_token="[EOS]",
            model_input_names=["input_ids", "attention_mask"]).save_pretrained(path)
        generator = e.LocalTextGenerator(path, manifest(path, "causal_lm"), maximum_tokens=32)
        result = generator.generate(["a b"], maximum_new_tokens=4)
        self.assertEqual(len(result["outputs"]), 1)
        self.assertLessEqual(result["outputs"][0]["generated_tokens"], 4)
        self.assertIsNone(result["semantic_quality"])
        self.assertFalse(result["production_accepted"])
        # A formatted chat already owns its special tokens: do not insert again.
        chat = "[BOS] a b [EOS]"
        expected = generator.tokenizer(chat, return_tensors="pt", add_special_tokens=False)["input_ids"]
        formatted = generator.generate([chat], maximum_new_tokens=4, add_special_tokens=False)
        self.assertEqual(formatted["outputs"][0]["input_token_sha256"], e.tensor_digest(expected))
        self.assertFalse(formatted["outputs"][0]["input_special_tokens_added"])

    def test_stock_clip_text_image_and_frame_paths(self):
        path = self.root / "clip"
        path.mkdir()
        text = CLIPTextConfig(vocab_size=4, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, max_position_embeddings=64,
            bos_token_id=0, eos_token_id=1, pad_token_id=1)
        vision = CLIPVisionConfig(hidden_size=8, intermediate_size=16, num_hidden_layers=1,
            num_attention_heads=2, image_size=8, patch_size=4)
        CLIPModel(CLIPConfig(text_config=text.to_dict(), vision_config=vision.to_dict(),
                             projection_dim=8)).save_pretrained(path, safe_serialization=True)
        (path / "vocab.json").write_text(json.dumps({"<|startoftext|>": 0, "<|endoftext|>": 1,
                                                  "a</w>": 2, "b</w>": 3}))
        (path / "merges.txt").write_text("#version: 0.2\n")
        tokenizer = CLIPTokenizer(str(path / "vocab.json"), str(path / "merges.txt"))
        CLIPProcessor(image_processor=CLIPImageProcessor(size={"shortest_edge": 8},
            crop_size={"height": 8, "width": 8}), tokenizer=tokenizer).save_pretrained(path)
        towers = m.LocalTowers(self.root, {"clip": manifest(path, "clip")})
        image = self.root / "image.png"
        Image.new("RGB", (8, 8), (12, 24, 36)).save(image)
        ref = {"path": image.name, "sha256": e.sha(image.read_bytes())}
        references = {}
        for name, item in (("text", "a b"), ("image", ref),
                           ("video", [dict(ref, timestamp_us=t) for t in (0, 1000000)])):
            value, stamps = towers.encode(name, item, self.root)
            self.assertEqual(value.ndim, 2)
            self.assertEqual(stamps.dtype, torch.int64)
            references[name] = (item, value.clone(), stamps.clone())
        self.assertEqual(towers.calls["clip"], 3)
        towers.close()
        # Reproduce the older real checkpoint's persisted, now regenerated IDs.
        # Keep ALL parameters, then demand equality with the runtime buffers.
        from safetensors.torch import save_file
        model = towers.models["clip"]
        legacy = {k: v.detach().clone() for k, v in model.state_dict().items()}
        positions = {k: v.detach().clone() for k, v in model.named_buffers() if k.endswith(".position_ids")}
        self.assertEqual(len(positions), 2)
        save_file({**legacy, **positions}, str(path / "model.safetensors"), metadata={"format": "pt"})
        restored = m.LocalTowers(self.root, {"clip": manifest(path, "clip")})
        self.assertEqual(set(restored.materializations["clip"]["verified_nonpersistent_buffers"]), set(positions))
        for name, (item, expected, stamps) in references.items():
            value, actual_stamps = restored.encode(name, item, self.root)
            self.assertTrue(torch.equal(value, expected))
            self.assertTrue(torch.equal(stamps, actual_stamps))
        restored.close()
        positions["text_model.embeddings.position_ids"][0, 0] = 1
        save_file({**legacy, **positions}, str(path / "model.safetensors"), metadata={"format": "pt"})
        with self.assertRaisesRegex(e.InputError, "nonpersistent buffer mismatch"):
            m.LocalTowers(self.root, {"clip": manifest(path, "clip")})

    def test_stock_whisper_bounded_audio_landmarks(self):
        path = self.root / "whisper"
        cfg = WhisperConfig(vocab_size=16, d_model=8, encoder_layers=1, decoder_layers=1,
            encoder_attention_heads=2, decoder_attention_heads=2, encoder_ffn_dim=16,
            decoder_ffn_dim=16, max_source_positions=1500, max_target_positions=32,
            pad_token_id=0, bos_token_id=1, eos_token_id=2, decoder_start_token_id=1,
            suppress_tokens=[], begin_suppress_tokens=[])
        WhisperForConditionalGeneration(cfg).save_pretrained(path, safe_serialization=True)
        WhisperFeatureExtractor().save_pretrained(path)
        audio = self.root / "audio.wav"
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(6400))
        audio.write_bytes(buffer.getvalue())
        towers = m.LocalTowers(self.root, {"whisper": manifest(path, "whisper")})
        value, stamps = towers.encode("audio", {"path": audio.name, "sha256": e.sha(audio.read_bytes())}, self.root)
        self.assertEqual(value.shape, (10, 8))
        self.assertEqual(stamps.tolist(), list(range(0, 200000, 20000)))
        towers.close()


if __name__ == "__main__":
    unittest.main()
