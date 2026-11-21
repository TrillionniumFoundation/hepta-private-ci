import tempfile
from pathlib import Path
import unittest

import numpy as np

from .budget import Budget, CostLedger, CostUncertain
from .continuation import fit_continuation, solve_continuation


class ContinuationTests(unittest.TestCase):
    def test_threshold_projection_exposes_nonmonotone_loss(self):
        transition = np.eye(3)
        reset = np.tile([0.0, 1.0, 0.0], (3, 1))
        critic = solve_continuation(transition, reset, [-2.0, 0.0, -2.0], [-0.3] * 3,
                                    grid=[-1.0, 0.0, 1.0], occupancy=np.ones(3),
                                    support=np.ones(3, dtype=bool), horizon=4)
        report = critic.report()
        self.assertEqual(report["non_single_threshold_contexts"], 1)
        self.assertGreater(report["weighted_projection_value_gap"], 0)
        self.assertTrue(np.all(critic.value >= critic.projected_value - 1e-12))

    def test_monotone_policy_is_represented_without_projection_loss(self):
        critic = solve_continuation(np.eye(3), np.tile([0.0, 0.0, 1.0], (3, 1)),
                                    [-2.0, -0.1, 0.0], [-0.3] * 3,
                                    grid=[-1.0, 0.0, 1.0], occupancy=np.ones(3),
                                    support=np.ones(3, dtype=bool), horizon=4)
        np.testing.assert_allclose(critic.value, critic.projected_value, atol=1e-12)

    def test_training_split_is_mandatory_and_record_replays_queries(self):
        observations = np.random.default_rng(2).normal(size=(12, 8, 2))
        with self.assertRaises(ValueError):
            fit_continuation(observations, split="dev")
        critic = fit_continuation(observations, split="train", horizon=8)
        restored = type(critic).from_record(critic.to_record())
        np.testing.assert_array_equal(critic.query(observations[:, 0], 3),
                                      restored.query(observations[:, 0], 3))

    def test_nonfinite_grid_and_nonstochastic_transition_are_rejected(self):
        arguments = dict(reset_transition=np.eye(2), reward=[0.0, 0.0], reset_reward=[-1.0, -1.0],
                         occupancy=np.ones(2), support=np.ones(2, dtype=bool), horizon=2)
        with self.assertRaises(ValueError):
            solve_continuation(np.eye(2), grid=[-float("inf"), float("inf")], **arguments)
        with self.assertRaises(ValueError):
            solve_continuation(np.eye(2) * 1.000005, grid=[0.0, 1.0], **arguments)

    def test_failed_work_is_charged_and_unfinished_work_blocks_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cost.jsonl"
            ledger = CostLedger(path, Budget(), "test")
            with self.assertRaises(RuntimeError):
                with ledger.operation("rejected_patch", training_examples=7, proposals=1):
                    raise RuntimeError("synthetic failure")
            restored = CostLedger(path, Budget(), "test")
            self.assertEqual(restored.cost["training_examples"], 7)
            self.assertEqual(restored.cost["failures"], 1)
            restored._append(dict(kind="reserve", operation=len(restored.records),
                                  name="interrupted", charge={"training_examples": 3}))
            with self.assertRaises(CostUncertain):
                CostLedger(path, Budget(), "test")


if __name__ == "__main__":
    unittest.main()
