"""Behavior, causal boundaries, branch isolation and numerical gradient checks."""

import argparse
import copy
from pathlib import Path
import unittest

import numpy as np

from .campaign import read_plan
from .environment import View, choose_action, load_physics, packet, reveal, rollout
from .models import Model


OUTPUT = None


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.module = read_plan(OUTPUT)
        self.config = self.module.Config()

    def test_multiclass_gradients(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(3, 4, 16)) * .15
        x[:, :, 0] = .15; x[:, :, 1] = 0; x[:, :, 2] = 1; x[:, :, 15] = .3
        y = rng.integers(5, size=(3, 4))
        for family in ("gru", "ssm", "mlp"):
            model = Model(family, 71, 4)
            _, grad = model.loss_grad(x, y)
            for key, value in model.p.items():
                direction = rng.normal(size=value.shape)
                old = value.copy()
                model.p[key] = old + 1e-5 * direction; plus = model.loss_grad(x, y)[0]
                model.p[key] = old - 1e-5 * direction; minus = model.loss_grad(x, y)[0]
                model.p[key] = old
                self.assertAlmostEqual((plus - minus) / 2e-5, float((grad[key] * direction).sum()), delta=3e-7,
                                       msg=family + ":" + key)

    def test_branch_isolation_and_persistence(self):
        episode = self.module.make_episode(4337, self.config)
        physics = self.module.Physics(**episode["calibration"]["estimated"])
        for family in ("gru", "ssm"):
            model = Model(family, 13, 8)
            view = View(self.module, physics, self.config, episode["initial_x"], family, model)
            view.advance(0); view.advance(1, reveal(episode, 1, self.config)); view.advance(2)
            original = (view.h.copy(), view.probability.copy(), copy.deepcopy(view.observation), copy.deepcopy(view.history))
            view.forecast(20)
            branch = view.hypothetical_read(10, reveal(episode, 10, self.config)); branch.forecast(20)
            choose_action(view, "task_value", 2, 919)
            np.testing.assert_array_equal(view.h, original[0]); np.testing.assert_array_equal(view.probability, original[1])
            self.assertEqual(view.observation, original[2]); self.assertEqual(view.history, original[3]); self.assertEqual(view.tick, 2)
            x = packet(.3, .15, view.observation, physics)
            retained = model.step(x[None], view.h)[0]
            reset = model.step(x[None], model.zero())[0]
            self.assertGreater(float(np.max(np.abs(retained - reset))), 1e-7)

    def test_prefix_causality_and_scoring_labels(self):
        episode = self.module.make_episode(4221, self.config)
        changed = copy.deepcopy(episode)
        for key in ("x", "refractory_remaining", "content"):
            changed["path"][key][11:] = list(reversed(changed["path"][key][11:]))
        # Two actual paths agree through tick10; future payload cannot affect prefix.
        for family in ("analytic", "exact_history", "gru", "ssm", "mlp"):
            model = None if family in ("analytic", "exact_history") else Model(family, 19, 8)
            a = rollout(episode, self.config, self.module, family, "task_value", model)
            b = rollout(changed, self.config, self.module, family, "task_value", model)
            self.assertEqual(a["trace"][:11], b["trace"][:11])

    def test_exact_history_and_original_policy(self):
        for seed in (17, 31, 73):
            episode = self.module.make_episode(seed, self.config)
            for controller in ("lightweight", "task_value"):
                a = rollout(episode, self.config, self.module, "analytic", controller)
                b = rollout(episode, self.config, self.module, "exact_history", controller)
                self.assertEqual(a, {**b, "family": "analytic"})
            physics = self.module.Physics(**episode["calibration"]["estimated"])
            view = View(self.module, physics, self.config, episode["initial_x"], "analytic")
            for tick in range(5):
                view.advance(tick, reveal(episode, tick, self.config) if tick == 2 else None)
            module = self.module
            class OriginalCore:
                calls = 0
                def counts(self, x, horizon, p, remaining=0):
                    return module.renewal_counts(x, horizon, p, remaining)[0]
            obs = module.Observation(**view.observation)
            old_action, old_detail = module.choose_action(OriginalCore(), "task_value", obs, 4, 2,
                physics, module.transition_matrix(5), self.config, 9981)
            new_action, new_detail = choose_action(view, "task_value", 2, 9981)
            self.assertEqual(old_action, new_action)
            for old, new in zip(old_detail["candidate_values"], new_detail["candidate_values"]):
                self.assertAlmostEqual(old["net_value"], new["net_value"], delta=1e-12)

    def test_common_perfect_read_head(self):
        episode = self.module.make_episode(441, self.config)
        physics = self.module.Physics(**episode["calibration"]["estimated"])
        for family in ("gru", "ssm", "mlp"):
            model = Model(family, 211, 8)
            view = View(self.module, physics, self.config, episode["initial_x"], family, model)
            np.testing.assert_array_equal(view.advance(0), np.full(5, .2))
            observed = reveal(episode, 1, self.config)
            np.testing.assert_array_equal(view.advance(1, observed), observed["content_probs"])

    def test_forecast_optimization_equals_literal_tick_replay(self):
        episode = self.module.make_episode(923, self.config)
        physics = self.module.Physics(**episode["calibration"]["estimated"])
        for family in ("analytic", "exact_history", "gru", "ssm", "mlp"):
            model = None if family in ("analytic", "exact_history") else Model(family, 211, 8)
            view = View(self.module, physics, self.config, episode["initial_x"], family, model)
            view.advance(0); view.advance(1, reveal(episode, 1, self.config)); view.advance(2)
            fast = view.forecasts([5, 10, 15, 20])
            for deadline in fast:
                literal = view.clone()
                while literal.tick < deadline:
                    literal.advance(literal.tick + 1)
                np.testing.assert_allclose(fast[deadline], literal.probability, atol=0, rtol=0)
            fake = reveal(episode, 9, self.config)
            fast_branch = view.hypothetical_read(9, fake)
            literal = view.clone()
            while literal.tick < 8:
                literal.advance(literal.tick + 1)
            literal.advance(9, fake)
            np.testing.assert_array_equal(fast_branch.probability, literal.probability)
            if family in ("gru", "ssm", "mlp"):
                np.testing.assert_array_equal(fast_branch.h, literal.h)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); OUTPUT = args.output
    unittest.main(argv=["renewal-tests", "-v"])
