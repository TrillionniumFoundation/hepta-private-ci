"""Behavior and independent finite-difference checks for persistent filters."""

import copy
import unittest

import numpy as np

from .models import AnalyticFilter, LearnedFilter, features
from .campaign import dataset, rollout, world


PLAN = {"ticks": 6, "rate": .35, "sensor_accuracy": {"A": .78, "V": .9},
        "read_cost": {"A": .035, "V": .06}, "interval_seconds": [.04, .7]}


class PersistentTests(unittest.TestCase):
    def test_gradients_independent_finite_difference(self):
        rng = np.random.default_rng(87)
        x = rng.normal(size=(3, 4, 5)) * .2
        x[:, :, 0] = np.abs(x[:, :, 0])
        x[:, :, 1:3] = 0
        x[:, 1::2, 1] = 1
        y = rng.integers(2, size=(3, 4))
        for family in ("gru", "ssm"):
            model = LearnedFilter(family, 19, width=4)
            _, grad, _ = model.loss_grad(x, y)
            for key, parameter in model.p.items():
                direction = rng.normal(size=parameter.shape)
                original = parameter.copy()
                model.p[key] = original + 1e-5 * direction
                plus = model.loss_grad(x, y)[0]
                model.p[key] = original - 1e-5 * direction
                minus = model.loss_grad(x, y)[0]
                model.p[key] = original
                self.assertAlmostEqual((plus - minus) / 2e-5,
                                       float(np.sum(grad[key] * direction)), delta=2e-7,
                                       msg=family + ":" + key)

    def test_prefix_causality_and_episode_reset(self):
        w = world(133, 6, PLAN)
        future_changed = copy.deepcopy(w)
        for name in ("dt", "A", "V", "latent"):
            future_changed[name][3:] = list(reversed(future_changed[name][3:]))
        # Latent test labels can affect recorded correctness, never actions/state.
        labels_changed = copy.deepcopy(w)
        labels_changed["latent"] = [1 - x for x in w["latent"]]
        for family in ("gru", "ssm", "analytic", "direct_history"):
            model = LearnedFilter(family, 23, 4) if family in ("gru", "ssm") else None
            first = rollout(w, family, "value", PLAN, model)
            changed = rollout(future_changed, family, "value", PLAN, model)
            relabeled = rollout(labels_changed, family, "value", PLAN, model)
            again = rollout(w, family, "value", PLAN, model)
            self.assertEqual(first["trace"][:3], changed["trace"][:3])
            self.assertEqual(first["trace"], again["trace"])
            for a, b in zip(first["trace"], relabeled["trace"]):
                self.assertEqual((a["action"], a["probability"], a["state"]),
                                 (b["action"], b["probability"], b["state"]))

    def test_state_persists_and_no_event_is_identity(self):
        for family in ("gru", "ssm"):
            model = LearnedFilter(family, 8, 4)
            h, _, _ = model.step(features(.2, "A", 1)[None], model.zero())
            advanced, _, _ = model.step(features(.3)[None], h)
            reset_advanced, _, _ = model.step(features(.3)[None], model.zero())
            self.assertGreater(float(np.max(np.abs(advanced - reset_advanced))), 1e-6)
            unchanged, _, _ = model.step(features(0)[None], advanced)
            np.testing.assert_array_equal(unchanged, advanced)

    def test_analytic_and_raw_history_equivalence(self):
        for seed in range(20):
            w = world(seed, 6, PLAN)
            for control in ("light", "value"):
                analytic = rollout(w, "analytic", control, PLAN)
                raw = rollout(w, "direct_history", control, PLAN)
                self.assertEqual(analytic["trace"], raw["trace"])

    def test_training_inputs_are_accepted_events(self):
        x, y, masks = dataset(111, 8, PLAN)
        self.assertEqual(x.shape, (8, 12, 5))
        np.testing.assert_array_equal(x[:, ::2, 1:], 0)
        np.testing.assert_array_equal(x[:, 1::2, 0], 0)
        np.testing.assert_array_equal(y[:, ::2], y[:, 1::2])
        for i in range(len(x)):
            for t in range(x.shape[1]):
                if masks[i, t] == 0:
                    np.testing.assert_array_equal(x[i, t, 1:], 0)


if __name__ == "__main__":
    unittest.main()
