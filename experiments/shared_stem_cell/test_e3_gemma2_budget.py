"""Adversarial stdlib-only preflight tests; NO pretrained Gemma weights are run."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import e3_gemma2_budget as b


class FakeTokenizer:
    def __init__(self, *, size=12, broken=False):
        self.size = size
        self.broken = broken
        self.receipts = []

    def __call__(self, source, **opts):
        self.receipts.append((source, opts))
        if self.broken:
            return {"input_ids": [True]}
        return {"input_ids": list(range(self.size))}


class NativeBudgetContract(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "original-pinned-image"
        self.path.write_bytes(b"immutable original image bytes")
        self.tokenizer = FakeTokenizer()
        self.model = SimpleNamespace(
            max_seq_length=8192,
            tokenizer=self.tokenizer,
            prompts={"Classification": "task: classification | query: "},
            default_prompt_name="Classification",
        )

    def test_pure_text_uses_no_truncation(self):
        result = b.check_batch(self.model, ["A source-bound question"])
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["max_conservative_context_tokens"], 12)
        self.assertEqual(self.tokenizer.receipts[0][1]["truncation"], False)
        self.assertTrue(self.tokenizer.receipts[0][0].startswith("task: classification"))

    def test_exact_local_image_only(self):
        result = b.check_batch(self.model, [{"image": str(self.path)}])
        self.assertEqual(result["max_conservative_context_tokens"], 1120)
        self.assertFalse(result["image_tokens_physically_verified"])

    def test_joint_text_image_charged_once(self):
        result = b.check_batch(self.model, [{"image": str(self.path), "text": "A source"}])
        self.assertEqual(result["max_conservative_context_tokens"], 1132)
        self.assertFalse(result["production_accepted"])

    def test_max_bound_is_conservative(self):
        self.tokenizer.size = 8192 - 1120
        self.assertEqual(b.check_batch(self.model, [{"image": str(self.path), "text": "x"}])
                         ["max_conservative_context_tokens"], 8192)

    def test_joint_overflow_denied_before_encode(self):
        self.tokenizer.size = 8192 - 1120 + 1
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": str(self.path), "text": "x"}])

    def test_plain_text_overflow_denied(self):
        self.tokenizer.size = 8193
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, ["source"])

    def test_unknown_model_context_denied(self):
        self.model.max_seq_length = None
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, ["source"])

    def test_unreviewed_short_image_context_denied(self):
        self.model.max_seq_length = 1024
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": str(self.path)}])

    def test_unregistered_default_prompt_denied(self):
        self.model.default_prompt_name = "unsafe"
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, ["source"])

    def test_reserved_hidden_image_marker_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"text": "x <|image|>", "image": str(self.path)}])

    def test_remote_image_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": "https://example.com/c.png"}])

    def test_relative_image_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": "./source.png"}])

    def test_missing_or_symlink_image_denied(self):
        link = Path(self.root.name) / "symlink"
        link.symlink_to(self.path)
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": str(link)}])

    def test_parent_symlink_escape_denied(self):
        alias = Path(self.root.name) / "source-alias"
        alias.symlink_to(Path(self.root.name), target_is_directory=True)
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": str(alias / self.path.name)}])

    def test_parent_dotdot_rejected(self):
        (self.path.parent / "subdir").mkdir()
        parent = str(self.path.parent / "subdir" / ".." / self.path.name)
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"image": parent}])

    def test_audio_and_unregistered_media_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [{"audio": "payload"}])

    def test_uninspectable_tokenizer_output_denied(self):
        self.model.tokenizer = FakeTokenizer(broken=True)
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, ["source"])

    def test_empty_text_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, [""])

    def test_unbounded_batch_denied(self):
        with self.assertRaises(b.NativeBudgetError):
            b.check_batch(self.model, ["x"] * 9)

    def test_mixed_batch_completely_verified(self):
        result = b.check_batch(self.model, ["plain", {"text": "joint", "image": str(self.path)}])
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["max_conservative_context_tokens"], 1132)



class SourceBoundRuntimeContext(unittest.TestCase):
    """Offline exact-source runtime bindings, never a pretrained model claim."""

    def make_owner(self, first_limit=None):
        class Model:
            def __init__(self, initial):
                self.first = SimpleNamespace(max_seq_length=initial)
                self.tokenizer = FakeTokenizer()
                self.prompts = {"Classification": "task: classification | query: "}
            def __getitem__(self, idx):
                if idx != 0:
                    raise IndexError(idx)
                return self.first
            @property
            def max_seq_length(self):
                return self.first.max_seq_length
            @max_seq_length.setter
            def max_seq_length(self, value):
                self.first.max_seq_length = value
        return SimpleNamespace(
            _verified_local_weights=True,
            model=Model(first_limit),
            profile_digest="a"*64,
            manifest={
                "model_id": "google/embeddinggemma-2",
                "revision": "914f7f89142e33e77833254d9c9b90c3cef7303b",
                "profile": "vision", "dimension": 256,
                "precision": "float32",
            },
        )

    def test_pinned_real_runtime_binds_previous_none(self):
        owner = self.make_owner()
        receipt = b.bind_verified_native_context(owner)
        self.assertIsNone(receipt["original_sentence_transformer_max_seq_length"])
        self.assertEqual(owner.model.max_seq_length, b.CONTEXT)
        self.assertEqual(owner.model[0].max_seq_length, b.CONTEXT)
        self.assertFalse(receipt["production_accepted"])

    def test_pinned_8192_runtime_is_idempotent(self):
        owner = self.make_owner(first_limit=8192)
        first = b.bind_verified_native_context(owner)
        second = b.bind_verified_native_context(owner)
        self.assertEqual(first["effective_sentence_transformer_max_seq_length"],8192)
        self.assertEqual(second["original_sentence_transformer_max_seq_length"],8192)

    def test_original_262144_is_bound_to_documented_8192(self):
        owner = self.make_owner(first_limit=262144)
        b.bind_verified_native_context(owner)
        self.assertEqual(owner.model.max_seq_length,8192)

    def test_short_sentence_transformer_default_is_rebound_without_truncation(self):
        owner = self.make_owner(first_limit=1024)
        receipt=b.bind_verified_native_context(owner)
        self.assertEqual(receipt["original_sentence_transformer_max_seq_length"],1024)
        self.assertEqual(receipt["effective_sentence_transformer_max_seq_length"],8192)
        self.assertEqual(receipt["underlying_transformer_max_seq_length"],8192)
        self.assertIs(receipt["image_token_count_physically_verified"],False)

    def test_512_default_is_rebound(self):
        owner = self.make_owner(first_limit=512)
        receipt=b.bind_verified_native_context(owner)
        self.assertEqual(receipt["original_sentence_transformer_max_seq_length"],512)
        self.assertEqual(owner.model[0].max_seq_length,8192)

    def test_tiny_unreviewed_default_rejected(self):
        owner = self.make_owner(first_limit=64)
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_boolean_default_denied(self):
        owner = self.make_owner(first_limit=True)
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_overlarge_unreviewed_default_denied(self):
        owner = self.make_owner(first_limit=262145)
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_unverified_weight_owner_denied(self):
        owner = self.make_owner()
        owner._verified_local_weights = False
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_wrong_publisher_revision_denied(self):
        owner = self.make_owner()
        owner.manifest["revision"] = "b"*40
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_wrong_model_modality_profile_denied(self):
        owner = self.make_owner()
        owner.manifest["profile"] = "text"
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_invalid_origin_manifest_digest_denied(self):
        owner = self.make_owner()
        owner.profile_digest = None
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_source_model_without_first_module_denied(self):
        owner = self.make_owner()
        owner.model.__class__.__getitem__ = lambda self, idx: (_ for _ in ()).throw(IndexError(idx))
        with self.assertRaises(b.NativeBudgetError):
            b.bind_verified_native_context(owner)

    def test_bound_does_not_prove_media_count(self):
        owner = self.make_owner()
        result=b.bind_verified_native_context(owner)
        self.assertIs(result["image_token_count_physically_verified"],False)
        self.assertIs(result["model_origin_independently_signed"],False)


if __name__ == "__main__":
    unittest.main()
