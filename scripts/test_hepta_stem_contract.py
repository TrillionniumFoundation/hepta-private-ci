"""Time contract integration with actual GRU training and SQLite owner recovery."""

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.component_types import Budget, CellError, Partition, StepContext
from hepta_cells.lifecycle import CellOwner
from hepta_cells.stem_contract import (
    TimeContract,
    TimedTemporalComponent,
    restore_run,
    resume_training,
)
from hepta_cells.temporal import TemporalConfig, TemporalKernel, TrainingAttemptError


def component(kernel=None):
    kernel = kernel or TemporalKernel("cell", TemporalConfig(5, 1, 2, hidden_dim=3))
    parts = {key: hashlib.sha256(key.encode()).hexdigest() for key in REQUIRED}
    parts.update({key: None for key in OPTIONAL})
    parts.update(
        base=kernel.kernel_sha256,
        heads=kernel.heads_sha256,
        composition=kernel.config.sha256,
    )
    return TimedTemporalComponent(
        kernel,
        Bundle("time-fixture", 1, parts),
        "run",
        TimeContract(2, "source", "monotonic", "boot", 10_000_000),
        100,
    )


def event(cursor, at, values):
    return {
        "cursor": cursor,
        "available_us": at,
        "values": values,
        "clock_identity": ["source", "monotonic", "boot"],
    }


class StemContractTests(unittest.TestCase):
    def setUp(self):
        self.component = component()
        self.partition = Partition("research", "agent", "cell", "run")
        self.context = StepContext(
            self.partition, "r", self.component.identity, None, Budget()
        )

    def test_real_elapsed_missingness_and_parameter_free_state_updates(self):
        item = event(0, 2_000_100, [0, None])
        encoded = self.component.contract.episodes([[item]], [100])[0, 0]
        np.testing.assert_array_equal(encoded, [0, 0, 1, 0, 2])
        kernel = self.component.inner.kernel
        before = (kernel.weights_sha256, kernel.optimizer_sha256)
        state = self.component.initial_state()
        with patch.object(kernel, "observe", wraps=kernel.observe) as observed:
            result = self.component.step(
                {"operation": "observe", "event": item}, state, self.context
            )
            np.testing.assert_array_equal(observed.call_args.args[1], encoded)
        self.assertEqual(before, (kernel.weights_sha256, kernel.optimizer_sha256))
        self.assertEqual(state, self.component.initial_state())
        self.assertEqual(result.state["available_us"], 2_000_100)
        self.assertEqual(result.output["cursor"], 1)

    def test_invalid_events_rejected_before_neural_work(self):
        valid = event(0, 100, [1, 2])
        cases = [
            {**valid, "cursor": 1},
            {**valid, "available_us": 99},
            {**valid, "available_us": 10_000_101},
            {**valid, "values": [True, 2]},
            {**valid, "clock_identity": ["source", "monotonic", "other-boot"]},
        ]
        for item in cases:
            with (
                self.subTest(item=item),
                patch.object(self.component.inner.kernel, "observe") as observed,
            ):
                with self.assertRaises(CellError):
                    self.component.step(
                        {"operation": "observe", "event": item},
                        self.component.initial_state(),
                        self.context,
                    )
                observed.assert_not_called()

    def test_owner_retry_and_reopen_preserve_clock_cursor_and_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "owner.sqlite"
            owner = CellOwner(path)
            owner.create(self.partition, self.component)
            payload = {"operation": "observe", "event": event(0, 1_000_100, [1, None])}
            first = owner.step(self.partition, self.component, "first", payload)
            retained = owner.checkpoint(self.partition)["state"]
            owner.close()
            owner = CellOwner(path)
            try:
                with patch.object(self.component.inner.kernel, "observe") as observed:
                    self.assertEqual(
                        first,
                        owner.step(self.partition, self.component, "first", payload),
                    )
                    observed.assert_not_called()
                self.assertEqual(retained, owner.checkpoint(self.partition)["state"])
                result = owner.step(
                    self.partition,
                    self.component,
                    "second",
                    {"operation": "observe", "event": event(1, 4_000_100, [None, -1])},
                )
                self.assertEqual(result["output"]["available_us"], 4_000_100)
                self.assertEqual(result["output"]["cursor"], 2)
            finally:
                owner.close()

    def test_run_and_original_training_recovery_are_distinct(self):
        episodes = [
            [event(0, 1_000_100, [1, None]), event(1, 3_000_100, [0, 1])],
            [event(0, 2_000_100, [-1, 0]), event(1, 2_000_100, [None, -1])],
        ]
        starts, actions, allowed = [100, 100], np.zeros((2, 1)), np.eye(2, dtype=bool)
        full, _ = self.component.train_candidate(
            episodes, starts, actions, allowed, updates=4
        )
        half, trained = self.component.train_candidate(
            episodes, starts, actions, allowed, updates=2
        )
        candidate = component(half)
        context = replace(self.context, identity=candidate.identity)
        state = candidate.step(
            {"operation": "observe", "event": episodes[0][0]},
            candidate.initial_state(),
            context,
        ).state
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot"
            saved = candidate.checkpoint(
                path,
                state,
                learning={
                    "data_sha256": trained["data_sha256"],
                    "updates": 2,
                    "lr": 0.003,
                    "clip": 5.0,
                },
            )
            identity = {
                "expected_sha256": saved["manifest_sha256"],
                "expected_identity": candidate.identity.digest,
            }
            restored, restored_state, _, cost = restore_run(path, **identity)
            self.assertEqual(restored_state, state)
            self.assertEqual(
                restored.inner.kernel.optimizer_sha256, half.optimizer_sha256
            )
            self.assertGreater(cost["wall_seconds"], 0)
            np.testing.assert_array_equal(
                restored.inner.kernel.predict(
                    restored_state["temporal"], [0], episode_id="run"
                ),
                half.predict(state["temporal"], [0], episode_id="run"),
            )
            continued, receipt = resume_training(
                path,
                **identity,
                episodes=episodes,
                starts_us=starts,
                actions=actions,
                allowed_mask=allowed,
            )
            self.assertEqual(
                (continued.weights_sha256, continued.optimizer_sha256),
                (full.weights_sha256, full.optimizer_sha256),
            )
            self.assertEqual(receipt["validated_updates"], 2)
            with self.assertRaises(TrainingAttemptError) as error:
                resume_training(
                    path,
                    **identity,
                    episodes=episodes,
                    starts_us=starts,
                    actions=actions,
                    allowed_mask=allowed[:, ::-1],
                )
            self.assertIn("original encoded dataset", str(error.exception))
            with self.assertRaises(TrainingAttemptError):
                restore_run(
                    path,
                    expected_sha256=saved["manifest_sha256"],
                    expected_identity=self.component.identity.digest,
                )

    def test_failed_saves_and_pretraining_encoding_keep_cost_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TrainingAttemptError) as error:
                self.component.checkpoint(tmp, self.component.initial_state())
            self.assertEqual(error.exception.receipt["status"], "failed")
            self.assertGreater(error.exception.receipt["wall_seconds"], 0)
        with self.assertRaises(TrainingAttemptError) as error:
            self.component.train_candidate(
                [[event(0, 99, [1, 2])]], [100], [[0]], [[True, False]]
            )
        self.assertEqual(error.exception.receipt["status"], "failed")
        self.assertGreater(error.exception.receipt["process_cpu_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
