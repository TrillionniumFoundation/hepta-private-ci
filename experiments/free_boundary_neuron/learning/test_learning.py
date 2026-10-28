"""Development-only correctness tests; no screening or confirmation outcomes."""

import itertools
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.special import logit

from .network import boundaries, forward, initialize, loss_and_gradient
from .task import ABSTAIN_REWARD, BellmanReference, evaluate, make_episodes
from . import runner


class LearningTests(unittest.TestCase):
    def test_event_keyed_streams_and_prefix_causality(self):
        small = make_episodes(900001, "smoke", 4)
        big = make_episodes(900001, "smoke", 12)
        np.testing.assert_array_equal(small.observations, big.observations[:4])
        params = initialize(900001, "fixed")
        before = forward(params, small, "standard")[0]
        changed = small.take(np.arange(4))
        changed.features[:, 7:, :2] *= -1
        after = forward(params, changed, "standard")[0]
        np.testing.assert_array_equal(before[:, :7], after[:, :7])

    def test_complete_neutral_cost_and_duration(self):
        episodes = make_episodes(900001, "smoke", 8)
        zero = np.zeros_like(episodes.observations)
        result = evaluate(zero, zero + 100, zero - 1, episodes)
        self.assertEqual(result["abstentions"], 8)
        self.assertEqual(result["observations"], int(episodes.deadline.sum()))
        self.assertEqual(result["coverage"], 0)
        self.assertIsNone(result["conditional_accuracy"])
        self.assertAlmostEqual(
            result["mean_utility"],
            float(np.mean(ABSTAIN_REWARD - episodes.cost * episodes.deadline)),
        )
        self.assertAlmostEqual(
            result["serial_duration"], float(np.sum(episodes.deadline + 0.4))
        )

    def test_hard_inference_matches_training_without_surrogate_work(self):
        episodes = make_episodes(900001, "smoke", 16)
        for method, gradient in itertools.product(
            ("fixed", "direct", "free"), ("standard", "first_passage")
        ):
            params = initialize(900001, method)
            training_voltage, training_spikes, _ = forward(params, episodes, gradient)
            inference_voltage, inference_spikes, cache = forward(
                params, episodes, gradient, cache_gradients=False
            )
            np.testing.assert_array_equal(training_voltage, inference_voltage)
            np.testing.assert_array_equal(training_spikes, inference_spikes)
            self.assertEqual(cache, {})

    def test_bellman_against_exhaustive_small_tree(self):
        reliability, cost, horizon = 0.65, 0.025, 4

        def tree(p, remaining):
            stop = max(abs(2 * p - 1), ABSTAIN_REWARD)
            if not remaining:
                return stop
            chance = reliability * p + (1 - reliability) * (1 - p)
            pp = reliability * p / chance
            pm = (1 - reliability) * p / (1 - chance)
            wait = (
                -cost
                + chance * tree(pp, remaining - 1)
                + (1 - chance) * tree(pm, remaining - 1)
            )
            return max(stop, wait)

        oracle = BellmanReference(2001)
        profile = oracle.profile(reliability, cost, horizon)
        for p in (0.15, 0.3, 0.5, 0.7, 0.85):
            self.assertAlmostEqual(
                np.interp(p, oracle.grid, profile["value_after_first"]),
                tree(p, horizon - 1),
                delta=0.002,
            )

    def test_hard_training_objective_equals_stopped_rollout(self):
        episodes = make_episodes(900001, "smoke", 16)
        oracle = BellmanReference()
        for method, gradient in itertools.product(
            ("fixed", "direct", "free"), ("standard", "first_passage")
        ):
            params = initialize(900001, method)
            free = oracle.boundaries(episodes) if method == "free" else None
            voltage, _, _ = forward(params, episodes, gradient)
            (choice, neutral), _ = boundaries(params, episodes, method, free=free)
            actual = evaluate(voltage, choice, neutral, episodes)["mean_utility"]
            _, _, diagnostics = loss_and_gradient(
                params, episodes, method, gradient, free=free
            )
            self.assertAlmostEqual(actual, diagnostics["utility"], places=12)

    def test_manual_reverse_mode_on_genuine_smooth_path(self):
        episodes = make_episodes(900002, "smoke", 3)
        oracle = BellmanReference()
        for method, gradient in itertools.product(
            ("fixed", "direct", "free"), ("standard", "first_passage")
        ):
            params = initialize(900002, method)
            free = oracle.boundaries(episodes) if method == "free" else None
            _, analytic, _ = loss_and_gradient(
                params, episodes, method, gradient, free=free, soft=True
            )
            rng = np.random.default_rng(915)
            for _ in range(3):
                direction = {
                    key: rng.normal(size=value.shape) for key, value in params.items()
                }
                norm = np.sqrt(sum(np.sum(value**2) for value in direction.values()))
                direction = {key: value / norm for key, value in direction.items()}
                epsilon = 1e-6
                plus = {
                    key: value + epsilon * direction[key]
                    for key, value in params.items()
                }
                minus = {
                    key: value - epsilon * direction[key]
                    for key, value in params.items()
                }
                finite = (
                    loss_and_gradient(
                        plus, episodes, method, gradient, free=free, soft=True
                    )[0]
                    - loss_and_gradient(
                        minus, episodes, method, gradient, free=free, soft=True
                    )[0]
                ) / (2 * epsilon)
                exact = sum(np.sum(analytic[key] * direction[key]) for key in params)
                np.testing.assert_allclose(
                    finite,
                    exact,
                    rtol=2e-4,
                    atol=2e-6,
                    err_msg=f"{method}/{gradient}: full stopped-path and recurrent derivative",
                )

    def test_terminal_belief_is_not_fpt_probability(self):
        episodes = make_episodes(900002, "smoke", 8)
        cumulative = np.cumsum(
            episodes.observations * logit(episodes.reliability[:, None]), axis=1
        )
        np.testing.assert_allclose(logit(episodes.posterior), cumulative, atol=1e-10)
        # The task posterior concerns external binary truth, not a terminal
        # voltage tail or a first-passage probability. Its known values check
        # the Bayesian state supplied to the independent reference policy.

    def test_checkpoint_audit_rejects_validation_and_work_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "development.json"
            result = runner.execute_attempt("development", destination)
            # This explicitly development-only fixture substitutes provenance
            # verification; registered scientific execution never does so.
            with patch.object(
                runner, "verify", return_value={"development_fixture": True}
            ):
                audit = runner.audit_results(destination, "development-fixture")
                self.assertEqual(audit["checkpoint_dataset_scores_verified"], 12)
                altered = copy.deepcopy(result)
                row = altered["records"][0]
                arm = row["arms"]["fixed:standard"]
                old = arm["selected_fixed_thresholds"][0]
                arm["selected_fixed_thresholds"][0] = 3.4 if old != 3.4 else 0.4
                parameters = {
                    key: np.asarray(value) for key, value in arm["checkpoint"].items()
                }
                for split in ("id_test", "ood_test"):
                    data = make_episodes(
                        row["seed"], split, 32, ood=split == "ood_test"
                    )
                    arm[split] = runner.score_model(
                        parameters,
                        arm["selected_fixed_thresholds"],
                        "fixed",
                        "standard",
                        data,
                        BellmanReference(),
                    )
                changed = Path(temporary) / "threshold_tampered.json"
                runner.write_receipt(changed, altered)
                with self.assertRaisesRegex(AssertionError, "validation selection"):
                    runner.audit_results(changed, "development-fixture")
                altered = copy.deepcopy(result)
                altered["records"][0]["arms"]["direct:first_passage"]["training"][
                    "parameter_count"
                ] += 1
                changed = Path(temporary) / "work_tampered.json"
                runner.write_receipt(changed, altered)
                with self.assertRaisesRegex(AssertionError, "budget/work metadata"):
                    runner.audit_results(changed, "development-fixture")

    def test_failed_attempt_preserves_completed_and_trained_checkpoints(self):
        real_score = runner.score_model
        calls = 0

        def fail_on_second_arm(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError("injected scorer failure")
            return real_score(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "failed.json"
            with patch.object(runner, "score_model", side_effect=fail_on_second_arm):
                with self.assertRaisesRegex(RuntimeError, "injected scorer failure"):
                    runner.execute_attempt("development", destination)
            directory = destination.with_name("failed_checkpoints")
            self.assertTrue(
                (directory / "seed_900001_fixed_standard_scores.json").is_file()
            )
            self.assertTrue(
                (
                    directory / "seed_900001_fixed_first_passage_checkpoint.json"
                ).is_file()
            )
            invalid = json.loads((directory / "INVALID_ATTEMPT.json").read_text())
            self.assertEqual(len(invalid["completed_arms"]), 1)
            self.assertEqual(invalid["last_completed_optimizer_step"], 2)
            self.assertFalse(destination.exists())

    def test_late_result_write_failure_keeps_complete_seed(self):
        real_write = runner.write_receipt
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "oversize.json"

            def fail_final(path, payload):
                if Path(path) == destination:
                    raise ValueError("injected final artifact-size failure")
                return real_write(path, payload)

            with patch.object(runner, "write_receipt", side_effect=fail_final):
                with self.assertRaisesRegex(ValueError, "artifact-size"):
                    runner.execute_attempt("development", destination)
            directory = destination.with_name("oversize_checkpoints")
            self.assertTrue((directory / "seed_900001_complete.json").is_file())
            invalid = json.loads((directory / "INVALID_ATTEMPT.json").read_text())
            self.assertEqual(len(invalid["completed_arms"]), 6)


if __name__ == "__main__":
    unittest.main()
