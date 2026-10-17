"""Native view staging mechanics; fake bytes do not authorize real models."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import associative_minilm_offline as m


class NativeStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.publisher = self.root / "publisher"
        self.publisher.mkdir()
        for name in m.MODEL_FILES:
            (self.publisher / name).write_bytes((name + ":fixture").encode())
        (self.publisher / "README.md").write_text("publisher metadata - not runtime tensors")
        self.pinned = m._digest_json({
            name: {"sha256": m.hashlib.sha256((name + ":fixture").encode()).hexdigest(),
                   "bytes": len((name + ":fixture").encode())}
            for name in sorted(m.MODEL_FILES)
        })

    def stage(self):
        with patch.object(m, "REGISTERED_ENCODER_IDENTITY", self.pinned):
            return m.stage_native_view(self.publisher, self.root / "native")

    def test_extra_publisher_metadata_not_copied_and_identity_exact(self):
        result = self.stage()
        self.assertEqual(result["encoder_identity"], self.pinned)
        self.assertEqual(result["files"], 6)
        self.assertFalse(result["production_accepted"])
        self.assertEqual({p.name for p in (self.root / "native").iterdir()}, m.MODEL_FILES)
        self.assertTrue((self.publisher / "README.md").is_file())

    def test_unregistered_model_rejected_before_output_created(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            m.stage_native_view(self.publisher, self.root / "native")
        self.assertFalse((self.root / "native").exists())

    def test_mutated_registered_file_rejected(self):
        (self.publisher / "vocab.txt").write_bytes(b"different registered bytes")
        with self.assertRaisesRegex(ValueError, "unregistered"):
            self.stage()
        self.assertFalse((self.root / "native").exists())

    def test_symlinked_registered_file_is_rejected(self):
        (self.publisher / "vocab.txt").unlink()
        (self.publisher / "vocab.txt").symlink_to(self.publisher / "config.json")
        with self.assertRaisesRegex(ValueError, "symlinked"):
            self.stage()

    def test_missing_file_and_existing_target_fail_closed(self):
        (self.publisher / "tokenizer.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.stage()
        (self.publisher / "tokenizer.json").write_bytes(b"tokenizer.json:fixture")
        (self.root / "native").mkdir()
        with self.assertRaises(FileExistsError):
            self.stage()

    def test_staged_bytes_identical_and_not_hardlinks(self):
        self.stage()
        for name in m.MODEL_FILES:
            left, right = self.publisher / name, self.root / "native" / name
            self.assertEqual(left.read_bytes(), right.read_bytes())
            self.assertNotEqual(left.stat().st_ino, right.stat().st_ino)


if __name__ == "__main__":
    unittest.main()
