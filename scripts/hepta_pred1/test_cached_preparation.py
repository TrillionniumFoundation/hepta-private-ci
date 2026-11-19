"""Small new development fixtures; never read a campaign or checkpoint."""

from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from . import cached_preparation as C
from .models import Model
from .preparation import (
    PreparationTariff,
    choose_fixed_one,
    choose_preparation,
    forecast_fixed_one,
    forecast_preparations,
)
from .simulator import generate_dataset


def fixture():
    data = generate_dataset(3, 9910409, "dev", 4)
    return replace(data, remaining_budget=np.full(3, 16.0), deadline=np.full(3, 20.0))


class Spy(Model):
    def __init__(self):
        super().__init__("gru", 16, 7, 32, 3, 9910413)
        self.observed_rows, self.seen = 0, []

    def observe(self, observation, state):
        self.observed_rows += len(observation)
        return super().observe(observation, state)

    def predict_from_state(self, state, query):
        if query.flags.writeable or any(v.flags.writeable for v in state.values()):
            raise AssertionError("mutable candidate input")
        self.seen.append(
            (int(query[0, :4].argmax()), int(query[0, 4:].argmax()), len(query))
        )
        return super().predict_from_state(state, query)


def forecast(model, data, horizons, tariff, **kwargs):
    return C.forecast_cached_panel(
        model,
        data.x,
        data.legal_actions,
        data.deadline,
        data.remaining_budget,
        horizons=horizons,
        tariff=tariff,
        **kwargs,
    )


class CachedPreparationTests(unittest.TestCase):
    tariff = PreparationTariff(*([0.001] * 6))

    def test_actual_fixed1_parity_and_zero_price_adaptive_agreement(self):
        data = fixture()
        for kind in ("single_step", "gru", "diag_ssm", "dual_timescale"):
            for reset, mask in ((False, False), (True, False), (False, True)):
                model = Model(kind, 16, 7, 32, 3, 9910417)
                options = dict(
                    tariff=self.tariff, reset=reset, mask_candidate_action=mask
                )
                new = forecast(model, data, (1,), **options)
                old = forecast_fixed_one(
                    model,
                    data.x,
                    data.legal_actions,
                    data.deadline,
                    data.remaining_budget,
                    **options,
                )
                for field in (
                    "predicted_values",
                    "admissible",
                    "decision_work_charged",
                    "decision_time_charged",
                ):
                    np.testing.assert_array_equal(
                        getattr(new, field), getattr(old, field)
                    )
                choice, _ = C.choose_cached_panel(new)
                np.testing.assert_array_equal(
                    choice.action, choose_fixed_one(old).action
                )
            zero = PreparationTariff(*([0.0] * 6))
            new = forecast(model, data, (1, 3, 6), zero)
            old = forecast_preparations(
                model,
                data.x,
                data.legal_actions,
                data.deadline,
                data.remaining_budget,
                np.zeros(3),
                np.zeros(3),
            )
            np.testing.assert_allclose(
                new.predicted_values[new.admissible],
                old.predicted_values[new.admissible],
            )
            choice, _ = C.choose_cached_panel(new)
            legacy = choose_preparation(old)
            np.testing.assert_array_equal(choice.action, legacy.action)
            np.testing.assert_array_equal(choice.horizon_index, legacy.horizon_index)

    def test_only_queried_slots_are_computed_scanned_and_priced(self):
        data = replace(
            fixture(),
            legal_actions=np.tile([True, False, True, False], (3, 1)),
            remaining_budget=np.array([16.0, 0.0, 16.0]),
        )
        model = Spy()
        result = forecast(model, data, (1, 3), self.tariff)
        choice, meter = C.choose_cached_panel(result)
        self.assertEqual(model.seen, [(0, 0, 2), (2, 0, 2), (0, 1, 2), (2, 1, 2)])
        self.assertEqual(model.observed_rows, 8)
        self.assertEqual(
            (result.meter["prediction_rows"], meter["planning_candidate_rows"]), (8, 8)
        )
        self.assertEqual(result.meter["history_encodings"], 2)
        np.testing.assert_allclose(result.decision_work_charged, [0.012, 0, 0.012])
        self.assertEqual(choice.action[1], -1)
        self.assertTrue(np.isneginf(result.predicted_values[:, 2]).all())

    def test_whole_panel_reservation_exact_boundaries_and_no_subset_fallback(self):
        data = replace(
            fixture(),
            legal_actions=np.ones((3, 4), dtype=bool),
            remaining_budget=np.full(3, 36.5),
            deadline=np.full(3, 41.0),
        )
        tariff = PreparationTariff(*([1.0] * 6))
        result = forecast(Spy(), data, (1, 3, 6), tariff)
        self.assertEqual(result.meter["prediction_rows"], 36)
        np.testing.assert_array_equal(result.decision_work_charged, np.full(3, 28.0))
        for field, bound in (("remaining_budget", 36.5), ("deadline", 41.0)):
            below = replace(data, **{field: np.full(3, np.nextafter(bound, 0))})
            model = Spy()
            refused = forecast(model, below, (1, 3, 6), tariff)
            self.assertEqual((model.observed_rows, model.seen), (0, []))
            self.assertEqual(
                C.choose_cached_panel(refused)[1]["planning_candidate_rows"], 0
            )
        short = replace(data, deadline=np.full(3, 20.0))
        self.assertEqual(
            forecast(Spy(), short, (1,), tariff).meter["queried_episodes"], 3
        )
        self.assertEqual(
            forecast(Spy(), short, (1, 3), tariff).meter["queried_episodes"], 0
        )
        original = replace(
            data, remaining_budget=np.full(3, 8.0), deadline=np.full(3, 8.0)
        )
        self.assertEqual(
            forecast(Spy(), original, (1,), self.tariff).meter["prediction_calls"], 0
        )
        for invalid in ((True,), (1, 6), (1, 1), [1]):
            with self.assertRaises(ValueError):
                forecast(Spy(), data, invalid, tariff)

    def test_all_choices_and_bridge_precede_evaluator_and_labels_do_not_change_policy(
        self,
    ):
        data, model, test = fixture(), Spy(), self
        with patch.object(
            C, "choose_cached_panel", wraps=C.choose_cached_panel
        ) as select:
            with patch.object(
                C, "choose_fixed_one", wraps=C.choose_fixed_one
            ) as bridge:

                class Guard:
                    def __getattr__(self, name):
                        if name == "evaluator":
                            test.assertEqual(
                                (select.call_count, bridge.call_count), (3, 1)
                            )
                        return getattr(data, name)

                report = C.evaluate_cached_development(
                    model, Guard(), tariff=self.tariff
                )
        self.assertTrue(report["old_cheap_bridge"]["parity"])
        changed = replace(
            data,
            evaluator=replace(
                data.evaluator, realized_class=(data.evaluator.realized_class + 1) % 32
            ),
        )
        other = C.evaluate_cached_development(Spy(), changed, tariff=self.tariff)
        for name in C.PANELS:
            self.assertEqual(
                report["arms"][name]["per_episode"]["selected_action"],
                other["arms"][name]["per_episode"]["selected_action"],
            )
        refused = Spy()
        with self.assertRaisesRegex(ValueError, "development groups"):
            C.evaluate_cached_development(
                refused,
                replace(data, groups=tuple(f"x:confirm:{i}" for i in range(3))),
                tariff=self.tariff,
            )
        self.assertEqual((refused.observed_rows, refused.seen), (0, []))


if __name__ == "__main__":
    unittest.main()
