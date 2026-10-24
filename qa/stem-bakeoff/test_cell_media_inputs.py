"""Actual image transforms, allowlists and content/feature tamper checks."""

import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from cell_media_inputs import cheap_features, media_rows
from prepare_cell_media import canonical, input_identity, sha
from real_cell_features import load_features


class MediaInputTests(unittest.TestCase):
    def dataset(self, root):
        (root / "media").mkdir()
        rows = []
        for i in range(3):
            pixels = np.full((32, 32, 3), 50 + i * 60, dtype=np.uint8)
            stream = io.BytesIO()
            Image.fromarray(pixels).save(stream, format="PNG")
            raw = stream.getvalue()
            path = f"media/{i}.png"
            (root / path).write_bytes(raw)
            rows.append({"source_id": f"image:{i}", "group_id": "pixels:" + sha(pixels.tobytes()),
                "source_version": "fixture", "text": "A photograph.", "modality": "image",
                "record": {"text": "A photograph.", "image": path}, "media_sha256": sha(raw),
                "media_bytes": len(raw), "labels": {"secret_target": i % 2},
                "input_content_sha256": input_identity("image", "A photograph.", "sha256:" + sha(raw))})
        dataset = root / "dataset.json"
        dataset.write_bytes(canonical({"protocol": {"input_modality": "image", "neutral_prompt": "A photograph."}, "rows": rows}))
        return dataset

    def test_pixel_baseline_uses_media_and_never_gold_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.dataset(root)
            rows, _, _ = media_rows(dataset)
            self.assertTrue(all("labels" not in row and "group_id" not in row for row in rows))
            report = cheap_features(dataset, root / "features")
            features, _ = load_features(root / "features", dataset)
            self.assertEqual(features.shape, (3, 3072))
            np.testing.assert_allclose(features[:, 0], np.array([50, 110, 170], dtype=np.float32) / 127.5 - 1)
            self.assertEqual(report["encoding"]["physical_model_forward_calls"], 0)
            data = json.loads(dataset.read_bytes())
            data["rows"][0]["labels"]["secret_target"] = 1
            dataset.write_bytes(canonical(data))
            changed, _, _ = media_rows(dataset)
            self.assertEqual(rows, changed)
            with self.assertRaisesRegex(ValueError, "corpus"):
                load_features(root / "features", dataset)

    def test_changed_media_or_label_text_rejects_before_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = self.dataset(root)
            data = json.loads(dataset.read_bytes())
            data["rows"][0]["record"]["text"] = "An animal."
            dataset.write_bytes(canonical(data))
            with self.assertRaisesRegex(ValueError, "neutral"):
                media_rows(dataset)
            data["rows"][0]["record"]["text"] = "A photograph."
            dataset.write_bytes(canonical(data))
            source = root / "media/0.png"
            source.write_bytes(source.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                media_rows(dataset)


if __name__ == "__main__":
    unittest.main()
