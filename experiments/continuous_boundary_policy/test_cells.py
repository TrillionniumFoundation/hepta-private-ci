"""Numerical-gradient and causal replay checks for the trainable supplement."""

import unittest

import numpy as np

from . import cells


class TrainableCellTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(102)
        x = rng.normal(0, 0.4, (4, 3, 18))
        resets = rng.uniform(0, 0.4, (4, 3))
        q = rng.normal(0, 2, (4, 3, 3))
        q[..., 2] = 0
        return x, resets, q

    def test_all_parameter_gradients_against_finite_differences(self):
        x, resets, q = self.fixture()
        mask = np.array([[1, 1, 1], [1, 1, 1], [1, 1, 1], [0, 1, 0]])
        for kind in cells.KINDS:
            params = cells.initialize(91, kind)
            loss, gradient, metrics = cells.loss_and_grad(
                x, resets, q, params, kind, mask
            )
            self.assertEqual(cells.parameter_count(params), 464)
            self.assertAlmostEqual(
                loss,
                metrics["cross_entropy"] + metrics["normalized_expected_regret"],
                places=13,
            )
            for name, values in params.items():
                numerical = np.zeros_like(values)
                for index in np.ndindex(values.shape):
                    original = values[index]
                    values[index] = original + 1e-6
                    plus = cells.loss_and_grad(x, resets, q, params, kind, mask)[0]
                    values[index] = original - 1e-6
                    minus = cells.loss_and_grad(x, resets, q, params, kind, mask)[0]
                    values[index] = original
                    numerical[index] = (plus - minus) / 2e-6
                np.testing.assert_allclose(
                    gradient[name], numerical, atol=6e-9, rtol=3e-4
                )
                self.assertTrue(np.all(gradient[name] != 0), (kind, name))

    def test_matched_pair_initializes_identically(self):
        x, resets, _ = self.fixture()
        dual, gru = [cells.initialize(13, kind) for kind in ("dual", "gru")]
        for name in dual:
            np.testing.assert_array_equal(dual[name], gru[name])
        for a, b in zip(
            cells.forward(x, resets, dual, "dual")[:2],
            cells.forward(x, resets, gru, "gru")[:2],
        ):
            np.testing.assert_array_equal(a, b)
        self.assertEqual(
            cells.serialize(dual, "dual")["fixed_sign_arrays"],
            cells.serialize(gru, "gru")["fixed_sign_arrays"],
        )

    def test_causal_steps_and_checkpoint_round_trip(self):
        x, resets, _ = self.fixture()
        for kind in cells.KINDS:
            params = cells.initialize(17, kind)
            restored, restored_kind = cells.deserialize(cells.serialize(params, kind))
            self.assertEqual(restored_kind, kind)
            scores, states, _ = cells.forward(x, resets, restored, kind)
            state = np.zeros((3, 6))
            for t in range(len(x)):
                score, state = cells.step(x[t], resets[t], state, restored, kind)
                np.testing.assert_array_equal(score, scores[t])
                np.testing.assert_array_equal(state, states[t])
            self.assertTrue(np.all(scores[..., 2] == 0))
            self.assertTrue(np.all(np.abs(scores) <= 8))
            self.assertTrue(np.all(np.abs(states) <= 1))
            all_reset = np.ones(3)
            score_a, state_a = cells.step(
                x[0], all_reset, np.ones((3, 6)), params, kind
            )
            score_b, state_b = cells.step(
                x[0], all_reset, -np.ones((3, 6)), params, kind
            )
            np.testing.assert_array_equal(score_a, score_b)
            np.testing.assert_array_equal(state_a, state_b)

    def test_full_training_moves_every_parameter_group_and_reduces_loss(self):
        x, resets, q = self.fixture()
        for kind in cells.KINDS:
            params, receipt = cells.fit(
                x,
                resets,
                q,
                cells.initialize(42, kind),
                kind,
                learning_rate=0.02,
                epochs=30,
            )
            self.assertLess(receipt["final_loss"], receipt["epoch_loss"][0])
            self.assertTrue(
                all(value > 0 for value in receipt["parameter_change_l2"].values())
            )
            self.assertEqual(
                sum(receipt["coordinates_with_nonzero_gradient"].values()), 464
            )
            cells.deserialize(cells.serialize(params, kind))

    def test_teacher_tie_rule_and_invalid_checkpoint(self):
        x, resets, _ = self.fixture()
        q = np.zeros((4, 3, 3))
        params = cells.initialize(6, "gru")
        params["head"][:] = 0
        params["head_bias"][:] = 0
        _, _, metrics = cells.loss_and_grad(x, resets, q, params, "gru")
        self.assertAlmostEqual(metrics["teacher_action_accuracy"], 1)
        self.assertEqual(metrics["normalized_expected_regret"], 0)
        snapshot = cells.serialize(params, "gru")
        snapshot["fixed_sign_arrays"]["head"][0][0] *= -1
        with self.assertRaises(ValueError):
            cells.deserialize(snapshot)


if __name__ == "__main__":
    unittest.main()
