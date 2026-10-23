#!/usr/bin/env python3
"""Synthetic artifact-identity rejection tests; never evidence of model execution."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bakeoff import EvidenceError
from run_models import model_inventory, validate_snapshot_repository


class ExactArtifactIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (
            Path(self.temp.name) / "models--convaiinnovations--laya" /
            "snapshots" / ("a" * 40)
        )
        self.root.mkdir(parents=True)
        (self.root / "model.safetensors").write_bytes(b"english-weights")
        (self.root / "tokenizer").mkdir()
        (self.root / "tokenizer" / "tokenizer.json").write_bytes(b"english-tokens")
        (self.root / "multilingual").mkdir()
        (self.root / "multilingual" / "model.safetensors").write_bytes(b"multilingual-weights")
        (self.root / "multilingual" / "tokenizer.json").write_bytes(b"multilingual-tokens")
        (self.root / "typed-decisions").mkdir()
        (self.root / "typed-decisions" / "model.safetensors").write_bytes(b"typed-weights")
        (self.root / "typed-decisions" / "tokenizer.json").write_bytes(b"typed-tokens")

    def test_correct_laya_english_repo_snapshot(self):
        validate_snapshot_repository(self.root, "laya-english-421m", "a" * 40)

    def test_snapshot_from_wrong_repo_is_rejected(self):
        with self.assertRaisesRegex(EvidenceError, "checkpoint repository mismatch"):
            validate_snapshot_repository(self.root, "laya-typed-421m", "a" * 40)

    def test_wrong_snapshot_revision_is_rejected(self):
        with self.assertRaisesRegex(EvidenceError, "snapshot must be exact"):
            validate_snapshot_repository(self.root, "laya-english-421m", "b" * 40)

    def test_bundled_siblings_do_not_change_english_weight_digest(self):
        before = model_inventory(self.root, exclude_bundled_laya=True)
        (self.root / "typed-decisions" / "model.safetensors").write_bytes(b"tampered-typed")
        (self.root / "multilingual" / "model.safetensors").write_bytes(b"tampered-ml")
        self.assertEqual(before, model_inventory(self.root, exclude_bundled_laya=True))
        (self.root / "model.safetensors").write_bytes(b"changed-english")
        self.assertNotEqual(before["weights"], model_inventory(self.root, exclude_bundled_laya=True)["weights"])

    def test_escaped_model_weight_symlink_is_rejected(self):
        outside = Path(self.temp.name) / "external.safetensors"
        outside.write_bytes(b"escaped")
        (self.root / "model.safetensors").unlink()
        (self.root / "model.safetensors").symlink_to(outside)
        with self.assertRaisesRegex(EvidenceError, "escaped model file"):
            model_inventory(self.root, exclude_bundled_laya=True)


if __name__ == "__main__":
    unittest.main()
