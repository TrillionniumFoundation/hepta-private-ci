"""Data-contract tests: leakage, information-preserving length changes and queries."""

import gzip
from pathlib import Path
import struct
import tempfile
import unittest
import wave

import numpy as np

from experiments.continuous_spiking_network.data import (
    FSDD_COMMIT,
    SPEAKER_SPLITS,
    audio_features,
    load_data,
)


def _write_idx(path, array):
    with gzip.open(path, "wb") as handle:
        handle.write(
            struct.pack(">" + "I" * (array.ndim + 1), 0x800 + array.ndim, *array.shape)
        )
        handle.write(array.astype(np.uint8).tobytes())


def _source_fixture(directory):
    raw = directory / "mnist"
    raw.mkdir()
    rng = np.random.default_rng(123)
    for prefix, count in (("train", 1200), ("t10k", 600)):
        labels = np.arange(count, dtype=np.uint8) % 10
        images = rng.integers(0, 256, (count, 28, 28), dtype=np.uint8)
        _write_idx(raw / f"{prefix}-images-idx3-ubyte.gz", images)
        _write_idx(raw / f"{prefix}-labels-idx1-ubyte.gz", labels)
    labels, speakers, ids = [], [], []
    for speaker in sum(SPEAKER_SPLITS.values(), ()):
        for label in range(10):
            for index in range(4):
                labels.append(label)
                speakers.append(speaker)
                ids.append(f"fsdd:{FSDD_COMMIT}:{label}_{speaker}_{index}.wav")
    np.savez_compressed(
        directory / "fsdd_features_v1.npz",
        x=rng.random((len(labels), 28, 20), dtype=np.float32),
        y=np.array(labels),
        speakers=np.array(speakers),
        ids=np.array(ids),
        duration=np.ones(len(labels)),
    )


class DataContractTests(unittest.TestCase):
    def test_context_adds_no_evidence_and_preserves_event_times(self):
        base = load_data(
            train_size=40, val_size=8, test_size=8, context_length=32, seed=9
        )
        for length in (64, 128):
            expanded = load_data(
                train_size=40, val_size=8, test_size=8, context_length=length, seed=9
            )
            factor = length // 32
            np.testing.assert_array_equal(
                expanded.train.x[:, factor - 1 :: factor], base.train.x
            )
            np.testing.assert_allclose(
                expanded.train.dt.cumsum(1)[:, factor - 1 :: factor],
                base.train.dt.cumsum(1),
                atol=2e-5,
            )
            np.testing.assert_array_equal(expanded.train.y, base.train.y)
            null = np.ones(length, dtype=bool)
            null[factor - 1 :: factor] = False
            self.assertFalse(np.any(expanded.train.x[:, null]))

    def test_synthetic_train_prefix_and_independent_heldout_are_stable(self):
        small = load_data(train_size=32, val_size=12, test_size=16, seed=4)
        large = load_data(train_size=96, val_size=12, test_size=16, seed=4)
        np.testing.assert_array_equal(small.train.x, large.train.x[:32])
        np.testing.assert_array_equal(small.val.x, large.val.x)
        np.testing.assert_array_equal(small.test.x, large.test.x)
        self.assertFalse(set(large.train.group_ids) & set(large.test.group_ids))

    def test_synthetic_task_requires_keyed_evidence_and_is_solvable(self):
        split = load_data(train_size=512, val_size=8, test_size=8, seed=31).train
        predictions = []
        for sequence in split.x:
            key = sequence[-1, 60:64].argmax()
            keep = sequence[:28, :4].argmax(1) == key
            evidence = sequence[:28, 4:8] + sequence[:28, 8:12]
            weights = sequence[:28, 52] ** 2
            predictions.append((evidence[keep] * weights[keep, None]).sum(0).argmax())
        self.assertGreater(np.mean(np.array(predictions) == split.y), 0.97)

    def test_long_memory_oracle_and_absence_of_target_in_later_observations(self):
        split = load_data(
            "long_memory", train_size=1024, val_size=8, test_size=8, seed=28
        ).train
        query = split.x[:, -1, 60:64].argmax(1)
        initial_keys = split.x[:, :4, :8].argmax(2)
        initial_values = (split.x[:, :4, 8:12] + split.x[:, :4, 12:16]).argmax(2)
        positions = (initial_keys == query[:, None]).argmax(1)
        np.testing.assert_array_equal(
            initial_values[np.arange(len(split)), positions], split.y
        )
        self.assertFalse(np.any(split.x[:, 4:-1, :4]))
        self.assertFalse(np.any(split.x[:, :-1, 60:64]))
        self.assertFalse(np.any(split.x[:, -1, :16]))
        # Obvious target proxies without the initial association remain at chance.
        later_values = split.x[:, 4:-1, 8:12] + split.x[:, 4:-1, 12:16]
        self.assertLess(np.mean(later_values.sum(1).argmax(1) == split.y), 0.32)
        self.assertLess(np.mean(query == split.y), 0.32)

    def test_long_memory_contexts_add_observations_and_keep_source_prefixes(self):
        short = load_data(
            "long_memory",
            train_size=16,
            val_size=8,
            test_size=8,
            context_length=32,
            seed=5,
        )
        for length in (64, 128):
            long = load_data(
                "long_memory",
                train_size=24,
                val_size=8,
                test_size=8,
                context_length=length,
                seed=5,
            )
            np.testing.assert_array_equal(short.train.x[:, :-1], long.train.x[:16, :31])
            np.testing.assert_array_equal(
                short.train.dt[:, :31], long.train.dt[:16, :31]
            )
            np.testing.assert_array_equal(
                short.train.x[:, -1, 60:64], long.train.x[:16, -1, 60:64]
            )
            np.testing.assert_array_equal(short.train.y, long.train.y[:16])
            np.testing.assert_array_equal(
                short.train.sample_ids, long.train.sample_ids[:16]
            )
            self.assertTrue(np.all(long.train.x[:, :, 53] == 1))
            self.assertTrue(np.all(long.train.dt[:16].sum(1) > short.train.dt.sum(1)))
            self.assertEqual(long.manifest["distractor_observations"], length - 5)

    def test_real_tasks_separate_sources_speakers_and_hide_query_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            _source_fixture(directory)
            bundle = load_data(
                "multimodal_select", 80, 40, 60, seed=3, cache_dir=directory
            )
            for name in ("train", "val", "test"):
                split = getattr(bundle, name)
                self.assertTrue(
                    set(split.metadata["speakers"]).issubset(SPEAKER_SPLITS[name])
                )
                # Query blocks depend on requested modality, never the digit target.
                for modality in ("image", "spoken"):
                    mask = np.array(split.metadata["query_modalities"]) == modality
                    self.assertGreater(len(set(split.y[mask])), 1)
                    queries = split.x[mask, 28:, 54:]
                    np.testing.assert_array_equal(
                        queries, np.broadcast_to(queries[:1], queries.shape)
                    )
            longer = load_data(
                "multimodal_select", 100, 40, 60, seed=3, cache_dir=directory
            )
            np.testing.assert_array_equal(bundle.train.x, longer.train.x[:80])
            np.testing.assert_array_equal(bundle.test.x, longer.test.x)
            bundle.val.metadata["audio_source_ids"][0] = bundle.train.metadata[
                "audio_source_ids"
            ][0]
            with self.assertRaisesRegex(ValueError, "Source leakage"):
                bundle.validate()

    def test_audio_reuse_is_explicit_and_image_audio_ablations_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            _source_fixture(directory)
            audio = load_data("fsdd", 300, 40, 80, cache_dir=directory)
            self.assertEqual(audio.train.metadata["unique_recordings"], 120)
            self.assertFalse(np.any(audio.train.x[:, :, :28]))
            image = load_data("mnist", 40, 20, 20, cache_dir=directory)
            self.assertFalse(np.any(image.train.x[:, :, 28:48]))
            self.assertEqual(image.train.metadata["unique_images"], 40)

    def test_audio_frontend_handles_silence_and_real_pcm_without_fit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "wave.wav"
            for signal in (
                np.zeros(1600, dtype=np.int16),
                (12000 * np.sin(2 * np.pi * 440 * np.arange(1600) / 8000)).astype(
                    np.int16
                ),
            ):
                with wave.open(str(path), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(8000)
                    handle.writeframes(signal.astype("<i2").tobytes())
                features, duration = audio_features(path)
                self.assertEqual(features.shape, (28, 20))
                self.assertTrue(np.isfinite(features).all())
                self.assertAlmostEqual(duration, 0.2)
                self.assertEqual(bool(np.any(features)), bool(np.any(signal)))


if __name__ == "__main__":
    unittest.main()
