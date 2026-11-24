"""Numerical and lifecycle checks for the reconstructed CfC implementation."""

import copy
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from hepta_cells.cfc import CfCModel
from hepta_cells.temporal import TemporalConfig, TemporalKernel, TrainingAttemptError


def scalar_reference(model, observation, previous):
    """Independent scalar arithmetic for the pinned default ncps equation."""
    p = model.params
    z = list(observation) + list(previous)
    result = []
    for j in range(model.h):
        affine = {
            name: float(p["b" + name][j])
            + sum(
                float(value) * float(p["W" + name][i, j]) for i, value in enumerate(z)
            )
            for name in ("f1", "f2", "ta", "tb")
        }
        first, second = math.tanh(affine["f1"]), math.tanh(affine["f2"])
        gate = 1.0 / (1.0 + math.exp(-(affine["ta"] * observation[-1] + affine["tb"])))
        result.append(first * (1.0 - gate) + second * gate)
    return result


class CfCCellTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(17)
        self.x = rng.normal(0, 0.25, (3, 4, 3))
        self.x[:, :, -1] = [[0, 0.1, 0.3, 2], [0, 1, 0.2, 0.01], [0, 0, 2, 0.5]]
        self.actions = rng.normal(0, 0.3, (3, 1))
        self.allowed = np.array([[1, 0, 0], [0, 1, 1], [1, 1, 1]], dtype=bool)
        self.config = TemporalConfig(3, 1, 3, hidden_dim=2, seed=23, kind="cfc")

    def test_scalar_parity_including_batch_equals_hidden_width(self):
        rng = np.random.default_rng(3)
        model = CfCModel("cfc", 3, 1, 3, 3, 2)
        for batch in (1, 2, 3):
            observation = rng.normal(0, 0.2, (batch, 3))
            observation[:, -1] = np.arange(batch) * 0.7
            previous = rng.normal(0, 0.4, (batch, 3))
            original = previous.copy()
            actual = model.observe(observation, {"fast": previous})["fast"]
            expected = np.array(
                [scalar_reference(model, x, h) for x, h in zip(observation, previous)]
            )
            np.testing.assert_allclose(actual, expected, rtol=1e-13, atol=1e-14)
            np.testing.assert_array_equal(previous, original)
            self.assertEqual(actual.shape, (batch, 3))
            # Default CfC does update at dt=0; the owner handles duplicates.
            self.assertFalse(np.array_equal(actual[0], previous[0]))

    def test_all_parameters_match_multistep_finite_differences(self):
        model = CfCModel("cfc", 3, 1, 3, 2, 23)
        weights = np.array([1.0, 2.0, 3.0])
        loss, analytic = model.loss_and_grads(
            self.x, self.actions, self.allowed, sample_weights=weights
        )
        self.assertTrue(np.isfinite(loss))
        self.assertEqual(model.parameter_count, 65)
        epsilon = 1e-6
        for key, value in model.params.items():
            for index in np.ndindex(value.shape):
                with self.subTest(parameter=key, coordinate=index):
                    original = value[index]
                    value[index] = original + epsilon
                    plus = model.loss_and_grads(
                        self.x, self.actions, self.allowed, sample_weights=weights
                    )[0]
                    value[index] = original - epsilon
                    minus = model.loss_and_grads(
                        self.x, self.actions, self.allowed, sample_weights=weights
                    )[0]
                    value[index] = original
                    self.assertAlmostEqual(
                        analytic[key][index], (plus - minus) / (2 * epsilon), delta=2e-7
                    )
        full = model.forward(self.x, self.actions)
        reset = model.forward(self.x, self.actions, reset=True)
        self.assertGreater(float(np.max(np.abs(full - reset))), 1e-6)

    def test_training_isolated_and_unknown_targets_preserve_adam(self):
        kernel = TemporalKernel("cfc-cell", self.config)
        state = kernel.observe(
            kernel.initial_state("episode"),
            self.x[0, 0],
            episode_id="episode",
            cursor=0,
        )
        before = (kernel.weights_sha256, kernel.optimizer_sha256, copy.deepcopy(state))
        candidate, receipt = kernel.train_candidate(
            self.x, self.actions, self.allowed, updates=3
        )
        self.assertIsInstance(candidate._model, CfCModel)
        self.assertEqual(
            (kernel.weights_sha256, kernel.optimizer_sha256, state), before
        )
        self.assertNotEqual(candidate.weights_sha256, kernel.weights_sha256)
        self.assertEqual(receipt["validated_updates"], 3)
        with self.assertRaises(ValueError):
            candidate.predict(state, [0], episode_id="episode")
        unchanged, receipt = candidate.train_candidate(
            self.x, self.actions, np.ones_like(self.allowed), updates=2
        )
        self.assertEqual(
            (unchanged.weights_sha256, unchanged.optimizer_sha256),
            (candidate.weights_sha256, candidate.optimizer_sha256),
        )
        self.assertEqual(receipt["validated_updates"], 0)
        self.assertEqual(receipt["losses"], [0.0, 0.0])

    def test_owner_checkpoint_restores_hidden_and_next_training(self):
        kernel, _ = TemporalKernel("cfc-cell", self.config).train_candidate(
            self.x, self.actions, self.allowed, updates=2
        )
        state = kernel.initial_state("episode")
        for cursor in range(2):
            state = kernel.observe(
                state, self.x[0, cursor], episode_id="episode", cursor=cursor
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.npz"
            digest = kernel.checkpoint(path, state)
            restored, recovered = TemporalKernel.restore_checkpoint(
                path, expected_sha256=digest, cell_id="cfc-cell", config=self.config
            )
            self.assertIsInstance(restored._model, CfCModel)
            self.assertEqual(state, recovered)
            self.assertEqual(
                kernel.observe(state, self.x[0, 2], episode_id="episode", cursor=2),
                restored.observe(
                    recovered, self.x[0, 2], episode_id="episode", cursor=2
                ),
            )
            np.testing.assert_array_equal(
                kernel.predict(state, [1], episode_id="episode"),
                restored.predict(recovered, [1], episode_id="episode"),
            )
            first, first_receipt = kernel.train_candidate(
                self.x, self.actions, self.allowed, updates=3
            )
            second, second_receipt = restored.train_candidate(
                self.x, self.actions, self.allowed, updates=3
            )
            self.assertEqual(
                (first.weights_sha256, first.optimizer_sha256, first_receipt["losses"]),
                (
                    second.weights_sha256,
                    second.optimizer_sha256,
                    second_receipt["losses"],
                ),
            )

    def test_model_checkpoint_next_update_matches_in_fresh_process(self):
        model = CfCModel("cfc", 3, 1, 3, 2, 23)
        for _ in range(2):
            model.fit_step(self.x, self.actions, self.allowed)
        code = (
            "import sys,numpy as np; from hepta_cells.cfc import CfCModel; "
            "m=CfCModel.load(sys.argv[1]); d=np.load(sys.argv[2],allow_pickle=False); "
            "m.fit_step(d['x'],d['actions'],d['allowed']); m.save(sys.argv[3])"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model.save(root / "before.npz")
            np.savez(
                root / "batch.npz", x=self.x, actions=self.actions, allowed=self.allowed
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = (
                str(Path(__file__).resolve().parent)
                + os.pathsep
                + env.get("PYTHONPATH", "")
            )
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    code,
                    str(root / "before.npz"),
                    str(root / "batch.npz"),
                    str(root / "after.npz"),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            recovered = CfCModel.load(root / "after.npz")
            model.fit_step(self.x, self.actions, self.allowed)
            self.assertEqual(model.steps, recovered.steps)
            for name in ("params", "m", "v"):
                for key, value in getattr(model, name).items():
                    np.testing.assert_array_equal(value, getattr(recovered, name)[key])

    def test_invalid_elapsed_time_fails_with_retained_attempt_cost(self):
        kernel = TemporalKernel("cfc-cell", self.config)
        before = kernel.weights_sha256, kernel.optimizer_sha256
        for value in (-0.1, np.nan, np.inf):
            with self.assertRaises(ValueError):
                kernel.observe(
                    kernel.initial_state("episode"),
                    [0, 0, value],
                    episode_id="episode",
                    cursor=0,
                )
        invalid = self.x.copy()
        invalid[0, 0, -1] = -1
        with self.assertRaises(TrainingAttemptError) as failure:
            kernel.train_candidate(invalid, self.actions, self.allowed)
        receipt = failure.exception.receipt
        self.assertEqual(receipt["status"], "failed")
        self.assertGreaterEqual(receipt["wall_seconds"], 0)
        self.assertGreaterEqual(receipt["process_cpu_seconds"], 0)
        self.assertEqual((kernel.weights_sha256, kernel.optimizer_sha256), before)


if __name__ == "__main__":
    unittest.main()
