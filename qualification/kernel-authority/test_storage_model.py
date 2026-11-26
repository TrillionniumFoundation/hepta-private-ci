#!/usr/bin/env python3
"""Regression tests for the qualification-only WAL/checkpoint model."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("storage_model.py")
SPEC = importlib.util.spec_from_file_location("kernel_authority_storage_model", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
STORAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORAGE)


class StorageModelTests(unittest.TestCase):
    def build(self, root: Path, operations: int = 256):
        model = root / "model"
        rollback = root / "rollback"
        frontier, head = STORAGE.build_model(model, rollback, operations)
        return model, rollback, frontier, head

    def test_checkpoint_binds_the_entire_committed_journal_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _rollback, frontier, _head = self.build(root)
            self.assertTrue(
                STORAGE.corrupt_committed_record(
                    model,
                    root / "corrupted-before-checkpoint",
                    frontier,
                    earliest=True,
                )
            )
            self.assertTrue(
                STORAGE.corrupt_committed_record(
                    model,
                    root / "corrupted-after-checkpoint",
                    frontier,
                    earliest=False,
                )
            )

    def test_checkpoint_sequence_type_is_not_coerced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _rollback, frontier, _head = self.build(root)
            manifest_path = model / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            checkpoint_path = model / manifest["checkpointPath"]
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["sequence"] = str(checkpoint["sequence"])
            checkpoint_bytes = STORAGE.canonical(checkpoint) + b"\n"
            checkpoint_path.write_bytes(checkpoint_bytes)
            manifest["checkpointSha256"] = STORAGE.sha256_bytes(checkpoint_bytes)
            manifest_path.write_bytes(STORAGE.canonical(manifest) + b"\n")
            with self.assertRaises(STORAGE.ModelError):
                STORAGE.recover(model, frontier)

    def test_checkpoint_path_cannot_escape_the_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, _rollback, frontier, _head = self.build(root)
            manifest_path = model / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["checkpointPath"] = "../checkpoint-escape.json"
            manifest_path.write_bytes(STORAGE.canonical(manifest) + b"\n")
            with self.assertRaises(STORAGE.ModelError):
                STORAGE.recover(model, frontier)

    def test_boolean_is_not_an_integer_for_security_state(self) -> None:
        with self.assertRaises(STORAGE.ModelError):
            STORAGE.require_nonnegative_int(True, "fixture")


if __name__ == "__main__":
    unittest.main()
