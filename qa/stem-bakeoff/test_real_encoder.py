"""Behavioral checks; these small fixtures are not model quality evidence."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file, save_file

from convert_mmbert import COPY_FILES, convert_mmbert
from real_encoder import (CANDIDATES, FrozenRealEncoder, RealEncoderError, physical_model_accounting,
                          pool_features, source_digests, verify_real_snapshot)
from teacher_snapshot import inventory


class RealEncoderTests(unittest.TestCase):
    def test_local_transformers_owner_shares_one_forward_and_rejects_unfreeze(self):
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import ModernBertConfig, ModernBertModel, PreTrainedTokenizerFast
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ModernBertConfig(vocab_size=8, hidden_size=8, intermediate_size=16,
                                      num_hidden_layers=1, num_attention_heads=2,
                                      pad_token_id=0, cls_token_id=1, sep_token_id=2,
                                      bos_token_id=1, eos_token_id=2)
            ModernBertModel(config).save_pretrained(root)
            tokenizer = Tokenizer(models.WordLevel({"[PAD]": 0, "[UNK]": 1, "A": 2, "B": 3},
                                                   unk_token="[UNK]"))
            tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
            PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="[PAD]",
                                   unk_token="[UNK]").save_pretrained(root)
            data = inventory(root)
            weight_hash = next(x["sha256"] for x in data["entries"] if x["path"] == "model.safetensors")
            with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": weight_hash, "width": 8}):
                owner = FrozenRealEncoder(candidate="granite97m", snapshot=root,
                                           revision=CANDIDATES["granite97m"]["revision"],
                                           expected_inventory_sha256=data["inventory_sha256"],
                                           operator_accepted_terms=True)
                features = owner.encode_text(["A B", "A"])
                self.assertEqual(tuple(features.read_global().shape), (2, 8))
                self.assertEqual(owner.last_receipt["model_forward_calls"], 1)
                self.assertEqual(owner.last_receipt["trainable_parameter_count"], 0)
                owner._model.train()
                with self.assertRaises(RealEncoderError):
                    owner.encode_text(["A"])
            weights = load_file(str(root / "model.safetensors"))
            del weights["embeddings.tok_embeddings.weight"]
            save_file(weights, str(root / "model.safetensors"), metadata={"format": "pt"})
            changed = inventory(root)
            weight_hash = next(x["sha256"] for x in changed["entries"] if x["path"] == "model.safetensors")
            with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": weight_hash, "width": 8}):
                with self.assertRaisesRegex(RealEncoderError, "fully initialize"):
                    FrozenRealEncoder(candidate="granite97m", snapshot=root,
                                      revision=CANDIDATES["granite97m"]["revision"],
                                      expected_inventory_sha256=changed["inventory_sha256"],
                                      operator_accepted_terms=True)

    def test_pooling_preserves_official_cls_and_excludes_padding(self):
        tokens = torch.tensor([[[3., 4.], [0., 5.], [1000., 1000.]]])
        mask = torch.tensor([[1, 1, 0]])
        torch.testing.assert_close(pool_features(tokens, mask, "cls"), torch.tensor([[.6, .8]]))
        expected = torch.nn.functional.normalize(torch.tensor([[1.5, 4.5]]), dim=-1)
        torch.testing.assert_close(pool_features(tokens, mask, "mean"), expected)
        with self.assertRaises(RealEncoderError):
            pool_features(tokens, torch.zeros_like(mask), "mean")
        tokens[0, 1, 0] = float("nan")
        with self.assertRaises(RealEncoderError):
            pool_features(tokens, mask, "cls")

    def test_physical_storage_counts_alias_once(self):
        model = torch.nn.Module()
        model.register_parameter("weight", torch.nn.Parameter(torch.ones(12)))
        model.register_buffer("alias", model.weight.detach().view(3, 4))
        model.requires_grad_(False)
        self.assertEqual(physical_model_accounting(model), {
            "loaded_parameter_count": 12, "trainable_parameter_count": 0,
            "resident_tensor_storage_bytes": 48, "resident_storage_count": 1})

    def test_source_identity_binds_actual_text_and_metadata(self):
        source = {"publisher": "example", "story_id": "7"}
        self.assertNotEqual(source_digests(["A"], [source]), source_digests(["B"], [source]))
        self.assertEqual(source_digests(["A"], [source]),
                         source_digests(["A"], [{"story_id": "7", "publisher": "example"}]))
        with self.assertRaises(RealEncoderError):
            source_digests(["A"], [{"text": "B"}])
        with self.assertRaises(RealEncoderError):
            source_digests(["A"], [{"timestamp": float("nan")}])

    def test_changed_weights_rejected_even_with_new_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text('{"model_type":"modernbert"}')
            save_file({"weight": torch.ones(2)}, str(root / "model.safetensors"))
            original = inventory(root)
            weight_hash = next(x["sha256"] for x in original["entries"] if x["path"] == "model.safetensors")
            with patch.dict(CANDIDATES["granite97m"], {"weight_sha256": weight_hash}):
                revision = CANDIDATES["granite97m"]["revision"]
                verify_real_snapshot(root, "granite97m", revision, original["inventory_sha256"], True)
                save_file({"weight": torch.zeros(2)}, str(root / "model.safetensors"))
                changed = inventory(root)["inventory_sha256"]
                with self.assertRaises(RealEncoderError):
                    verify_real_snapshot(root, "granite97m", revision, changed, True)

    def test_weights_only_conversion_preserves_alias_values_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "derived"
            source.mkdir()
            for name in COPY_FILES:
                (source / name).write_text('{"model_type":"modernbert"}')
            tensor = torch.arange(8, dtype=torch.float32)
            torch.save({"embedding": tensor, "decoder": tensor}, source / "pytorch_model.bin")
            digest = hashlib.sha256((source / "pytorch_model.bin").read_bytes()).hexdigest()
            spec = CANDIDATES["mmbert_small"]
            with patch.dict(spec, {"upstream_bin_sha256": digest}):
                receipt = convert_mmbert(source=source, output=output, revision=spec["revision"],
                                         expected_inventory_sha256=inventory(source)["inventory_sha256"],
                                         operator_accepted_terms=True)
                result = load_file(str(output / "model.safetensors"))
                torch.testing.assert_close(result["embedding"], tensor)
                torch.testing.assert_close(result["decoder"], tensor)
                verify_real_snapshot(output, "mmbert_small", spec["revision"],
                                     receipt["output_inventory_sha256"], True)
                data = json.loads((output / "conversion_receipt.json").read_text())
                data["weights_only"] = False
                (output / "conversion_receipt.json").write_text(json.dumps(data))
                with self.assertRaises(RealEncoderError):
                    verify_real_snapshot(output, "mmbert_small", spec["revision"],
                                         inventory(output)["inventory_sha256"], True)


if __name__ == "__main__":
    unittest.main()
