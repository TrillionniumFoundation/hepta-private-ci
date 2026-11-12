"""Behavioral checks for the actor-only CORD view and decoding boundary."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from perc1 import cord_task
from perc1.schema import Invalid, sha


class CordTaskTests(unittest.TestCase):
    def test_decoder_excludes_subtotals_counts_and_keeps_missing_unknown(self):
        self.assertEqual(
            cord_task.decode("Subtotal 100.000\nGrand Total 110,000\nTotal Items 2"),
            "110000",
        )
        self.assertEqual(cord_task.decode("TOTAL\nRp. 48.000"), "48000")
        self.assertIsNone(cord_task.decode("Subtotal 120,000\nCash 150,000"))
        self.assertIsNone(cord_task.decode("unreadable"))

    def test_unknown_region_views_keep_original_and_fit_native_patch_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "real-shaped.png"
            Image.new("RGB", (1800, 4200), "white").save(original)
            weights, projection = root / "weights", root / "projection"
            weights.write_bytes(b"fixture model bytes")
            projection.write_bytes(b"{}")
            item = dict(
                id="input",
                split="train",
                image_path=str(original),
                image_sha256=sha(original.read_bytes()),
                source_uri="fixture:receipt",
            )
            task = cord_task.prepare(item, root / "views", weights, projection)
            self.assertFalse(task["target_rectangle_public"])
            self.assertEqual(
                (root / "views/original.image").read_bytes(), original.read_bytes()
            )
            self.assertEqual(
                set(task["requests"]), {"initial", "full", "upper", "middle", "lower"}
            )
            for request in task["requests"].values():
                self.assertLessEqual(
                    sum(r["width"] * r["height"] * 3 for r in request["regions"]), 8192
                )
            with self.assertRaises(FileExistsError):
                cord_task.prepare(item, root / "views", weights, projection)
            original.write_bytes(b"changed input")
            with self.assertRaises(Invalid):
                cord_task.prepare(item, root / "changed", weights, projection)


if __name__ == "__main__":
    unittest.main()
