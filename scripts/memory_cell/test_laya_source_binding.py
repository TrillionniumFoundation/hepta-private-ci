"""Exercise the pinned Laya source boundary without loading model weights."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import laya_backend


def git_blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


class LayaVerifiedSourceTests(unittest.TestCase):
    def test_replacement_after_verification_executes_only_verified_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            model_dir.mkdir()
            (model_dir / "rl_agent_config.json").write_text("{}")
            source_path = root / "common.py"
            verified = (
                b"def build_model(config, encoder):\n"
                b"    raise RuntimeError('verified Laya source reached')\n"
            )
            replacement = (
                b"def build_model(config, encoder):\n"
                b"    raise RuntimeError('reopened replacement source reached')\n"
            )
            source_path.write_bytes(verified)
            read_bytes = Path.read_bytes
            reads = []

            def read_and_replace(path):
                data = read_bytes(path)
                if path == source_path:
                    reads.append(data)
                    source_path.write_bytes(replacement)
                return data

            with (
                mock.patch.object(
                    laya_backend, "LAYA_COMMON_GIT_BLOB", git_blob(verified)
                ),
                mock.patch.object(Path, "read_bytes", read_and_replace),
                self.assertRaisesRegex(RuntimeError, "^verified Laya source reached$"),
            ):
                laya_backend.train_and_measure(
                    model_dir, source_path, [], root / "output"
                )
            self.assertEqual(reads, [verified])
            self.assertEqual(read_bytes(source_path), replacement)
            self.assertFalse((root / "output").exists())

    def test_unreviewed_bytes_are_rejected_before_module_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "common.py"
            source_path.write_text(
                "raise RuntimeError('unreviewed module was executed')\n"
            )
            with (
                mock.patch.object(laya_backend, "LAYA_COMMON_GIT_BLOB", "0" * 40),
                self.assertRaisesRegex(ValueError, "^unreviewed Laya source$"),
            ):
                laya_backend.train_and_measure(
                    root / "absent-model", source_path, [], root / "output"
                )
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
