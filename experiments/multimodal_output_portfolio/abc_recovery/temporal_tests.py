"""Causality and actual lossless serialization tests on synthetic media only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from .temporal_codec import CommitSink, Reference, audio_timeline, observe_output
from .temporal_statistics import summarize
from .temporal_run import do_evaluation
from .temporal_transport import (FEEDBACK, FIXED, FRAME_TICKS, RATE, episode_seed,
                                 fit_policy, loss, network_events, simulate)


class TemporalTests(unittest.TestCase):
    def test_audio_timeline_measures_origin_and_detects_packet_clock_discontinuity(self):
        frames = [{"pts_time": ".080000", "nb_samples": 1764},
                  {"pts_time": ".120000", "nb_samples": 792}]
        start, error, samples = audio_timeline(frames)
        self.assertEqual((start, samples), (.08, 2556))
        self.assertLess(error, 1e-10)
        changed = deepcopy(frames)
        changed[1]["pts_time"] = ".160000"
        self.assertAlmostEqual(audio_timeline(changed)[1], .04)

    def test_evaluation_release_gate_precedes_any_source_or_network_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            protocol = folder / "protocol.json"
            protocol.write_text("prospective protocol")
            protocol_sha = hashlib.sha256(protocol.read_bytes()).hexdigest()
            model = {"protocol_sha256": protocol_sha, "fit_role": "fit", "fixed_comparison": FIXED[0],
                     "feedback_parameters": {"base_ms": 80, "margin_ms": 40},
                     "source_code_pins": {"temporal_transport.py": hashlib.sha256(Path(__file__).with_name("temporal_transport.py").read_bytes()).hexdigest()}}
            fit = folder / "policy.json"
            fit.write_text(json.dumps(model))
            policy_sha = hashlib.sha256(fit.read_bytes()).hexdigest()
            qualification = folder / "qualification.json"
            qualification.write_text(json.dumps({"qualified": True, "protocol_sha256": protocol_sha, "policy_sha256": policy_sha}))
            release = folder / "release.json"
            release.write_text(json.dumps({"authorized_by": "root", "protocol_sha256": protocol_sha,
                "policy_sha256": policy_sha, "qualification_sha256": hashlib.sha256(qualification.read_bytes()).hexdigest()}))
            args = SimpleNamespace(protocol=protocol, fit=fit, qualification=qualification, eval_release=release)
            with patch("experiments.multimodal_output_portfolio.abc_recovery.temporal_run.registered_sources", side_effect=AssertionError("evaluation opened")):
                with self.assertRaisesRegex(ValueError, "after A/B mechanism"):
                    do_evaluation(args, {}, {}, {})

    def test_future_events_do_not_change_the_observed_action_prefix(self):
        events = network_events(episode_seed("synthetic", 3), 3)
        changed = deepcopy(events)
        cutoff = 10 * FRAME_TICKS
        for event in changed:
            if event["release_ticks"] > cutoff:
                event["arrival_ticks"] = event["release_ticks"] + 20 * FRAME_TICKS
                event["environment_dropped"] = False
        one = simulate(events, FEEDBACK, {"base_ms": 80, "margin_ms": 40})
        two = simulate(changed, FEEDBACK, {"base_ms": 80, "margin_ms": 40})
        self.assertEqual([row for row in one["public_trace"] if row["now_ticks"] <= cutoff],
                         [row for row in two["public_trace"] if row["now_ticks"] <= cutoff])
        self.assertEqual(len(one["commit_ticks"]), 75)
        self.assertTrue(all(delay <= .240001 for delay in one["simulated_delivery_latency_seconds"]))
        self.assertNotIn("environment_dropped", one["public_trace"][0]["public_state"])
        with self.assertRaisesRegex(ValueError, "fit role"):
            fit_policy([{"role": "evaluation"}])

    def test_actual_lossless_clock_readback_and_irreversible_silent_packet_coverage(self):
        width, height, count = 32, 24, 3
        black = np.full(width * height * 3 // 2, 128, np.uint8)
        black[:width * height] = 16
        frames = np.stack([black.copy() for _ in range(count)])
        audio = np.zeros((count * FRAME_TICKS - 99, 2), dtype="<i2")
        reference = Reference("silent-source", width, height, frames, audio, tuple(i * .04 for i in range(count)))
        with tempfile.TemporaryDirectory() as temporary:
            sink = CommitSink(reference, Path(temporary) / "actual")
            sink.commit(0, {"video": True, "audio": True}, FRAME_TICKS)
            prefix = sink.video_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "cannot be rewritten"):
                sink.commit(0, {"video": False, "audio": False}, FRAME_TICKS * 2)
            self.assertEqual(sink.video_path.read_bytes(), prefix)
            with self.assertRaisesRegex(ValueError, "No terminal truncation"):
                sink.finish()
            sink.commit(1, {"video": False, "audio": True}, FRAME_TICKS * 2)
            sink.commit(2, {"video": True, "audio": False}, FRAME_TICKS * 3)
            path = sink.finish(relative_audio_delay_ms=80)
            result = observe_output(path, reference, sink.records, sink.directory)
            self.assertTrue(result["content_fidelity_passed"])
            self.assertEqual((result["video_frames"], result["audio_samples_per_channel"]), (count, len(audio)))
            self.assertAlmostEqual(result["signed_relative_audio_clock_offset_seconds"], .080, places=3)
            self.assertEqual(result["source_delivery_video_fraction"], 2 / 3)
            self.assertEqual(result["source_delivery_audio_fraction"], (2 * FRAME_TICKS) / len(audio))
            self.assertEqual(result["valid_alignment_coverage"], 1 / 3)
            self.assertGreater(result["missing_alignment_penalty"], 0)
            sink.cleanup()
            self.assertTrue(path.is_file())
            self.assertFalse(sink.video_path.exists())
        self.assertEqual(loss(0, 0, None, 0, 0), .8)

    def test_bootstrap_keeps_all_repeated_scenarios_in_the_speaker_group(self):
        rows = []
        for speaker in range(4):
            for scenario in range(4):
                for policy in FIXED + (FEEDBACK,):
                    rows.append({"speaker": speaker, "scenario": scenario, "policy": policy,
                        "loss": .3 + .01 * speaker + .005 * scenario - .2 * (policy == FEEDBACK),
                        "q_video": 1, "q_audio": 1, "joint_delivery_completion": 1,
                        "valid_alignment_coverage": 1, "valid_clock_error_seconds": 0,
                        "completed_and_fidelity_passed": True})
        result = summarize(rows, list(range(4)), FIXED[0], replicates=101, seed=7)
        self.assertEqual(result["independent_speaker_groups"], 4)
        self.assertTrue(np.allclose(result["feedback_minus_fixed_NDU_95CI"], [.2, .2]))
        self.assertTrue(result["engineering_transport_benefit_gate_passed"])
        with self.assertRaisesRegex(ValueError, "exactly once"):
            summarize(rows + [rows[0]], list(range(4)), FIXED[0], replicates=101)
        rows[0]["completed_and_fidelity_passed"] = False
        rows[0]["loss"] = 1
        self.assertFalse(summarize(rows, list(range(4)), FIXED[0], replicates=101)["engineering_transport_benefit_gate_passed"])


if __name__ == "__main__":
    unittest.main()
