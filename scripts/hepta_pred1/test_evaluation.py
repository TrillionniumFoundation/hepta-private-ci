"""Verify oracle regret, proper scores, legal selection, and prediction isolation."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

import numpy as np

from .contracts import JOINT_SUPPORT
from .evaluation import evaluate
from .simulator import Dataset, EvaluatorOnly, generate_dataset


class OraclePredictor:
    def __init__(self, predictions):
        self.predictions, self.calls = predictions, 0

    def predict_proba(self, x, query, reset=False):
        self.calls += 1
        ai, hi = int(query[0, :4].argmax()), int(query[0, 4:].argmax())
        return self.predictions[:, hi, ai].copy()


def point_fixture(outcome=1, elapsed=4, cost=4):
    index = int(
        np.flatnonzero(np.all(JOINT_SUPPORT == [outcome, elapsed, cost], axis=1))[0]
    )
    classes = np.full((2, 3, 4), index, dtype=int)
    probabilities = np.eye(len(JOINT_SUPPORT))[classes]
    dataset = Dataset(
        np.zeros((2, 4, 16)),
        np.zeros((2, 7)),
        np.ones((2, len(JOINT_SUPPORT)), dtype=bool),
        ("a", "b"),
        np.ones((2, 4), dtype=bool),
        np.full(2, 4.0),
        np.full(2, 4.0),
        np.full(2, 1.5),
        {},
        EvaluatorOnly(probabilities, classes, classes[:, 0, 0]),
    )
    return dataset


class EvaluationTests(unittest.TestCase):
    def test_same_information_oracle_has_zero_regret(self):
        data = generate_dataset(13, 52, "pilot")
        model = OraclePredictor(data.evaluator.bayes_joint)
        metrics, per_episode = evaluate(model, data)
        np.testing.assert_allclose(per_episode["bayes_regret"], 0, atol=1e-14)
        self.assertEqual(
            metrics["forecast_scores"]["joint_total_variation_to_bayes"], 0.0
        )
        self.assertEqual(metrics["prediction_calls"], model.calls)
        self.assertEqual(metrics["prediction_rows"], 13 * 12)
        self.assertTrue(
            data.legal_actions[np.arange(13), per_episode["selected_action"]].all()
        )

    def test_exact_scores_deadline_budget_and_full_cost_boundary(self):
        data = replace(
            point_fixture(elapsed=8),
            deadline=np.full(2, 13.0),
            remaining_budget=np.full(2, 4.5),
        )
        metrics, per_episode = evaluate(
            OraclePredictor(data.evaluator.bayes_joint), data
        )
        for value in metrics["forecast_scores"].values():
            self.assertEqual(value, 0.0)
        self.assertEqual(metrics["deadline_budget_success_rate"], 1.0)
        self.assertAlmostEqual(metrics["expected_utility"], 0.8)
        self.assertAlmostEqual(metrics["net_utility"], 0.755)
        self.assertEqual(metrics["mean_tool_cost"], 4.0)
        self.assertEqual(metrics["mean_future_cost"], 4.5)
        self.assertEqual(metrics["complete_environment_cost"], 6.0)
        self.assertEqual(metrics["mean_time"], 13.0)
        self.assertEqual(metrics["time_p95"], 13.0)
        np.testing.assert_array_equal(per_episode["elapsed_time"], [13, 13])

    def test_preparation_deadline_and_budget_boundaries(self):
        # Five preparation ticks plus a two-tick tool finish at tick 7. The
        # remaining 1.5 budget includes 0.5 preparation + 1 tool, not sunk prefix.
        data = replace(
            point_fixture(elapsed=2, cost=1),
            deadline=np.full(2, 7.0),
            remaining_budget=np.full(2, 1.5),
        )
        metrics, _ = evaluate(OraclePredictor(data.evaluator.bayes_joint), data)
        self.assertEqual(metrics["deadline_budget_success_rate"], 1.0)
        self.assertEqual(metrics["complete_environment_cost"], 3.0)
        self.assertAlmostEqual(metrics["expected_utility"], 0.92)
        self.assertAlmostEqual(metrics["net_utility"], 0.875)
        for field, limit in (("deadline", 7.0), ("remaining_budget", 1.5)):
            less = replace(data, **{field: np.full(2, np.nextafter(limit, 0.0))})
            result, _ = evaluate(OraclePredictor(data.evaluator.bayes_joint), less)
            self.assertEqual(result["deadline_budget_success_rate"], 0.0)
            self.assertAlmostEqual(result["expected_utility"], -0.08)
            self.assertEqual(
                result["forecast_scores_by_horizon"]["3"][
                    "realized_deadline_budget_success_rate"
                ],
                1.0,
            )

    def test_translated_crps_and_horizon_specific_feasibility(self):
        data = replace(
            point_fixture(elapsed=4, cost=2),
            deadline=np.full(2, 8.0),
            remaining_budget=np.full(2, 8.0),
        )
        predicted = 0.5 * data.evaluator.bayes_joint
        short = int(np.flatnonzero(np.all(JOINT_SUPPORT == [1, 1, 1], axis=1))[0])
        predicted[..., short] += 0.5
        metrics, _ = evaluate(OraclePredictor(predicted), data)
        scores = metrics["forecast_scores_by_horizon"]
        for horizon in ("1", "3", "6"):
            self.assertEqual(scores[horizon]["time_crps"], 0.75)
            self.assertEqual(scores[horizon]["cost_crps"], 0.25)
        self.assertEqual(scores["1"]["deadline_budget_brier"], 0.0)
        self.assertEqual(scores["3"]["deadline_budget_brier"], 0.0)
        # At five preparation ticks the 4-tick realized tool misses deadline 8,
        # while the forecast's 1-tick alternative still has probability 0.5.
        self.assertEqual(scores["6"]["deadline_budget_brier"], 0.25)
        self.assertEqual(metrics["protocol"], "direct_preparation_option_forecast")
        self.assertFalse(metrics["horizon_selection_evaluated"])

    def test_illegal_high_scoring_action_never_selected(self):
        data = replace(
            point_fixture(elapsed=2, cost=1),
            deadline=np.full(2, 8.0),
            remaining_budget=np.full(2, 8.0),
        )
        legal = data.legal_actions.copy()
        legal[:, 0] = False
        data = replace(data, legal_actions=legal)
        p = data.evaluator.bayes_joint.copy()
        p[:, :, 1:] = np.eye(32)[0]
        _, per_episode = evaluate(OraclePredictor(p), data)
        np.testing.assert_array_equal(per_episode["selected_action"], [1, 1])
        with self.assertRaises(ValueError):
            evaluate(
                OraclePredictor(p),
                replace(data, legal_actions=np.zeros((2, 4), dtype=bool)),
            )

    def test_invalid_probability_and_evaluator_labels_rejected(self):
        data = point_fixture()
        for bad in (
            np.full((2, 32), np.nan),
            np.full((2, 32), -1.0),
            np.full((2, 32), 1.0),
            np.zeros((2, 31)),
        ):
            model = SimpleNamespace(
                predict_proba=lambda x, query, reset=False, p=bad: p
            )
            with self.assertRaises(ValueError):
                evaluate(model, data)
        labels = replace(data.evaluator, realized_class=np.full((2, 3, 4), 32))
        with self.assertRaises(ValueError):
            evaluate(
                OraclePredictor(data.evaluator.bayes_joint),
                replace(data, evaluator=labels),
            )

    def test_zero_event_mass_is_infinite_nll_not_clipped(self):
        data = point_fixture()
        p = np.zeros_like(data.evaluator.bayes_joint)
        p[..., 0] = 1.0
        metrics, _ = evaluate(OraclePredictor(p), data)
        self.assertTrue(np.isinf(metrics["forecast_scores"]["joint_nll"]))
        self.assertEqual(metrics["zero_mass_observed_event_count"], 24)

    def test_only_public_inputs_before_all_predictions_with_horizon_preserved(self):
        data, seen = point_fixture(), []
        history = data.x.copy()
        history[:, :, :3] = 1.0
        data = replace(data, x=history)

        class Spy:
            def predict_proba(self, x, query, reset=False):
                np.testing.assert_array_equal(x[:, :, :3], 0.0)
                np.testing.assert_array_equal(x[:, :, 3:], data.x[:, :, 3:])
                np.testing.assert_array_equal(query[:, :4], 0.0)
                np.testing.assert_array_equal(query[:, 4:].sum(axis=1), 1.0)
                self_test.assertTrue(reset)
                seen.append(query.copy())
                return np.full((len(x), 32), 1 / 32)

        class Guard:
            def __getattr__(self, name):
                if name == "evaluator":
                    self_test.assertEqual(len(seen), 12)
                return getattr(data, name)

        self_test = self
        metrics, _ = evaluate(Spy(), Guard(), reset=True, mask_candidate_action=True)
        self.assertEqual(len(seen), 12)
        self.assertFalse(metrics["autoregressive_rollout_evaluated"])
        self.assertTrue(
            all(
                metrics[key] >= 0
                for key in (
                    "inference_wall_seconds",
                    "inference_process_cpu_seconds",
                    "planning_wall_seconds",
                    "planning_process_cpu_seconds",
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
