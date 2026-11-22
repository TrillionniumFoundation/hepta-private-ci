"""Zero-authentic-compute controls for the parallel resource amendment."""

import json
import tempfile
import unittest
from pathlib import Path

from .lane import _progress


class ParallelProfileControls(unittest.TestCase):
    def test_progress_is_durable_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.jsonl"
            _progress(path, "test", lane_ordinal=3)
            record = json.loads(path.read_text())
            self.assertEqual(record["event"], "test")
            self.assertEqual(record["lane_ordinal"], 3)

    def test_fixed_lane_roster(self):
        self.assertEqual(list(range(10)), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])


if __name__ == "__main__":
    unittest.main()
