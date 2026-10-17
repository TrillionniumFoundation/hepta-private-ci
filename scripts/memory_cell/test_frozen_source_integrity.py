"""Reject corrupted physical-generation sources or semantic rewrites."""

import hashlib
import shutil
from pathlib import Path
import tempfile
import unittest

from frozen_source_integrity import PINS, ROOT, object_ids, verify_archive


class ImmutableGeneratingSourceTests(unittest.TestCase):
    def test_original_sources_equal_published_generating_git_blobs(self):
        result = verify_archive()
        self.assertEqual(result["byte_identical_original_generators"], 4)
        self.assertEqual(result["syntax_tree_equivalent_development_copies"], 4)
        self.assertEqual(result["decision"], "DENY_ALL")

    def test_byte_mutation_fails_even_if_syntax_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy(root)
            name = "locomo_reader_replay.py"
            path = root / "frozen_source" / (name + ".source")
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "historical generating Git object"):
                verify_archive(root)

    def test_semantic_mutation_fails_even_when_archive_is_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._copy(root)
            path = root / "locomo_format_trial.py"
            path.write_bytes(path.read_bytes() + b"\nOVERRIDE = True\n")
            with self.assertRaisesRegex(ValueError, "changed behavior"):
                verify_archive(root)

    def test_git_object_hash_includes_blob_prefix(self):
        raw = b"print('example')\n"
        sha, digest = object_ids(raw)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        self.assertEqual(sha, hashlib.sha1(b"blob 17\0" + raw).hexdigest())

    @staticmethod
    def _copy(root):
        (root / "frozen_source").mkdir()
        for name in PINS:
            shutil.copy2(ROOT / name, root / name)
            shutil.copy2(
                ROOT / "frozen_source" / (name + ".source"),
                root / "frozen_source" / (name + ".source"),
            )


if __name__ == "__main__":
    unittest.main()
