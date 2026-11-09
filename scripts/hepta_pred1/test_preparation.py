"""Behavioral checks for bounded, actor-first preparation/action choices."""

from dataclasses import replace
from types import SimpleNamespace
import unittest

import numpy as np

from .contracts import JOINT_SUPPORT
from .preparation import (
    choose_preparation,
    evaluate_development_preparations,
    forecast_preparations,
)
from .simulator import Dataset, EvaluatorOnly


def fixture():
    failure = np.flatnonzero(np.all(JOINT_SUPPORT == [0, 1, 1], axis=1))[0]
    success = np.flatnonzero(np.all(JOINT_SUPPORT == [1, 2, 4], axis=1))[0]
    classes = np.full((2, 3, 4), failure, dtype=int)
    classes[:, 2, 2] = success
    probabilities = np.eye(len(JOINT_SUPPORT))[classes]
    history = np.zeros((2, 4, 16))
    history[1, :, 0] = 1
    return Dataset(
        history,
        np.zeros((2, 7)),
        np.ones((2, 32), dtype=bool),
        ("prepare:91:dev:0", "prepare:91:dev:1"),
        np.ones((2, 4), dtype=bool),
        np.full(2, 13.5),
        np.full(2, 8.75),
        np.full(2, 1.5),
        {},
        EvaluatorOnly(probabilities, classes, classes[:, 0, 0]),
    )


class ForecastModel:
    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.calls, self.rows = 0, 0

    def predict_proba(self, history, query, reset=False):
        if history.flags.writeable or query.flags.writeable:
            raise AssertionError("planner passed mutable model inputs")
        self.calls += 1
        self.rows += len(history)
        hi, ai = query[0, 4:].argmax(), query[0, :4].argmax()
        return self.probabilities[history[:, 0, 0].astype(int), hi, ai].copy()


def forecast(data, model=None, charge=None, delay=None):
    return forecast_preparations(
        model or ForecastModel(data.evaluator.bayes_joint),
        data.x,
        data.legal_actions,
        data.deadline,
        data.remaining_budget,
        np.full(2, 0.25) if charge is None else charge,
        np.full(2, 0.5) if delay is None else delay,
    )


class PreparationTests(unittest.TestCase):
    def test_joint_choice_and_once_only_prefix_preparation_decision_cost(self):
        data = fixture()
        report = evaluate_development_preparations(
            ForecastModel(data.evaluator.bayes_joint),
            data,
            decision_work=np.full(2, 0.25),
            decision_time=np.full(2, 0.5),
        )
        adaptive = report["arms"]["adaptive"]
        self.assertEqual(adaptive["per_episode"]["selected_horizon"], [6, 6])
        self.assertEqual(adaptive["per_episode"]["selected_action"], [2, 2])
        self.assertEqual(adaptive["per_episode"]["future_cost"], [4.5, 4.5])
        self.assertEqual(adaptive["per_episode"]["future_elapsed_time"], [7.0, 7.0])
        self.assertEqual(adaptive["per_episode"]["decision_time"], [0.5, 0.5])
        self.assertEqual(adaptive["per_episode"]["elapsed_time"], [7.5, 7.5])
        self.assertEqual(adaptive["complete_environment_cost"], 6.25)
        self.assertAlmostEqual(adaptive["expected_net_utility"], 0.775)
        self.assertAlmostEqual(adaptive["realized_net_utility"], 0.775)
        self.assertAlmostEqual(adaptive["bayes_regret"], 0.0)
        for name in ("fixed_1", "fixed_3"):
            self.assertEqual(report["arms"][name]["stop_rate"], 1.0)
            self.assertEqual(report["arms"][name]["complete_environment_cost"], 1.75)
            self.assertEqual(
                report["arms"][name]["per_episode"]["elapsed_time"], [0.5, 0.5]
            )
            self.assertAlmostEqual(report["arms"][name]["expected_net_utility"], -0.055)
            self.assertAlmostEqual(report["arms"][name]["realized_net_utility"], -0.055)
        self.assertEqual(report["arms"]["fixed_6"], adaptive)
        self.assertEqual(report["meter"]["prediction_rows"], 24)
        self.assertFalse(report["meter"]["physical_cost_complete"])

    def test_budget_and_deadline_reserve_full_support_not_predicted_cost(self):
        data = fixture()
        self.assertEqual(choose_preparation(forecast(data)).action.tolist(), [2, 2])
        for field, bound in (("deadline", 13.5), ("remaining_budget", 8.75)):
            reduced = replace(data, **{field: np.full(2, np.nextafter(bound, 0.0))})
            choice = choose_preparation(forecast(reduced))
            self.assertEqual(choice.action.tolist(), [-1, -1])
            self.assertEqual(choice.status, ("nonpositive_value",) * 2)

    def test_no_legal_or_budgeted_option_stops_before_model_execution(self):
        data = fixture()
        for changed in (
            replace(data, legal_actions=np.zeros((2, 4), dtype=bool)),
            replace(data, deadline=np.full(2, 7.0)),
            replace(data, remaining_budget=np.full(2, 0.1)),
        ):
            model = ForecastModel(data.evaluator.bayes_joint)
            result = forecast(changed, model)
            self.assertEqual(model.calls, 0)
            self.assertEqual(result.decision_work_charged.tolist(), [0.0, 0.0])
            self.assertEqual(result.decision_time_charged.tolist(), [0.0, 0.0])
            self.assertEqual(
                choose_preparation(result).status, ("no_admissible_option",) * 2
            )

    def test_mixed_admission_queries_only_admitted_rows(self):
        data = replace(fixture(), remaining_budget=np.array([0.1, 8.75]))
        model = ForecastModel(data.evaluator.bayes_joint)
        result = forecast(data, model)
        self.assertEqual(model.rows, 12)
        self.assertEqual(choose_preparation(result).action.tolist(), [-1, 2])
        self.assertEqual(result.decision_work_charged.tolist(), [0.0, 0.25])
        self.assertEqual(result.decision_time_charged.tolist(), [0.0, 0.5])

    def test_decision_delay_is_reserved_and_not_subtracted_twice_at_choice(self):
        data = fixture()
        slow = forecast(data, delay=np.full(2, 14.0))
        self.assertEqual(slow.meter["prediction_calls"], 0)
        self.assertEqual(choose_preparation(slow).status, ("no_admissible_option",) * 2)
        # The delay is already paid once forecasting finishes. Executing a
        # positive-future-value option still beats stopping with the same delay.
        data = replace(data, deadline=np.full(2, 213.0))
        report = evaluate_development_preparations(
            ForecastModel(data.evaluator.bayes_joint),
            data,
            decision_work=np.full(2, 0.25),
            decision_time=np.full(2, 200.0),
        )
        adaptive = report["arms"]["adaptive"]
        self.assertEqual(adaptive["per_episode"]["selected_action"], [2, 2])
        self.assertAlmostEqual(adaptive["expected_net_utility"], -0.2225)
        self.assertGreater(
            adaptive["expected_net_utility"],
            report["arms"]["fixed_1"]["expected_net_utility"],
        )

    def test_illegal_preferred_action_never_selected(self):
        data = fixture()
        legal = data.legal_actions.copy()
        legal[:, 2] = False
        result = forecast(replace(data, legal_actions=legal))
        self.assertEqual(choose_preparation(result).action.tolist(), [-1, -1])

    def test_invalid_public_inputs_and_probability_mass_rejected(self):
        data = fixture()
        for changed in (
            replace(data, deadline=np.full(2, -1.0)),
            replace(data, remaining_budget=np.full(2, np.nan)),
            replace(data, legal_actions=np.ones((2, 4))),
        ):
            with self.assertRaises(ValueError):
                forecast(changed)
        for mass in (np.zeros((2, 32)), np.full((2, 32), np.nan), np.ones((2, 31))):
            model = SimpleNamespace(predict_proba=lambda *args, p=mass, **kwargs: p)
            with self.assertRaises(ValueError):
                forecast(data, model)
        with self.assertRaises(ValueError):
            forecast(data, charge=np.full(2, -0.1))
        for delay in (np.full(2, -0.1), np.full(2, np.nan)):
            with self.assertRaises(ValueError):
                forecast(data, delay=delay)

    def test_evaluator_unavailable_until_all_predictions_finish(self):
        data = fixture()
        model = ForecastModel(data.evaluator.bayes_joint)
        test = self

        class Guard:
            def __getattr__(self, name):
                if name == "evaluator":
                    test.assertEqual(model.calls, 12)
                return getattr(data, name)

        evaluate_development_preparations(
            model,
            Guard(),
            decision_work=np.full(2, 0.25),
            decision_time=np.full(2, 0.5),
        )

    def test_evaluator_changes_cannot_change_frozen_choices(self):
        data = fixture()
        labels = replace(data.evaluator, realized_class=np.zeros((2, 3, 4), dtype=int))
        reports = [
            evaluate_development_preparations(
                ForecastModel(data.evaluator.bayes_joint),
                candidate,
                decision_work=np.full(2, 0.25),
                decision_time=np.full(2, 0.5),
            )
            for candidate in (data, replace(data, evaluator=labels))
        ]
        for name in reports[0]["arms"]:
            left, right = (r["arms"][name]["per_episode"] for r in reports)
            for field in ("selected_horizon", "selected_action", "status"):
                self.assertEqual(left[field], right[field])
        self.assertNotEqual(
            reports[0]["arms"]["adaptive"]["realized_net_utility"],
            reports[1]["arms"]["adaptive"]["realized_net_utility"],
        )

    def test_fixed_baselines_share_charge_and_do_not_mutate_inputs(self):
        data = fixture()
        before = {
            key: getattr(data, key).copy()
            for key in ("x", "legal_actions", "deadline", "remaining_budget")
        }
        result = forecast(data)
        for horizon in (1, 3, 6):
            choose_preparation(result, fixed_horizon=horizon)
        self.assertEqual(choose_preparation(result).horizon_index.tolist(), [2, 2])
        for key, value in before.items():
            np.testing.assert_array_equal(getattr(data, key), value)
        for invalid in (True, 2, "6"):
            with self.assertRaises(ValueError):
                choose_preparation(result, fixed_horizon=invalid)

    def test_confirmation_and_malformed_groups_are_not_development(self):
        data = fixture()
        for groups in (("a", "b"), ("prepare:91:confirm:0", "prepare:91:confirm:1")):
            model = ForecastModel(data.evaluator.bayes_joint)
            with self.assertRaises(ValueError):
                evaluate_development_preparations(
                    model,
                    replace(data, groups=groups),
                    decision_work=np.full(2, 0.25),
                    decision_time=np.full(2, 0.5),
                )
            self.assertEqual(model.calls, 0)


if __name__ == "__main__":
    unittest.main()
