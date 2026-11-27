import unittest

from .observed_evaluation import UtilityContract
from .observed_policy import choose_fixed1, information_value


class ObservedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.contract = UtilityContract(
            cost_unit="fixture-resource", time_weight=0.1, cost_weight=0.2
        )

    def test_fixed1_forecast_charges_real_units_not_old_discrete_grid(self):
        def distribution(p, duration, cost):
            return dict(
                success_probability=p,
                duration_values=[duration],
                duration_probabilities=[1.0],
                cost_values=[cost],
                cost_probabilities=[1.0],
            )

        result = choose_fixed1(
            {
                "cheap": distribution(0.8, 0.017, 0.003),
                "expensive": distribution(0.9, 2.03, 0.7),
            },
            self.contract,
            preparation_seconds=0.011,
            preparation_cost=0.002,
        )
        self.assertEqual(result["chosen_action"], "cheap")
        self.assertAlmostEqual(
            result["expected_utilities"]["cheap"], 0.8 - 0.1 * 0.028 - 0.2 * 0.005
        )
        self.assertIsNone(result["observed_policy_gain"])

    def test_information_value_uses_posterior_max_and_charges_preparation(self):
        values = dict(
            current={"a": 0.5, "b": 0.5},
            scenarios=[{"a": 0.8, "b": 0.2}, {"a": 0.2, "b": 0.8}],
            probabilities=[0.5, 0.5],
            preparation_seconds=0.0,
            preparation_cost=1.0,
            contract=self.contract,
            evidence_ref="1" * 64,
            evidence_split="train",
        )
        result = information_value(**values)
        self.assertTrue(result["prepare"])
        self.assertAlmostEqual(result["net_value"], 0.1)
        values["preparation_cost"] = 2.0
        self.assertFalse(information_value(**values)["prepare"])
        values["evidence_split"] = "confirm"
        with self.assertRaises(ValueError):
            information_value(**values)

    def test_no_scenarios_stops_and_inconsistent_scenarios_are_rejected(self):
        values = dict(
            current={"a": 0.5},
            scenarios=None,
            probabilities=None,
            preparation_seconds=0.0,
            preparation_cost=0.0,
            contract=self.contract,
            evidence_ref=None,
            evidence_split="train",
        )
        self.assertFalse(information_value(**values)["prepare"])
        values.update(
            scenarios=[{"a": 0.6}], probabilities=[1.0], evidence_ref="1" * 64
        )
        with self.assertRaises(ValueError):
            information_value(**values)

    def test_impossible_payoffs_and_overflow_do_not_choose_or_prepare(self):
        with self.assertRaises(ValueError):
            information_value(
                {"a": 0.5, "b": 0.5},
                [{"a": 10.0, "b": -9.0}, {"a": -9.0, "b": 10.0}],
                [0.5, 0.5],
                preparation_seconds=0.0,
                preparation_cost=0.0,
                contract=self.contract,
                evidence_ref="1" * 64,
                evidence_split="train",
            )
        forecast = dict(
            success_probability=0.5,
            duration_values=[1e308],
            duration_probabilities=[1.0],
            cost_values=[0.0],
            cost_probabilities=[1.0],
        )
        with self.assertRaises(ValueError):
            choose_fixed1(
                {"a": forecast},
                UtilityContract("fixture", 1e308, 0.0),
                preparation_seconds=0.0,
                preparation_cost=0.0,
            )


if __name__ == "__main__":
    unittest.main()
