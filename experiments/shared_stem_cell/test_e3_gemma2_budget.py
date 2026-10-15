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


if __name__ == "__main__":
    unittest.main()
