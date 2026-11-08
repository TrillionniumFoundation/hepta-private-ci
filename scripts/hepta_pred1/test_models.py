"""Gradient and learning checks for the hand-written recurrent optimization path."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    from .models import KINDS, Model, matched_hidden_dim
except ImportError:
    from models import KINDS, Model, matched_hidden_dim


class ModelTests(unittest.TestCase):
    def test_all_parameters_have_correct_bptt(self):
        rng = np.random.default_rng(31)
        x, action = rng.normal(size=(3, 4, 2)), rng.normal(size=(3, 2))
        allowed = np.array([[1, 0, 0], [0, 1, 1], [1, 1, 1]], dtype=bool)
        for kind in KINDS:
            model = Model(kind, 2, 2, 3, 2, 3)
            _, gradients = model.loss_and_grads(x, action, allowed)
            for name, values in model.params.items():
                for index in np.ndindex(values.shape):
                    original, step = values[index], 1e-5
                    values[index] = original + step
                    plus, _ = model.loss_and_grads(x, action, allowed)
                    values[index] = original - step
                    minus, _ = model.loss_and_grads(x, action, allowed)
                    values[index] = original
                    numeric = (plus - minus) / (2 * step)
                    self.assertAlmostEqual(
                        numeric,
                        gradients[name][index],
                        places=7,
                        msg=f"{kind}/{name}/{index}",
                    )

    def test_unknown_is_zero_information_and_invalid_sets_rejected(self):
        model = Model("gru", 2, 1, 3, 2, 5)
        x, a = np.ones((3, 5, 2)), np.ones((3, 1))
        loss, gradients = model.loss_and_grads(x, a, np.ones((3, 3), dtype=bool))
        self.assertEqual(loss, 0.0)
        self.assertTrue(all(np.count_nonzero(g) == 0 for g in gradients.values()))
        model.fit_step(x, a, np.eye(3, dtype=bool))
        before, steps = {k: v.copy() for k, v in model.params.items()}, model.steps
        model.fit_step(x, a, np.ones((3, 3), dtype=bool))
        self.assertEqual(steps, model.steps)
        for key in before:
            np.testing.assert_array_equal(before[key], model.params[key])
        with self.assertRaises(ValueError):
            model.loss_and_grads(x, a, np.zeros((3, 3), dtype=bool))

    def test_training_updates_time_kernel_and_reduces_loss(self):
        rng = np.random.default_rng(4)
        x, a = rng.normal(size=(40, 5, 2)), rng.normal(size=(40, 2))
        labels = (x[:, 0, 0] + x[:, -1, 1] + a[:, 0] > 0).astype(int)
        allowed = np.eye(2, dtype=bool)[labels]
        for kind in KINDS:
            model = Model(kind, 2, 2, 2, 6, 8)
            before = {k: v.copy() for k, v in model.params.items()}
            initial, _ = model.loss_and_grads(x, a, allowed)
            for _ in range(100):
                model.fit_step(x, a, allowed, lr=0.02)
            final, _ = model.loss_and_grads(x, a, allowed)
            self.assertLess(final, initial * 0.7, kind)
            self.assertTrue(
                all(not np.array_equal(before[k], v) for k, v in model.params.items()),
                kind,
            )

    def test_reset_action_and_streaming_contract(self):
        rng = np.random.default_rng(8)
        x, a = rng.normal(size=(5, 7, 3)), rng.normal(size=(5, 2))
        altered = x.copy()
        altered[:, :-1] *= -20
        for kind in KINDS:
            model = Model(kind, 3, 2, 5, 4, 9)
            np.testing.assert_array_equal(
                model.forward(x, a, reset=True), model.forward(altered, a, reset=True)
            )
            np.testing.assert_array_equal(
                model.forward(x, a, mask_action=True),
                model.forward(x, 10 * a, mask_action=True),
            )
            self.assertFalse(np.allclose(model.forward(x, a), model.forward(x, -a)))
            state = model.initial_state(len(x))
            for t in range(x.shape[1]):
                previous = {k: v.copy() for k, v in state.items()}
                old_state = state
                state = model.observe(x[:, t], state)
                for key in previous:
                    np.testing.assert_array_equal(old_state[key], previous[key])
            np.testing.assert_array_equal(
                model.forward(x, a), model.predict_from_state(state, a)
            )

    def test_checkpoint_resumes_optimizer_exactly(self):
        x, a, labels = np.ones((3, 4, 2)), np.ones((3, 1)), np.eye(3, dtype=bool)
        for kind in KINDS:
            model = Model(kind, 2, 1, 3, 3, 6)
            model.fit_step(x, a, labels)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "checkpoint.npz"
                digest = model.save(path)
                self.assertEqual(len(digest), 64)
                original = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    model.save(path)
                self.assertEqual(path.read_bytes(), original)
                loaded = Model.load(path)
            np.testing.assert_array_equal(model.forward(x, a), loaded.forward(x, a))
            self.assertEqual(
                model.fit_step(x, a, labels), loaded.fit_step(x, a, labels)
            )
            for key in model.params:
                np.testing.assert_array_equal(model.params[key], loaded.params[key])

    def test_matching_reports_close_counts(self):
        for kind in KINDS:
            h = matched_hidden_dim(kind, 16, 7, 32, 3000)
            count = Model(kind, 16, 7, 32, h, 1).parameter_count
            self.assertLess(abs(count - 3000), 200)


if __name__ == "__main__":
    unittest.main()
