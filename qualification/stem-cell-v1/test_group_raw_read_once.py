"""POSIX descriptor-pinned raw receipt intake; real filesystem negative tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from group_feedback_factorial_raw_replay import _regular_file


class DescriptorPinnedReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "original.json"
        self.payload = b'{"source":"immutable-original"}'
        self.path.write_bytes(self.payload)

    def test_reads_real_original_descriptor(self):
        self.assertEqual(_regular_file(self.path), self.payload)

    def test_refuses_symlink_and_fifo_without_blocking(self):
        target = self.root / "link.json"
        target.symlink_to(self.path)
        with self.assertRaises(ValueError):
            _regular_file(target)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            _regular_file(fifo)

    def test_rejects_empty_and_oversized_regular_file(self):
        self.path.write_bytes(b"")
        with self.assertRaises(ValueError):
            _regular_file(self.path)
        self.path.write_bytes(b"some file bytes")
        with patch("group_feedback_factorial_raw_replay.MAX_RAW_BYTES", 5):
            with self.assertRaises(ValueError):
                _regular_file(self.path)

    def test_rejects_file_swapped_at_open_boundary(self):
        original_open = os.open
        substitute = self.root / "substitute.json"
        substitute.write_bytes(b"other")
        def swap(path, flags):
            # The check must use the opened descriptor's bytes rather than
            # re-opening the mutable original path after hash admission.
            return original_open(substitute, flags)
        with patch("group_feedback_factorial_raw_replay.os.open", side_effect=swap):
            self.assertEqual(_regular_file(self.path), b"other")

    def test_missing_path_and_no_follow_support_fail_closed(self):
        with self.assertRaises(ValueError):
            _regular_file(self.root / "missing.json")
        with patch("group_feedback_factorial_raw_replay.os", spec_set=["O_RDONLY"]):
            with self.assertRaises(ValueError):
                _regular_file(self.path)


if __name__ == "__main__":
    unittest.main()
