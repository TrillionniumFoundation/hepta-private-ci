"""Behavioral checks for acquisition order, history, and exact continuation."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .stream_runtime import (FeatureSource, State, checkpoint, create_store,
                             restore, run, step)


def fixture(root, name, future=3):
    x = np.zeros((6, 40), np.float32)
    x[:, :16] = np.arange(6)[:, None]
    x[3:, :16] = future
    x[:, 16:32] = 999  # These inherited deltas must never reach the encoder.
    x[:, 32] = x[:, 34] = 1
    create_store(root / name, x, np.arange(1, 7) * .1, np.ones(6, bool))
    return root / name


def predictor(rows):
    probability = .5 + .04 * float(rows[-1, 0])
    return [probability, 1 - probability]


class CausalRuntimeTests(unittest.TestCase):
    def test_wait_does_not_read_or_encode(self):
        with tempfile.TemporaryDirectory() as temp:
            source = FeatureSource(fixture(Path(temp), "one"))
            state = State(2)
            policy = dict(kind="periodic", period_seconds=.1)
            step(source, state, policy, predictor)
            self.assertEqual((source.payload_reads, source.payload_bytes, state.encoder_calls), (0, 0, 0))
            self.assertEqual(state.trace[0]["action"], "WAIT")
            source.close()

    def test_stop_never_acquires_future_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            states = []
            for name, future in (("a", 3), ("b", 100)):
                source = FeatureSource(fixture(Path(temp), name, future))
                state = run(source, State(2), dict(kind="confidence", threshold=.53, minimum_reads=2), predictor)
                states.append((state.trace, state.probabilities, source.payload_reads))
                source.close()
            self.assertEqual(states[0], states[1])
            self.assertEqual(states[0][2], 2)

    def test_only_read_payload_changes_content(self):
        with tempfile.TemporaryDirectory() as temp:
            traces = []
            for name, future in (("a", 3), ("b", 5)):
                source = FeatureSource(fixture(Path(temp), name, future))
                state = run(source, State(2), dict(kind="all"), predictor)
                traces.append(state.trace)
                source.close()
            self.assertEqual(traces[0][:3], traces[1][:3])
            self.assertEqual(traces[0][3]["before"], traces[1][3]["before"])
            self.assertNotEqual(traces[0][3]["after"], traces[1][3]["after"])

    def test_delta_uses_last_accepted_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = FeatureSource(fixture(Path(temp), "one"))
            state = run(source, State(2), dict(kind="periodic", period_seconds=.1), predictor)
            rows = np.asarray(state.rows)
            np.testing.assert_array_equal(rows[:, 0], [1, 3, 3])
            np.testing.assert_array_equal(rows[:, 16], [0, 2, 0])
            self.assertEqual(state.encoder_calls, source.payload_reads)
            source.close()

    def test_checkpoint_resumes_identical_actions_and_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = fixture(Path(temp), "one")
            original = FeatureSource(directory)
            policy = dict(kind="periodic", period_seconds=.1)
            expected = run(original, State(2), policy, predictor)
            partial = FeatureSource(directory)
            state = State(2)
            for _ in range(3):
                step(partial, state, policy, predictor)
            path = Path(temp) / "checkpoint.json"
            checkpoint(partial, state, policy, path, encoder_identity="test-v1")
            partial.close()
            resumed, state, recovered, _ = restore(path, encoder_identity="test-v1")
            actual = run(resumed, state, recovered, predictor)
            self.assertEqual((actual.trace, actual.rows, actual.probabilities),
                             (expected.trace, expected.rows, expected.probabilities))
            self.assertEqual((resumed.payload_reads, resumed.payload_bytes),
                             (original.payload_reads, original.payload_bytes))
            original.close()
            resumed.close()

    def test_changed_schedule_is_rejected_on_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = fixture(Path(temp), "one")
            source = FeatureSource(directory)
            path = Path(temp) / "checkpoint.json"
            checkpoint(source, State(2), dict(kind="all"), path, encoder_identity="test-v1")
            source.close()
            header = directory / "headers.json"
            record = json.loads(header.read_text())
            record["headers"][0]["time"] = 100
            header.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "identity changed"):
                restore(path, encoder_identity="test-v1")

    def test_changed_payload_is_rejected_only_when_read(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = fixture(Path(temp), "one")
            source = FeatureSource(directory)
            state = State(2)
            step(source, state, dict(kind="all"), predictor)
            path = Path(temp) / "checkpoint.json"
            checkpoint(source, state, dict(kind="all"), path, encoder_identity="test-v1")
            source.close()
            with (directory / "payload.bin").open("r+b") as stream:
                stream.seek(3 * 64)
                stream.write(np.full(16, 5, dtype="<f4").tobytes())
            resumed, state, policy, _ = restore(path, encoder_identity="test-v1")
            for _ in range(2):
                step(resumed, state, policy, predictor)
            with self.assertRaisesRegex(ValueError, "payload identity changed"):
                step(resumed, state, policy, predictor)
            resumed.close()

    def test_encoder_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = FeatureSource(fixture(Path(temp), "one"))
            path = Path(temp) / "checkpoint.json"
            checkpoint(source, State(2), dict(kind="all"), path, encoder_identity="test-v1")
            source.close()
            with self.assertRaisesRegex(ValueError, "Encoder identity changed"):
                restore(path, encoder_identity="test-v2")

    def test_nonfinite_clock_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            x = np.zeros((1, 40), np.float32)
            x[:, 32] = x[:, 34] = 1
            with self.assertRaisesRegex(ValueError, "clock"):
                create_store(Path(temp) / "one", x, [np.nan], [True])


if __name__ == "__main__":
    unittest.main()
