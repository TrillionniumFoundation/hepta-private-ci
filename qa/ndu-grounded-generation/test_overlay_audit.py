"""Model-free positive and negative controls for the forensic overlay screen."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from overlay_audit import audit


class OverlayAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.box = [0.2, 0.2, 0.7, 0.8]
        image = Image.new("RGB", (100, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 16, 70, 64), outline=(255, 30, 30), width=3)
        image = image.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        path = self.root / "origin.png"
        image.save(path)
        self.digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.rename(self.root / (self.digest + ".png"))
        self.row = {"task_id": "example", "method": "base", "boxes": [self.box],
                    "artifact_sha256": self.digest}
        self.refs = self.root / "refs.jsonl"
        self.refs.write_text(json.dumps({"task_id": "example", "image_size": [100, 80]}) + "\n")
        self.episodes = self.root / "test.jsonl"

    def check(self):
        self.episodes.write_text(json.dumps(self.row) + "\n")
        return audit(self.episodes, self.root, self.refs)

    def test_valid_rectangle_and_frame_size(self):
        receipt = self.check()
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual((receipt["episodes"], receipt["predicted_boxes"]), (1, 1))
        self.assertGreater(receipt["minimum_eligible_box_border_coverage"], 0.99)

    def test_wrong_rectangle_is_detected(self):
        self.row["boxes"] = [[0.1, 0.1, 0.6, 0.7]]
        receipt = self.check()
        self.assertEqual(receipt["status"], "fail")
        self.assertEqual(len(receipt["low_coverage_boxes"]), 1)

    def test_modified_png_digest_is_detected(self):
        path = self.root / (self.digest + ".png")
        path.write_bytes(path.read_bytes() + b"tampered")
        self.assertEqual(self.check()["bad_artifacts"][0]["reason"], "digest_mismatch")

    def test_frame_size_mismatch_is_detected(self):
        self.refs.write_text(json.dumps({"task_id": "example", "image_size": [101, 80]}) + "\n")
        self.assertEqual(self.check()["bad_artifacts"][0]["reason"], "frame_size_mismatch")

    def test_empty_predictions_are_counted(self):
        self.row["boxes"] = []
        receipt = self.check()
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual((receipt["empty_box_episodes"], receipt["predicted_boxes"]), (1, 0))

    def test_invalid_box_fails_closed(self):
        self.row["boxes"] = [[0.8, 0.1, 0.2, 0.7]]
        receipt = self.check()
        self.assertEqual(receipt["status"], "fail")
        self.assertEqual(receipt["unrenderable_boxes"], 1)

    def test_invalid_digest_fails_closed(self):
        self.row["artifact_sha256"] = "../tampered"
        receipt = self.check()
        self.assertEqual(receipt["status"], "fail")
        self.assertEqual(receipt["bad_artifacts"][0]["reason"], "invalid_digest")

    def test_duplicate_ids_fail_closed(self):
        self.episodes.write_text(json.dumps(self.row) + "\n" + json.dumps(self.row) + "\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit(self.episodes, self.root, self.refs)


if __name__ == "__main__":
    unittest.main()
