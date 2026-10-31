"""Behavioral tests for causality, missingness and ragged batch semantics."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from .async_av import (audio_features, event_inputs, fit_normalization,
                      load_batch, merge_observations, prefix_audit, save_npz)


class AsyncAVTests(unittest.TestCase):
    def test_future_audio_and_video_cannot_change_prefix(self):
        rng = np.random.default_rng(417)
        audio = rng.normal(size=44100)
        video = rng.integers(0, 256, (27, 16, 16), dtype=np.uint8)
        times = 0.027 + np.arange(len(video)) / 30
        _, result = prefix_audit(audio, video, times, 44100, 0.0, 16)
        self.assertTrue(result["passed"])
        self.assertGreater(result["prefix_events"], 10)

    def test_audio_is_available_at_window_end(self):
        _, times = audio_features(np.zeros(1600), 16000, 0.125)
        np.testing.assert_allclose(times[:2], [0.150, 0.160], rtol=0, atol=1e-15)
        values, ends = audio_features(np.ones(399), 16000, 0.125)
        self.assertEqual((values.shape, ends.shape), ((0, 16), (0,)))

    def test_ties_are_stable_and_zero_time_is_preserved(self):
        events = merge_observations(np.array([[1.], [2.]]), np.array([.1, .2]),
                                     np.array([[3.], [4.]]), np.array([.1, .3]))
        x, dt = event_inputs(**events, origin=0.0)
        np.testing.assert_array_equal(events["modality"], [0, 1, 0, 1])
        np.testing.assert_allclose(dt, [.1, 0, .1, .1])
        np.testing.assert_array_equal(x[:, 2:4], [[1, 0], [0, 1], [1, 0], [0, 1]])

    def test_missing_observation_has_no_payload_or_delta_leak(self):
        base = np.array([[2.], [999.], [5.]])
        times, modality, seen = np.array([.1, .2, .3]), np.zeros(3, dtype=np.uint8), [1, 0, 1]
        x, dt = event_inputs(base, times, modality, 0, observed=seen)
        changed = base.copy()
        changed[1] = -10000
        y, dy = event_inputs(changed, times, modality, 0, observed=seen)
        np.testing.assert_array_equal(x, y)
        np.testing.assert_array_equal(dt, dy)
        np.testing.assert_array_equal(x[1, :2], [0, 0])
        np.testing.assert_array_equal(x[2, :2], [5, 3])
        self.assertAlmostEqual(float(x[1, 6]), .1, places=6)

    def test_normalization_does_not_fit_validation_values(self):
        common = dict(times=np.array([.1, .2]), modality=np.array([0, 1]), origin=0.)
        train = dict(**common, base=np.array([[1.], [2.]]), split="train")
        heldout = dict(**common, base=np.array([[1000.], [-1000.]]), split="validation")
        a, b = fit_normalization([train]), fit_normalization([train, heldout])
        for key in a:
            np.testing.assert_array_equal(a[key], b[key])

    def test_batch_masks_padding_and_reads_last_valid_target(self):
        with tempfile.TemporaryDirectory() as folder:
            base, times, modalities = np.array([[1.], [2.], [3.]]), np.array([.1, .2, .1]), np.array([0, 1, 0])
            x1, dt1 = event_inputs(base[:2], times[:2], modalities[:2], 0.)
            x2, dt2 = event_inputs(base[2:], times[2:], modalities[2:], 0.)
            save_npz(Path(folder) / "train.npz", x=np.concatenate([x1, x2]), dt=np.r_[dt1, dt2],
                base=base, times=times, modality=modalities, offsets=np.array([0, 2, 3]),
                labels=np.array([4, 5]), origins=np.array([0., 0.]), clip_ids=np.array(["a", "b"]),
                normalization_mean=np.zeros((2, 2)), normalization_scale=np.ones((2, 2)))
            batch = load_batch(folder, "train")
            np.testing.assert_array_equal(batch["valid"], [[1, 1], [1, 0]])
            np.testing.assert_array_equal(batch["y_sequence"], [[-100, 4], [5, -100]])
            np.testing.assert_array_equal(batch["dt"], batch["dt_seconds"])
            hidden = load_batch(folder, "train", missing_modality=0)
            np.testing.assert_array_equal(hidden["x"][0, 0, :2], [0, 0])


if __name__ == "__main__":
    unittest.main()
