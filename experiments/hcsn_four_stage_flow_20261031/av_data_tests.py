"""Small semantic checks; no real-media extraction or Torch import."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from . import av_data as av


class AVDataTests(unittest.TestCase):
    def test_exact_information_bounds_and_single_modality_balance(self):
        bounds = av.information_bounds()
        self.assertEqual(bounds["none"]["accuracy"], 0.5)
        for name in ("audio", "video", "text"):
            self.assertEqual(bounds[name]["accuracy"], 0.5)
        for name in ("audio+video", "audio+text", "video+text"):
            self.assertEqual(bounds[name], dict(correct_weight=10, total_weight=12, accuracy=5/6))
        self.assertEqual(bounds["audio+video+text"]["accuracy"], 1)

    def test_prefix_features_ignore_future_content_and_recording_length(self):
        rng = np.random.default_rng(917)
        wave = rng.normal(size=24000).astype(np.float32)
        times = np.arange(41, dtype=np.float64) / 25
        pixels = rng.integers(0, 256, size=(41, 16, 16), dtype=np.uint8)
        original, receipt = av.fixed_window_features(wave, pixels, times, 0.0)
        changed_wave = np.concatenate((wave, rng.normal(size=8000).astype(np.float32)))
        changed_wave[16000:] = -99
        changed_pixels = pixels.copy()
        changed_pixels[times > 1.0] = 255 - changed_pixels[times > 1.0]
        changed, _ = av.fixed_window_features(changed_wave, changed_pixels, times, 0.0)
        for key in original:
            np.testing.assert_array_equal(original[key], changed[key])
        self.assertEqual(receipt["selected_video_times"], [0.48, 1.0])
        self.assertTrue(np.isfinite(original["audio"]).all())

    def test_second_window_does_not_modify_first(self):
        rng = np.random.default_rng(19)
        wave = rng.normal(size=20000).astype(np.float32)
        times = np.arange(31) / 25
        frames = rng.integers(0, 256, (31, 16, 16), dtype=np.uint8)
        before, _ = av.fixed_window_features(wave, frames, times, 0)
        wave[8000:] *= 4
        frames[times > 0.5] = 0
        after, _ = av.fixed_window_features(wave, frames, times, 0)
        np.testing.assert_array_equal(before["audio"][0], after["audio"][0])
        np.testing.assert_array_equal(before["video"][0], after["video"][0])
        self.assertFalse(np.array_equal(before["audio"][1], after["audio"][1]))

    def test_native_window_is_cropped_before_resampling(self):
        rng = np.random.default_rng(71)
        rate = 44100
        wave = rng.normal(size=rate * 2).astype(np.float32)
        times = np.arange(41) / 25
        pixels = np.zeros((41, 16, 16), dtype=np.uint8)
        before, receipt = av.fixed_window_features(wave, pixels, times, 0, rate)
        wave[rate:] = 10000
        after, _ = av.fixed_window_features(wave, pixels, times, 0, rate)
        np.testing.assert_array_equal(before["audio"], after["audio"])
        wave[rate // 2:rate] = -10000
        changed_second, _ = av.fixed_window_features(wave, pixels, times, 0, rate)
        np.testing.assert_array_equal(before["audio"][0], changed_second["audio"][0])
        self.assertFalse(np.array_equal(before["audio"][1], changed_second["audio"][1]))
        self.assertEqual(receipt["native_audio_samples_used_per_window"], 22050)

    def test_episode_interface_weights_and_metadata_separation(self):
        records, features = [], {}
        for index, sentence in enumerate(av.SENTENCES):
            clip = f"1001_{sentence}_ANG_XX"
            records.append(dict(actor="1001", emotion="ANG", sentence=sentence, clip=clip))
            features[clip] = dict(audio=np.full((2, 64), index, dtype=np.float32),
                                  video=np.full((2, 64), index + 10, dtype=np.float32))
        data = av.assemble_episodes(records, features)
        self.assertEqual(data["x"].shape, (8, 2, av.INPUT_DIM))
        self.assertEqual(data["x"].dtype, np.float32)
        self.assertEqual(data["sample_weight"].sum(), 12)
        self.assertEqual((data["sample_weight"] * data["y"]).sum(), 6)
        self.assertEqual(len(set(data["sample_id"])), 8)
        self.assertEqual(av.MODEL_ARRAYS, ("x", "dt"))
        masked = av.mask_modalities(data["x"], ["audio", "text"])
        self.assertFalse(masked[..., slice(*av.MODALITY_SLICES["audio"])].any())
        self.assertFalse(masked[..., slice(*av.MODALITY_SLICES["text"])].any())
        np.testing.assert_array_equal(masked[..., 64:128], data["x"][..., 64:128])
        np.testing.assert_array_equal(masked[..., -3:], np.broadcast_to([0, 1, 0], (8, 2, 3)))
        np.testing.assert_array_equal(data["dt"], np.full((8, 2), 0.5))

    def test_cohort_disjointness_complete_groups_and_frozen_identity(self):
        splits = dict(train=["1001"], validation=["1002"], test=["1003"])
        records = [dict(actor=actor, sentence=s, emotion=e, split=split,
                        clip=f"{actor}_{s}_{e}_XX", sha256="a" * 64, bytes=10)
                   for split, actors in splits.items() for actor in actors
                   for s in av.SENTENCES for e in av.EMOTIONS]
        with tempfile.TemporaryDirectory(prefix="hcsn-avt-test-") as temporary:
            root = Path(temporary)
            cohort = root / "cohort.json"
            payload = dict(upstream_sha=av.UPSTREAM_COMMIT, splits=splits, records=records)
            cohort.write_text(json.dumps(payload))
            self.assertEqual(len(av.freeze_plan(cohort, root / "out")), 36)
            av.freeze_plan(cohort, root / "out")
            payload["records"][0]["bytes"] = 11
            cohort.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "frozen AV data contract"):
                av.freeze_plan(cohort, root / "out")
            payload["splits"]["test"] = ["1001"]
            cohort.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "disjoint"):
                av.read_cohort(cohort)

    def test_confirmation_requires_prior_candidate_freeze(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-avt-test-") as temporary:
            with self.assertRaisesRegex(ValueError, "candidate-freeze"):
                av.prepare(Path(temporary), Path(temporary) / "absent.json",
                           Path(temporary) / "out", ["test"])
            self.assertFalse((Path(temporary) / "out").exists())


if __name__ == "__main__":
    unittest.main()
