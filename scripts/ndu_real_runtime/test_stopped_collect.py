"""Read-only recovery behavior at the collector entry point."""

from pathlib import Path
import tempfile
import unittest

from .stopped_collect import readback_attempt


class StoppedCollectionTests(unittest.TestCase):
    def test_missing_and_interrupted_attempts_keep_the_denominator_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "attempts").mkdir()
            entry = {"operation": "fixture", "phase": "calibration"}
            item, raw = readback_attempt(entry, {}, root)
            self.assertEqual(
                (item["status"], item["training_rows"], raw), ("Unstarted", 0, b"")
            )
            (root / "attempts/fixture").mkdir()
            before = list(root.rglob("*"))
            item, raw = readback_attempt(entry, {}, root)
            self.assertEqual(
                (item["status"], item["training_rows"], raw), ("Unresolved", 0, b"")
            )
            self.assertEqual(list(root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
