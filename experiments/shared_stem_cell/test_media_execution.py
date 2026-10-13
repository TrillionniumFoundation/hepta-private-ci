"""Real media-byte fixtures + synthetic tower tensors, not pretrained evidence."""
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image
import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import media_execution as m


class FixtureTowers:
    simulated = True

    def __init__(self, root, models):
        self.calls = {"fixture": 0}
        self.identities = {"fixture": "not-pretrained"}

    def encode(self, name, item, root):
        self.calls["fixture"] += 1
        n = len(item) if name == "video" else 2
        if name == "image":
            raw = m.reference(root, item)
            scalar = float(np.asarray(m.image_bytes(raw))[0, 0, 0]) / 255
        elif name == "audio":
            scalar = float(m.audio_bytes(m.reference(root, item)).mean())
        else:
            scalar = 0.125
        stamps = (torch.tensor([f["timestamp_us"] for f in item]) if name == "video" else
                  torch.arange(n, dtype=torch.int64))
        return torch.full((n, 4), scalar), stamps

    def close(self):
        pass


class MediaTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def picture(self, i):
        path = self.root / f"frame-{i}.png"
        if not path.exists():
            Image.new("RGB", (8, 8), (i, 2 * i, 3 * i)).save(path)
        return {"path": path.name, "sha256": e.sha(path.read_bytes())}

    def audio(self, rate=16000, channels=1):
        stream = io.BytesIO()
        with wave.open(stream, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.arange(3200, dtype="<i2").tobytes())
        return stream.getvalue()

    def rows(self):
        return [{"case_id": str(i), "group": f"source-{i}", "split": split,
                 "scope": "fixture", "observed_at": i * 1000000,
                 "inputs": {"text": "Shared instruction", "image": self.picture(i)}, "label": i % 2}
                for i, split in enumerate(("train", "train", "calibration", "holdout", "holdout"))]

    def save(self, rows):
        path = self.root / "dataset.jsonl"
        raw = b"".join(e.canonical(row) for row in rows)
        path.write_bytes(raw)
        return {"path": path.name, "sha256": e.sha(raw)}

    def test_actual_png_and_pcm_decode(self):
        self.assertEqual(m.image_bytes(m.reference(self.root, self.picture(4))).size, (8, 8))
        samples = m.audio_bytes(self.audio())
        self.assertEqual(len(samples), 3200)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(float(samples[1]), 1 / 32768)

    def test_wrong_audio_rate_no_silent_resample(self):
        with self.assertRaises(e.InputError):
            m.audio_bytes(self.audio(rate=8000))

    def test_media_byte_hash_required(self):
        ref = self.picture(1)
        ref["sha256"] = "0" * 64
        with self.assertRaises(e.InputError):
            m.reference(self.root, ref)

    def test_parent_path_and_symlink_rejected(self):
        for ref in ({"path": "../x", "sha256": "a" * 64}, {"path": "/tmp/x", "sha256": "a" * 64}):
            with self.assertRaises(e.InputError):
                m.reference(self.root, ref)
        ref = self.picture(2)
        (self.root / "alias.png").symlink_to(self.root / ref["path"])
        with self.assertRaises(e.InputError):
            m.reference(self.root, {**ref, "path": "alias.png"})

    def test_media_source_leakage_across_folds(self):
        rows = self.rows()
        rows[-1]["inputs"]["image"] = rows[0]["inputs"]["image"]
        with self.assertRaisesRegex(e.InputError, "leakage"):
            m.read_cases(self.root, self.save(rows), 2)

    def test_group_leakage_and_scope_rejected(self):
        rows = self.rows()
        rows[-1]["group"] = rows[0]["group"]
        with self.assertRaises(e.InputError):
            m.read_cases(self.root, self.save(rows), 2)
        rows = self.rows()
        rows[-1]["scope"] = "other"
        with self.assertRaises(e.InputError):
            m.read_cases(self.root, self.save(rows), 2)

    def test_same_instruction_is_not_media_leakage(self):
        cases, labels = m.read_cases(self.root, self.save(self.rows()), 2, temporal=True)
        self.assertEqual(len(cases), 5)
        self.assertFalse(hasattr(cases[0], "label"))
        self.assertEqual(len(labels), 5)

    def test_reversed_future_video_and_float_times_rejected(self):
        for stamps in ((2, 1), (1, 9000000), (0.0, 1.0)):
            rows = self.rows()
            rows[-1]["inputs"]["video"] = [dict(self.picture(i+20), timestamp_us=t) for i, t in enumerate(stamps)]
            with self.assertRaises(e.InputError):
                m.read_cases(self.root, self.save(rows), 2)

    def test_missing_modality_uses_mask_not_fabricated_feature(self):
        cases, _ = m.read_cases(self.root, self.save(self.rows()), 2)
        cases = list(cases)
        cases[-1] = replace(cases[-1], inputs={"text": "Shared instruction"})
        values = m.extract(FixtureTowers(None, None), cases, self.root)
        self.assertFalse(bool(values["image"][1][-1].any()))
        self.assertTrue(bool(values["text"][1][-1].all()))
        self.assertEqual(values["image"][2].dtype, torch.int64)

    def test_invalid_tower_never_publishes_features(self):
        class Invalid(FixtureTowers):
            def encode(self, name, item, root):
                x, t = super().encode(name, item, root)
                x[0, 0] = float("nan")
                return x, t
        cases, _ = m.read_cases(self.root, self.save(self.rows()), 2)
        with self.assertRaises(e.InputError):
            m.extract(Invalid(None, None), cases, self.root)

    def test_real_connector_pipeline_on_fixture_media(self):
        config = {"schema": "hepta.shared-stem-media.v1", "classes": 2, "steps": 3,
                  "temporal": True, "models": {}, "dataset": self.save(self.rows())}
        e.write_once(self.root / "manifest.json", config)
        report = m.run(self.root / "manifest.json", self.root / "result", _tower_factory=FixtureTowers)
        self.assertTrue(report["simulated_towers"])
        self.assertFalse(report["multimodal_reasoning_established"])
        self.assertEqual({s["arm"] for s in report["scores"]}, {"image", "text", "image+text"})
        self.assertTrue(all(s["cases"] == 2 for s in report["scores"]))
        self.assertEqual(report["prediction_sha256"], e.sha((self.root / "result/predictions.json").read_bytes()))

    def test_source_change_during_inference_rejected_before_scoring(self):
        rows = self.rows()
        config = {"schema": "hepta.shared-stem-media.v1", "classes": 2, "steps": 1,
                  "models": {}, "dataset": self.save(rows)}
        e.write_once(self.root / "manifest.json", config)
        root = self.root
        class Mutating(FixtureTowers):
            def close(self):
                (root / "dataset.jsonl").write_bytes(b"{}\n")
        with self.assertRaises(e.InputError):
            m.run(self.root / "manifest.json", self.root / "result", _tower_factory=Mutating)
        self.assertFalse((self.root / "result/report.json").exists())
        self.assertFalse((self.root / "result/predictions.json").exists())


if __name__ == "__main__":
    unittest.main()
