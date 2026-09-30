"""Regression coverage for immutable upstream versus derived loader inputs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from laya_loader_view import LayaLoaderView, _digest, _inventory


class LoaderViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "snapshot"
        (self.root / "tokenizer").mkdir(parents=True)
        self.config = self.root / "tokenizer/tokenizer_config.json"
        self.config.write_text(json.dumps({"tokenizer_class": "TokenizersBackend", "backend": "tokenizers", "is_local": True, "extra_special_tokens": ["<x>"], "model_max_length": 1024}))
        (self.root / "model.safetensors").write_bytes(b"immutable-weight-fixture")

    def view(self):
        value = LayaLoaderView(self.root, expected_snapshot_digest=_digest(_inventory(self.root)))
        self.addCleanup(value.close)
        return value

    def test_private_compatibility_rewrite_does_not_change_original(self):
        original = _inventory(self.root)
        view = self.view()
        self.assertEqual(_inventory(self.root), original)
        self.assertEqual(json.loads((view.path / "tokenizer/tokenizer_config.json").read_bytes()), {"tokenizer_class": "PreTrainedTokenizerFast", "extra_special_tokens": {"extra_0": "<x>"}, "model_max_length": 1024})
        self.assertNotEqual(view.identity["source_snapshot_digest"], view.identity["effective_snapshot_digest"])
        self.assertEqual(view.identity["changed_paths"], ["tokenizer/tokenizer_config.json"])
        self.assertNotEqual(self.config.stat().st_ino, (view.path / "tokenizer/tokenizer_config.json").stat().st_ino)
        view.verify()

    def test_prepared_view_is_stable_and_cleanup_is_local(self):
        first = self.view()
        second = self.view()
        self.assertEqual(first.identity, second.identity)
        copied = first.path
        first.close()
        self.assertFalse(copied.exists())
        self.assertTrue(self.config.exists())
        second.verify()

    def test_already_compatible_bytes_are_not_reserialized(self):
        raw = b'{ "tokenizer_class": "PreTrainedTokenizerFast", "extra_special_tokens": {} }'
        self.config.write_bytes(raw)
        view = self.view()
        self.assertEqual((view.path / "tokenizer/tokenizer_config.json").read_bytes(), raw)
        self.assertEqual(view.identity["changed_paths"], [])
        self.assertEqual(view.identity["source_snapshot_digest"], view.identity["effective_snapshot_digest"])

    def test_source_mutation_is_detected(self):
        view = self.view()
        self.config.write_text('{}')
        with self.assertRaisesRegex(ValueError, "original snapshot changed"):
            view.verify()

    def test_unexpected_effective_mutation_is_detected(self):
        view = self.view()
        target = view.path / "model.safetensors"
        target.chmod(0o600)
        target.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "effective loader inputs changed"):
            view.verify()
        self.assertEqual((self.root / "model.safetensors").read_bytes(), b"immutable-weight-fixture")

    def test_symlinks_and_non_regular_entries_reject(self):
        (self.root / "alias").symlink_to(self.config)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            self.view()

    def test_duplicate_and_malformed_tokenizer_fields_reject(self):
        for value in (b'{"tokenizer_class":null,"tokenizer_class":"TokenizersBackend"}', b'[]', b'{"extra_special_tokens":[23]}', b'{"a":NaN}'):
            with self.subTest(value=value):
                self.config.write_bytes(value)
                with self.assertRaises(ValueError):
                    self.view()

    def test_admitted_upstream_identity_cannot_be_rebound(self):
        admitted = _digest(_inventory(self.root))
        self.config.write_text('{}')
        with self.assertRaisesRegex(ValueError, "admitted upstream inventory"):
            LayaLoaderView(self.root, expected_snapshot_digest=admitted)

    def test_capacity_rejects_before_copy(self):
        with patch('laya_loader_view.MAX_TOTAL_BYTES', 1):
            with self.assertRaisesRegex(ValueError, "capacity"):
                self.view()


if __name__ == "__main__":
    unittest.main()
