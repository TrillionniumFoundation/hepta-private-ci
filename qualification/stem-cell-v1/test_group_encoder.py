"""Offline encoder admission tests: no torch/HF installation or download needed."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import group_encoder as encoder
from group_features import FeatureCache, content_digest


class Tensor:
    def __init__(self, values):
        self.values = deepcopy(values)
        cursor, shape = values, []
        while isinstance(cursor, list):
            shape.append(len(cursor))
            cursor = cursor[0] if cursor else None
        self.shape = tuple(shape)
        self.ndim = len(shape)

    def __getitem__(self, index):
        return Tensor(self.values[index])

    def detach(self):
        return self

    def clone(self):
        return Tensor(self.values)

    def cpu(self):
        return self

    def tolist(self):
        return deepcopy(self.values)


class OfflineEncoderTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in encoder.FILES:
            (self.root / name).write_bytes(name.encode())
        material = dict(model_id=encoder.MODEL_ID, revision=encoder.REVISION,
                        sha256={n: encoder.file_digest(self.root / n) for n in encoder.FILES})
        (self.root / "material.json").write_text(json.dumps(material))
        self.tokenizer = Mock(return_value={"input_ids": Tensor([[1, 2]]),
                                            "attention_mask": Tensor([[1, 1]])})
        self.model = Mock()
        self.model.training = False
        self.model.parameters.return_value = [SimpleNamespace(requires_grad=False)]
        self.model.eval.return_value = self.model
        self.model.requires_grad_.return_value = self.model
        self.model.return_value = SimpleNamespace(last_hidden_state=Tensor([[[0.1] * 384, [0.2] * 384]]))
        self.info = {n: [] for n in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")}
        torch = ModuleType("torch")
        torch.float32, torch.no_grad = "fp32", nullcontext
        transformers = ModuleType("transformers")
        transformers.__version__ = "4.57.1"
        transformers.AutoConfig = SimpleNamespace(from_pretrained=Mock(return_value=SimpleNamespace(
            model_type="modernbert", hidden_size=384, reference_compile=True)))
        transformers.AutoModel = SimpleNamespace(from_pretrained=Mock(return_value=(self.model, self.info)))
        transformers.AutoTokenizer = SimpleNamespace(from_pretrained=Mock(return_value=self.tokenizer))
        self.transformers = transformers
        modules = patch.dict(sys.modules, {"torch": torch, "transformers": transformers})
        modules.start()
        self.addCleanup(modules.stop)
        verification = patch.object(encoder, "verify_loaded_safetensors", return_value={"complete": True})
        self.verification = verification.start()
        self.addCleanup(verification.stop)

    def test_pinned_local_load_freeze_and_reuse(self):
        loaded = encoder.FrozenTokenEncoder(self.root)
        self.model.eval.assert_called_once_with()
        self.model.requires_grad_.assert_called_once_with(False)
        kwargs = self.transformers.AutoModel.from_pretrained.call_args.kwargs
        self.assertEqual((kwargs["local_files_only"], kwargs["trust_remote_code"],
                          kwargs["use_safetensors"], kwargs["attn_implementation"]),
                         (True, False, True, "eager"))
        ref = loaded.identity("real input", scope="episode", generation=1)
        cache = FeatureCache("episode", 1)
        first = cache.get_or_encode(ref, lambda: loaded.encode("real input", ref))
        second = cache.get_or_encode(ref, lambda: loaded.encode("real input", ref))
        self.assertIs(first, second)
        self.assertEqual((first.shape, first.positions, loaded.calls), ((2, 384), ((0.0,), (1.0,)), 1))
        self.model.assert_called_once()
        self.tokenizer.assert_called_once_with("real input", return_tensors="pt", truncation=False)

    def test_rejects_partial_load_without_fallback(self):
        self.info["missing_keys"].append("randomly_initialized.weight")
        with self.assertRaisesRegex(ValueError, "partially initialized"):
            encoder.FrozenTokenEncoder(self.root)
        self.transformers.AutoModel.from_pretrained.assert_called_once()
        self.transformers.AutoTokenizer.from_pretrained.assert_not_called()
        self.verification.assert_not_called()

    def test_rejects_exact_weight_mismatch_without_fallback(self):
        self.verification.side_effect = ValueError("loaded tensor mismatch")
        with self.assertRaisesRegex(ValueError, "tensor mismatch"):
            encoder.FrozenTokenEncoder(self.root)
        self.transformers.AutoModel.from_pretrained.assert_called_once()
        self.transformers.AutoTokenizer.from_pretrained.assert_not_called()

    def test_rejects_disk_mutation_before_model_load(self):
        (self.root / "model.safetensors").write_bytes(b"changed checkpoint")
        with self.assertRaisesRegex(ValueError, "content changed"):
            encoder.FrozenTokenEncoder(self.root)
        self.transformers.AutoConfig.from_pretrained.assert_not_called()

    def test_binds_actual_text_and_preprocessing_before_forward(self):
        loaded = encoder.FrozenTokenEncoder(self.root)
        ref = loaded.identity("original input", scope="episode", generation=1)
        for text, identity in (("different input", ref),
                               ("original input", replace(ref, preprocess_digest=content_digest(b"other preprocessing")))):
            with self.assertRaisesRegex(ValueError, "actual encoder input"):
                loaded.encode(text, identity)
        self.model.assert_not_called()
        self.tokenizer.assert_not_called()

    def test_no_silent_truncation_or_forward_on_excess_evidence(self):
        loaded = encoder.FrozenTokenEncoder(self.root, max_tokens=1)
        ref = loaded.identity("long evidence", scope="episode", generation=1)
        with self.assertRaisesRegex(ValueError, "no silent evidence truncation"):
            loaded.encode("long evidence", ref)
        self.assertEqual(loaded.calls, 0)
        self.tokenizer.assert_called_once_with("long evidence", return_tensors="pt", truncation=False)
        self.model.assert_not_called()

    def test_rejects_noninteger_token_limits_and_wrong_architecture(self):
        for limit in (True, 1.5, 0, 257):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                encoder.FrozenTokenEncoder(self.root, max_tokens=limit)
        self.transformers.AutoConfig.from_pretrained.return_value.hidden_size = 128
        with self.assertRaisesRegex(ValueError, "architecture"):
            encoder.FrozenTokenEncoder(self.root)
        self.transformers.AutoModel.from_pretrained.assert_not_called()

    def test_rejects_bad_batch_missing_mask_and_misaligned_tokens(self):
        loaded = encoder.FrozenTokenEncoder(self.root)
        ref = loaded.identity("evidence", scope="episode", generation=1)
        for malformed in (None, {"input_ids": Tensor([[1, 2]])},
                          {"input_ids": Tensor([[1], [2]]), "attention_mask": Tensor([[1], [1]])},
                          {"input_ids": Tensor([[1, 2]]), "attention_mask": Tensor([[1]])},
                          {"input_ids": Tensor([1, 2]), "attention_mask": Tensor([1, 1])}):
            self.tokenizer.return_value = malformed
            with self.subTest(tokens=malformed), self.assertRaisesRegex(ValueError, "aligned"):
                loaded.encode("evidence", ref)
        self.model.assert_not_called()

    def test_rejects_output_width_batch_and_token_count_mismatch(self):
        loaded = encoder.FrozenTokenEncoder(self.root)
        ref = loaded.identity("evidence", scope="episode", generation=1)
        for values in ([[[0.1] * 383] * 2], [[[0.1] * 384] * 2] * 2, [[[0.1] * 384]]):
            self.model.return_value = SimpleNamespace(last_hidden_state=Tensor(values))
            with self.subTest(shape=Tensor(values).shape), self.assertRaisesRegex(ValueError, "geometry"):
                loaded.encode("evidence", ref)
        self.assertEqual(loaded.calls, 0)

    def test_rejects_unfrozen_or_training_encoder_before_forward(self):
        loaded = encoder.FrozenTokenEncoder(self.root)
        ref = loaded.identity("evidence", scope="episode", generation=1)
        for training, requires_grad in ((True, False), (False, True)):
            self.model.training = training
            self.model.parameters.return_value = [SimpleNamespace(requires_grad=requires_grad)]
            with self.assertRaisesRegex(ValueError, "not frozen"):
                loaded.encode("evidence", ref)
        self.model.assert_not_called()
        self.tokenizer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
