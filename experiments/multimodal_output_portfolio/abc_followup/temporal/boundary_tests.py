"""Causal information, physical stream and source-crossfit invariants."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from experiments.multimodal_output_portfolio.abc_next.temporal.speech import write_pcm, sha256
from experiments.multimodal_output_portfolio.abc_next.temporal.stream import verify_output
from .episodes import execute
from .state import CueOwner, Frame, features, initial_frame
from .tasks import manifest
from . import value


class ActualPcmFixture:
    """Test fixture writes physical PCM; never counted as neural evidence."""

    def __init__(self):
        self.texts = {}
        self.observed_paths = []

    def synthesize(self, text, output):
        write_pcm(output, 16000, np.full(1600, 1200, dtype=np.int16))
        self.texts[str(output)] = text
        return {"sample_rate": 16000, "sha256": sha256(output), "wall_ns": 1, "cpu_ns": 1}

    def observe(self, path):
        self.observed_paths.append(str(path))
        text = self.texts.get(str(path))
        if text is None:
            text = (Path(path).parent / "output.txt").read_text()
        return {"transcript": text, "mean_word_confidence": .9,
                "input_sha256": sha256(path), "wall_ns": 1, "cpu_ns": 1}


class RecordingPolicy:
    def __init__(self):
        self.seen = []
        self.variant = "full"

    def needs_prefix_probe(self):
        return self.variant == "full"

    def feedback_action(self, frame):
        if type(frame) is not Frame:
            raise AssertionError("Private owner leaked")
        self.seen.append(frame)
        return int(frame.stage == 0)


class BoundaryTests(unittest.TestCase):
    def test_actual_acquisition_is_action_gated_and_prefix_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episode"
            policy = RecordingPolicy()
            row = execute(ActualPcmFixture(), manifest()["roles"]["development"][0], 0, 0,
                          path, "feedback", policy=policy)
            self.assertEqual([r["cue_index"] for r in row["acquisitions"]], [1, 2])
            self.assertEqual([len(frame.observations) for frame in policy.seen], [1, 2])
            self.assertFalse((path / "cue-3.wav").exists())
            self.assertTrue(all(not r["optional_cue_exists"] for r in row["decisions"]))
            self.assertLess(row["decisions"][0]["decision_ns"], row["acquisitions"][1]["released_ns"])
            self.assertTrue(verify_output(path / "output")["exact_committed_span_readback"])
            text = path / "output" / "output.txt"
            text.write_text("Tampered prefix.\n" + text.read_text())
            with self.assertRaises(ValueError):
                verify_output(path / "output")

    def test_constant_route_retains_fusion_and_skips_unused_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = manifest()["roles"]["development"][0]
            row = execute(ActualPcmFixture(), source, 0, 0, Path(directory) / "episode", "fixed", (1, 1))
            self.assertEqual([r["cue_index"] for r in row["acquisitions"]], [1, 2, 3])
            self.assertEqual(row["prefix_probes"], [])
            self.assertEqual(row["route"], [1, 1])
            self.assertEqual(len(row["frames"][1]["observations"]), 2)

    def test_initial_route_features_ignore_later_observations(self):
        frame = initial_frame((0, 0, 0), 0)
        state = frame.detached()
        state.update(posterior=((0.,) * 7 + (1.,), (0., 1., 0., 0.), (0., 0., 1., 0.)),
                     observations=((7, 1, 2),), observation_confidence=(.99,))
        altered = Frame(**state)
        np.testing.assert_array_equal(features(frame, initial_only=True), features(altered, initial_only=True))
        self.assertFalse(np.array_equal(features(frame), features(altered)))
        with self.assertRaises(TypeError):
            features(CueOwner(manifest()["roles"]["development"][0], 0))

    def test_cue_only_physically_omits_probe_and_masks_its_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = RecordingPolicy()
            policy.variant = "cue_only"
            backend = ActualPcmFixture()
            row = execute(backend, manifest()["roles"]["development"][0], 0, 0,
                          Path(directory) / "episode", "feedback", policy=policy)
            self.assertEqual(row["prefix_probes"], [])
            self.assertFalse(any(path.endswith("chunk-0.wav") for path in backend.observed_paths))
            self.assertEqual(tuple(row["frames"][1]["previous_audio_fact"]), (None, None, None))
        frame = initial_frame((0, 0, 0), 0)
        data = frame.detached()
        data["previous_audio_fact"] = (7, 3, 2)
        altered = Frame(**data)
        np.testing.assert_array_equal(value.public_features(frame, "cue_only"), value.public_features(altered, "cue_only"))
        self.assertFalse(np.array_equal(value.public_features(frame, "full"), value.public_features(altered, "full")))

    def test_crossfit_backup_does_not_use_own_fold_future_labels(self):
        rng = np.random.default_rng(31)
        x = rng.normal(size=(24, 4))
        labels = np.full((24, 2), np.nan)
        labels[np.arange(24), np.arange(24) % 2] = rng.uniform(.1, 1., 24)
        assignment = np.repeat([0, 1], 12)
        old = value.FIT["steps"]
        value.FIT["steps"] = 30
        try:
            first = value.crossfit_continuation(x, labels, assignment, 17)
            changed = labels.copy()
            changed[assignment == 0] *= 3
            second = value.crossfit_continuation(x, changed, assignment, 17)
        finally:
            value.FIT["steps"] = old
        np.testing.assert_array_equal(first[assignment == 0], second[assignment == 0])
        self.assertTrue(np.isfinite(first).all())
        self.assertTrue((first > 0).all())
        self.assertFalse(np.array_equal(first[assignment == 1], second[assignment == 1]))

    def test_selection_census_rejects_consistently_rehashed_duplicate_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = []
            labels = ("fixed-00", "fixed-01", "fixed-10", "fixed-11", "initial", "feedback-full", "feedback-cue_only")
            for source in manifest()["roles"]["selection"]:
                for template in (0, 1):
                    for scenario in (0, 1):
                        for label in labels:
                            mode = "fixed" if label.startswith("fixed-") else "feedback" if label.startswith("feedback-") else "initial"
                            path = root / f"case-{len(entries)}.json"
                            row = {"source_id": source["source_id"], "template": template, "scenario": scenario,
                                   "mode": mode, "route": [int(v) for v in label[-2:]] if mode == "fixed" else [0, 0],
                                   "feedback_variant": label.removeprefix("feedback-") if mode == "feedback" else None,
                                   "prefix_probes": [{}] if label == "feedback-full" else [], "offline_observation": None}
                            path.write_text(json.dumps(row))
                            entries.append({"source_id": source["source_id"], "template": template, "scenario": scenario,
                                            "policy": label, "case": str(path), "sha256": sha256(path)})

            def close_index(records):
                index = root / "index.jsonl"
                index.write_text("\n".join(json.dumps(r) for r in records) + "\n")
                (root / "complete.json").write_text(json.dumps({"role": "selection", "complete": True,
                      "requests": 448, "source_groups": 16, "index_sha256": sha256(index)}))

            close_index(entries)
            self.assertEqual(len(value.selection_rows(root)), 448)
            close_index([*entries[:-1], entries[0]])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                value.selection_rows(root)
            close_index(entries[:-1])
            with self.assertRaisesRegex(ValueError, "Missing"):
                value.selection_rows(root)
            close_index(entries)
            (root / "index.jsonl").write_text((root / "index.jsonl").read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "index changed"):
                value.selection_rows(root)


if __name__ == "__main__":
    unittest.main()
