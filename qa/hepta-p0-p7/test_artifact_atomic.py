"""No model or admission claims: filesystem evidence custody regressions only."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qualification import EvidenceError, digest, verify_artifact


class AtomicArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        (self.root / "nested").mkdir()
        self.content = b"pinned original evidence bytes\x00"
        (self.root / "nested" / "proof.bin").write_bytes(self.content)
        self.expected = digest(self.content)

    def tearDown(self):
        self.temp.cleanup()

    def test_regular_file_and_wrong_digest(self):
        verify_artifact(self.root, "nested/proof.bin", self.expected)
        with self.assertRaisesRegex(EvidenceError, "SHA256 mismatch"):
            verify_artifact(self.root, "nested/proof.bin", digest(b"wrong"))

    def test_symlink_root_directory_and_leaf_denied(self):
        (self.root / "linked").symlink_to(self.root / "nested", target_is_directory=True)
        (self.root / "nested" / "linked.bin").symlink_to(self.root / "nested" / "proof.bin")
        alias = self.root.parent / "root-link"
        alias.symlink_to(self.root, target_is_directory=True)
        for root, rel in ((alias, "nested/proof.bin"), (self.root, "linked/proof.bin"),
                          (self.root, "nested/linked.bin")):
            with self.subTest(root=root, rel=rel), self.assertRaises(EvidenceError):
                verify_artifact(root, rel, self.expected)

    def test_noncanonical_platform_paths_denied(self):
        for rel in ("../root/nested/proof.bin", "nested/../nested/proof.bin",
                    "nested//proof.bin", "./nested/proof.bin",
                    "/nested/proof.bin", "nested\\proof.bin", "C:/outside.bin",
                    "nested/\x00proof.bin"):
            with self.subTest(rel=rel), self.assertRaises(EvidenceError):
                verify_artifact(self.root, rel, self.expected)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO only")
    def test_fifo_is_nonblocking_and_rejected(self):
        os.mkfifo(self.root / "nested" / "pipe.bin")
        with self.assertRaisesRegex(EvidenceError, "not regular"):
            verify_artifact(self.root, "nested/pipe.bin", self.expected)

    def test_byte_limit_is_enforced(self):
        with self.assertRaisesRegex(EvidenceError, "too large"):
            verify_artifact(self.root, "nested/proof.bin", self.expected, cap=8)

    def test_leaf_symlink_swap_between_directory_and_file_open(self):
        leaf = self.root / "nested" / "proof.bin"
        outside = self.root.parent / "outside.bin"
        outside.write_bytes(self.content)
        real_open = os.open
        switched = False

        def switching_open(path, flags, *args, **kwargs):
            nonlocal switched
            if path == "proof.bin" and kwargs.get("dir_fd") is not None and not switched:
                switched = True
                leaf.unlink()
                leaf.symlink_to(outside)
            return real_open(path, flags, *args, **kwargs)

        with patch("qualification.os.open", side_effect=switching_open):
            with self.assertRaises(EvidenceError):
                verify_artifact(self.root, "nested/proof.bin", self.expected)
        self.assertTrue(switched)

    def test_parent_symlink_swap_is_rejected(self):
        parent = self.root / "nested"
        renamed = self.root.parent / "moved"
        real_open = os.open
        switched = False

        def switching_open(path, flags, *args, **kwargs):
            nonlocal switched
            if path == "nested" and kwargs.get("dir_fd") is not None and not switched:
                switched = True
                parent.rename(renamed)
                parent.symlink_to(renamed, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)

        with patch("qualification.os.open", side_effect=switching_open):
            with self.assertRaises(EvidenceError):
                verify_artifact(self.root, "nested/proof.bin", self.expected)
        self.assertTrue(switched)


if __name__ == "__main__":
    unittest.main()
