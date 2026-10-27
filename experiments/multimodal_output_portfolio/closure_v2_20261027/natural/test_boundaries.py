"""Behavioral checks for public-only inference, fallback and clustered scoring."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from .common import paired_ci
from .document_model import fit, select
from .fetch_video import RangeArchive
from .video_engine import render


class BoundaryTests(unittest.TestCase):
    def test_rule_fallback_and_fitted_exception(self):
        choices = {field: [{"value": "OLD", "box": [0, 0, 1, 1], "features": [0.] * 31, "is_rule": True},
            {"value": "NEW", "box": [0, 0, 1, 1], "features": [1.] * 31, "is_rule": False}]
            for field in ("company", "date", "address", "total")}
        documents = [{"options": choices, "reference": {"company": "NEW", "date": None, "address": None, "total": None}}
            for _ in range(8)]
        model = fit(documents, 1.)
        corrected, correction = select(choices, model, .1)
        retained, retention = select(choices, model, 1000.)
        self.assertEqual(corrected["company"]["value"], "NEW")
        self.assertEqual(retained["company"]["value"], "OLD")
        self.assertTrue(all(row["rule_preserved"] for row in retention))
        self.assertEqual(model["diagnostics"]["date"]["observed_documents"], 0)

    def test_target_file_is_not_an_inference_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pixels = np.zeros((64, 96, 3), dtype=np.uint8)
            pixels[20:40, 25:50] = [200, 100, 50]
            Image.fromarray(pixels).save(root / "left.png")
            Image.fromarray(np.roll(pixels, 3, axis=1)).save(root / "right.png")
            item = {"left": str(root / "left.png"), "right": str(root / "right.png"), "private_target": "/unreadable/private.png"}
            first = render(item, {"solver": "dis_ultrafast", "alpha": .8}, root / "first")
            item["private_target"] = "another-missing-target"
            second = render(item, {"solver": "dis_ultrafast", "alpha": .8}, root / "second")
            self.assertEqual(first["output_sha256"], second["output_sha256"])
            self.assertFalse(first["private_target_received"])

    def test_frame_replication_does_not_create_source_clusters(self):
        rows = [{"id": str(group), "source": group, "arm": arm, "quality": group + (arm == "new")}
            for group in range(4) for arm in ("new", "old")]
        first = paired_ci(rows, "new", "old", "quality", "source")
        repeated = [{**row, "id": row["id"] + str(index)} for row in rows for index in range(5)]
        second = paired_ci(repeated, "new", "old", "quality", "source")
        self.assertEqual(first, second)
        self.assertEqual(first["independent_source_clusters"], 4)

    def test_full_archive_response_is_rejected_without_read(self):
        class FullResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, size):
                raise AssertionError("Full archive must not be read")

        with tempfile.TemporaryDirectory() as directory, patch("urllib.request.urlopen", return_value=FullResponse()):
            with self.assertRaisesRegex(ValueError, "full archive"):
                RangeArchive("https://example.test/data.zip", Path(directory) / "ranges")


if __name__ == "__main__":
    unittest.main()
