"""Behavioral checks for the owner-bound temporal Cell and actual Adam resume."""

import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

import numpy as np

from hepta_cells.temporal import TemporalConfig, TemporalKernel, TrainingAttemptError


class TemporalCellTests(unittest.TestCase):
    def setUp(self):
        self.config = TemporalConfig(input_dim=3, action_dim=2, output_dim=2, hidden_dim=6, seed=41)
        self.kernel = TemporalKernel("prediction-cell", self.config)
        self.x = np.zeros((12, 5, 3), dtype=np.float64)
        self.x[:6, 0, 0], self.x[6:, 0, 0] = -1.0, 1.0
        self.actions = np.zeros((12, 2))
        self.labels = np.eye(2, dtype=bool)[np.arange(12) // 6]

    def state_after(self, kernel, observations, episode="episode-1"):
        state = kernel.initial_state(episode)
        for cursor, observation in enumerate(observations):
            state = kernel.observe(state, observation, episode_id=episode, cursor=cursor)
        return state

    def nll(self, kernel):
        logits = np.stack([kernel.predict(self.state_after(kernel, x), a, episode_id="episode-1")
                           for x, a in zip(self.x, self.actions)])
        return float(np.mean(np.logaddexp.reduce(logits, axis=1) - logits[self.labels]))

    def test_true_learning_is_isolated_and_requires_new_hidden_state(self):
        old_state = self.state_after(self.kernel, self.x[0])
        original = (self.kernel.weights_sha256, self.kernel.optimizer_sha256, copy.deepcopy(old_state))
        before = self.nll(self.kernel)
        candidate, receipt = self.kernel.train_candidate(self.x, self.actions, self.labels, updates=25, lr=0.02)
        self.assertLess(self.nll(candidate), before - 0.05)
        self.assertNotEqual(candidate.weights_sha256, original[0])
        self.assertNotEqual(candidate.optimizer_sha256, original[1])
        self.assertEqual((self.kernel.weights_sha256, self.kernel.optimizer_sha256, old_state), original)
        with self.assertRaisesRegex(ValueError, "weights or episode mismatch"):
            candidate.predict(old_state, [0, 0], episode_id="episode-1")
        fresh = candidate.initial_state("episode-2")
        self.assertEqual(fresh["hidden"], {"fast": [[0.0] * self.config.hidden_dim]})
        self.assertEqual(fresh["cursor"], 0)
        self.assertEqual(receipt["validated_updates"], 25)
        self.assertEqual(receipt["status"], "completed_candidate_only")
        self.assertEqual(receipt["resources"]["persistent_state_array_bytes"], 6 * 8)
        self.assertGreater(receipt["resources"]["parameter_array_bytes"], 0)
        self.assertEqual(receipt["resources"]["optimizer_array_bytes"],
                         2 * receipt["resources"]["parameter_array_bytes"])
        self.assertIsNone(receipt["energy_joules"])
        self.assertGreaterEqual(receipt["wall_seconds"], 0)
        self.assertGreaterEqual(receipt["process_cpu_seconds"], 0)

    def test_checkpoint_exactly_resumes_hidden_and_next_optimizer_update(self):
        candidate, _ = self.kernel.train_candidate(self.x, self.actions, self.labels, updates=4)
        state = self.state_after(candidate, self.x[0, :2])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.npz"
            digest = candidate.checkpoint(path, state)
            restored, recovered_state = TemporalKernel.restore_checkpoint(
                path, expected_sha256=digest, cell_id=candidate.cell_id, config=self.config)
            self.assertEqual(state, recovered_state)
            self.assertEqual((candidate.weights_sha256, candidate.optimizer_sha256),
                             (restored.weights_sha256, restored.optimizer_sha256))
            np.testing.assert_array_equal(candidate.predict(state, [1, 0], episode_id="episode-1"),
                                          restored.predict(recovered_state, [1, 0], episode_id="episode-1"))
            self.assertEqual(candidate.observe(state, [0.2, 0.3, -0.4], episode_id="episode-1", cursor=2),
                             restored.observe(recovered_state, [0.2, 0.3, -0.4], episode_id="episode-1", cursor=2))
            next_a, a_receipt = candidate.train_candidate(self.x, self.actions, self.labels, updates=3)
            next_b, b_receipt = restored.train_candidate(self.x, self.actions, self.labels, updates=3)
            self.assertEqual((next_a.weights_sha256, next_a.optimizer_sha256, a_receipt["losses"]),
                             (next_b.weights_sha256, next_b.optimizer_sha256, b_receipt["losses"]))
            with self.assertRaises(FileExistsError):
                candidate.checkpoint(path, state)
            for wrong in ({"expected_sha256": "0" * 64}, {"cell_id": "another-cell"},
                          {"config": TemporalConfig(3, 2, 2, hidden_dim=7)}):
                kwargs = dict(expected_sha256=digest, cell_id=candidate.cell_id, config=self.config)
                kwargs.update(wrong)
                with self.assertRaises(ValueError):
                    TemporalKernel.restore_checkpoint(path, **kwargs)

    def test_rejects_invalid_optimizer_even_with_a_matching_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.npz"
            self.kernel.checkpoint(path, self.kernel.initial_state("episode-1"))
            with np.load(path, allow_pickle=False) as data:
                payload = {k: data[k] for k in data.files}
            payload["v_Wz"][0, 0] = -1.0
            raw = io.BytesIO()
            np.savez_compressed(raw, **payload)
            path.write_bytes(raw.getvalue())
            with self.assertRaisesRegex(ValueError, "invalid checkpoint parameter or optimizer"):
                TemporalKernel.restore_checkpoint(path, expected_sha256=hashlib.sha256(raw.getvalue()).hexdigest(),
                                                  cell_id=self.kernel.cell_id, config=self.config)

    def test_candidates_and_future_observations_do_not_rewrite_observed_belief(self):
        state = self.state_after(self.kernel, [[1, 0, 0]])
        frozen = copy.deepcopy(state)
        first = self.kernel.predict(state, [1, 0], episode_id="episode-1")
        for action in ([0, 1], [-100, 30], [1, 1]):
            self.kernel.predict(state, action, episode_id="episode-1")
        branch = self.kernel.observe(state, [-5, 2, 1], episode_id="episode-1", cursor=1)
        self.assertEqual(state, frozen)
        np.testing.assert_array_equal(first, self.kernel.predict(state, [1, 0], episode_id="episode-1"))
        self.assertNotEqual(branch["hidden"], state["hidden"])
        replay = self.kernel.observe(frozen, [-5, 2, 1], episode_id="episode-1", cursor=1)
        self.assertEqual(branch, replay)

    def test_owner_episode_cursor_and_finiteness_are_enforced(self):
        state = self.state_after(self.kernel, [[1, 0, 0]])
        other = TemporalKernel("different-cell", self.config)
        with self.assertRaises(ValueError):
            other.predict(state, [0, 0], episode_id="episode-1")
        with self.assertRaises(ValueError):
            self.kernel.predict(state, [0, 0], episode_id="another-episode")
        for cursor in (0, 2, True):
            with self.assertRaises(ValueError):
                self.kernel.observe(state, [1, 0, 0], episode_id="episode-1", cursor=cursor)
        for vector in ([np.nan, 0, 0], [1, 0]):
            with self.assertRaises(ValueError):
                self.kernel.observe(state, vector, episode_id="episode-1", cursor=1)
        damaged = copy.deepcopy(state)
        damaged["hidden"]["fast"][0][0] = np.inf
        with self.assertRaises(ValueError):
            self.kernel.predict(damaged, [0, 0], episode_id="episode-1")

    def test_unknown_labels_do_not_consume_adam_momentum(self):
        candidate, _ = self.kernel.train_candidate(self.x, self.actions, self.labels, updates=3)
        unchanged, receipt = candidate.train_candidate(self.x, self.actions, np.ones_like(self.labels), updates=2)
        self.assertEqual((unchanged.weights_sha256, unchanged.optimizer_sha256),
                         (candidate.weights_sha256, candidate.optimizer_sha256))
        self.assertEqual(receipt["validated_updates"], 0)
        self.assertEqual(receipt["losses"], [0.0, 0.0])

    def test_failed_attempt_retains_cost_and_parent_weights(self):
        before = (self.kernel.weights_sha256, self.kernel.optimizer_sha256)
        with self.assertRaises(TrainingAttemptError) as failure:
            self.kernel.train_candidate(self.x, self.actions, self.labels, lr=0)
        receipt = failure.exception.receipt
        self.assertEqual(receipt["status"], "failed")
        self.assertGreaterEqual(receipt["wall_seconds"], 0)
        self.assertGreaterEqual(receipt["process_cpu_seconds"], 0)
        self.assertIsNone(receipt["energy_joules"])
        self.assertEqual(before, (self.kernel.weights_sha256, self.kernel.optimizer_sha256))

    def test_diagonal_recurrence_trains_but_hcsn_cannot_silently_fallback(self):
        diagonal = TemporalKernel("prediction-cell", TemporalConfig(3, 2, 2, hidden_dim=6, kind="diag_ssm"))
        updated, _ = diagonal.train_candidate(self.x, self.actions, self.labels, updates=3)
        self.assertNotEqual(updated.weights_sha256, diagonal.weights_sha256)
        state = self.state_after(updated, self.x[0])
        self.assertTrue(np.isfinite(updated.predict(state, [1, 0], episode_id="episode-1")).all())
        with self.assertRaisesRegex(ValueError, "HCSN has no admitted Cell adapter"):
            TemporalConfig(3, 2, 2, kind="hcsn")


if __name__ == "__main__":
    unittest.main()
