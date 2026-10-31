"""Causal information, semantics, and append-only serialization invariants."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .facts import PublicFrame, action_fact, features, observed_metrics, owner_public_frame, parse_facts, source_manifest
from .policy import predict, public_reference, state_features, train_model
from .speech import write_pcm
from .stream import AppendOnlyOutput, verify_output


class CausalSpeechTests(unittest.TestCase):
    def test_root_policy_cannot_change_with_later_observation(self):
        frame = owner_public_frame((2, 0, 1), "synthetic-fixture", 1)
        later = replace(frame, fresh=(7, 3, 2), posterior=((.01,) * 7 + (.93,), (.01, .01, .01, .97), (.01, .01, .97, .01)),
                        probe_fact=(7, 3, 2), probe_confidence=.15, probe_word_count=8)
        np.testing.assert_array_equal(features(frame, initial_only=True), features(later, initial_only=True))
        self.assertFalse(np.array_equal(features(frame), features(later)))
        with self.assertRaises(TypeError):
            features({**frame.serialized(), "target": (2, 0, 1), "future_audio": "private"})

    def test_same_information_fusion_and_shared_clamp(self):
        frame = PublicFrame((0, 0, 0), (.55, .55, .55), (2, 2, 2), (.95, .95, .95),
                            ((.01, .01, .93, .01, .01, .01, .01, .01), (.02, .02, .94, .02), (.02, .02, .94, .02)),
                            (0, 0, 0), .9, 10)
        self.assertEqual(action_fact(frame, "fuse_normal"), (2, 2, 2))
        self.assertEqual(action_fact(frame, "fuse_slow"), (2, 2, 2))
        self.assertEqual(action_fact(frame, "fuse_clamp_normal"), (0, 0, 0))
        with self.assertRaises(ValueError):
            action_fact(frame, "private_target")

    def test_missing_ambiguous_audio_never_completes_task(self):
        text = "The number is three. The color is red. The direction is south."
        for audio in ("", "the number is three", "three four red south"):
            metric = observed_metrics((2, 0, 1), text, audio, True)
            self.assertFalse(metric["required_semantic_completion"])
            self.assertFalse(metric["joint_task_success"])
        wrong = observed_metrics((2, 0, 1), text, "four red south", True)
        self.assertTrue(wrong["required_semantic_completion"])
        self.assertFalse(wrong["joint_task_success"])

    def test_source_manifest_preserves_group_disjointness(self):
        manifest = source_manifest()
        ids = [row["source_id"] for rows in manifest["roles"].values() for row in rows]
        facts = [tuple(row["fact"]) for rows in manifest["roles"].values() for row in rows]
        self.assertEqual((len(set(ids)), len(set(facts))), (len(ids), len(facts)))

    def test_external_number_spelling_is_target_independent(self):
        self.assertEqual(parse_facts("The number is 3; red; south"), (2, 0, 1))
        self.assertEqual(parse_facts("The number is three; red; south"), (2, 0, 1))
        self.assertIsNone(parse_facts("The number is 3 or 4; red; south")[0])

    def test_declared_prior_risk_reference_uses_same_fusion_budget(self):
        frame = PublicFrame((0, 0, 0), (.55, .55, .55), (2, 2, 2), (.95, .95, .95),
                            ((.01, .01, .93, .01, .01, .01, .01, .01), (.02, .02, .94, .02), (.02, .02, .94, .02)),
                            (0, 0, 0), .9, 10)
        self.assertEqual(public_reference(frame), "fuse_normal")
        unchanged = replace(frame, initial=(2, 2, 2))
        self.assertEqual(public_reference(unchanged), "keep_normal")

    def test_positive_conditional_value_learns_held_out_public_signal(self):
        frames = [owner_public_frame((index % 8, index % 4, (index // 4) % 4),
                                     f"test-{index}", index % 4) for index in range(24)]
        x = np.asarray([state_features(frame, "initial_only") for frame in frames])
        target = np.asarray([[.25, .8, .3, .9] if frame.initial_quality[0] < .7 else [.8, .25, .9, .3]
                             for frame in frames])
        model = train_model(x, target, 17)
        self.assertLess(model["final_fit_mse"], model["initial_fit_mse"] / 5)
        for index in range(6):
            unseen = owner_public_frame((index, 2, 1), f"held-out-test-{index}", index % 4)
            prediction = predict(model, unseen, "initial_only")
            self.assertTrue(np.all(prediction > 0))
            expected = 0 if unseen.initial_quality[0] < .7 else 1
            self.assertEqual(int(np.argmin(prediction)), expected)

    def test_committed_prefix_cannot_silently_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a, b = root / "a.wav", root / "b.wav"
            write_pcm(a, 16000, np.arange(257, dtype=np.int16))
            write_pcm(b, 16000, -np.arange(113, dtype=np.int16))
            stream = AppendOnlyOutput(root / "output", 16000)
            stream.append("prefix", a, "prefix")
            stream.append("future words", b, "future")
            receipt = stream.finish()
            self.assertEqual((receipt["samples"], receipt["commit_count"]), (370, 2))
            self.assertEqual(receipt, verify_output(root / "output"))
            with self.assertRaises(RuntimeError):
                stream.append("rewrite", a, "late")
            text = root / "output/output.txt"
            text.write_bytes(text.read_bytes().replace(b"prefix", b"PREFIX"))
            with self.assertRaises(ValueError):
                verify_output(root / "output")


if __name__ == "__main__":
    unittest.main()
