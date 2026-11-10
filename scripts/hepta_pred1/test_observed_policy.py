import unittest

from .observed_evaluation import UtilityContract
from .observed_policy import choose_fixed1, information_value


class ObservedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.contract = UtilityContract(cost_unit="fixture-resource", time_weight=.1, cost_weight=.2)

    def test_fixed1_forecast_charges_real_units_not_old_discrete_grid(self):
        def distribution(p, duration, cost):
            return dict(success_probability=p, duration_values=[duration], duration_probabilities=[1.],
                        cost_values=[cost], cost_probabilities=[1.])
        result = choose_fixed1({"cheap": distribution(.8, .017, .003),
                                "expensive": distribution(.9, 2.03, .7)}, self.contract,
                               preparation_seconds=.011, preparation_cost=.002)
        self.assertEqual(result["chosen_action"], "cheap")
        self.assertAlmostEqual(result["expected_utilities"]["cheap"], .8 - .1 * .028 - .2 * .005)
        self.assertIsNone(result["observed_policy_gain"])

    def test_information_value_uses_posterior_max_and_charges_preparation(self):
        values = dict(current={"a": .5, "b": .5}, scenarios=[{"a": .8, "b": .2}, {"a": .2, "b": .8}],
                      probabilities=[.5, .5], preparation_seconds=0., preparation_cost=1.,
                      contract=self.contract, evidence_ref="1" * 64, evidence_split="train")
        result = information_value(**values)
        self.assertTrue(result["prepare"])
        self.assertAlmostEqual(result["net_value"], .1)
        values["preparation_cost"] = 2.
        self.assertFalse(information_value(**values)["prepare"])
        values["evidence_split"] = "confirm"
        with self.assertRaises(ValueError):
            information_value(**values)

    def test_no_scenarios_stops_and_inconsistent_scenarios_are_rejected(self):
        values = dict(current={"a": .5}, scenarios=None, probabilities=None,
                      preparation_seconds=0., preparation_cost=0., contract=self.contract,
                      evidence_ref=None, evidence_split="train")
        self.assertFalse(information_value(**values)["prepare"])
        values.update(scenarios=[{"a": .6}], probabilities=[1.], evidence_ref="1" * 64)
        with self.assertRaises(ValueError):
            information_value(**values)

    def test_impossible_payoffs_and_overflow_do_not_choose_or_prepare(self):
        with self.assertRaises(ValueError):
            information_value({"a": .5, "b": .5}, [{"a": 10., "b": -9.}, {"a": -9., "b": 10.}], [.5, .5],
                              preparation_seconds=0., preparation_cost=0., contract=self.contract,
                              evidence_ref="1" * 64, evidence_split="train")
        forecast = dict(success_probability=.5, duration_values=[1e308], duration_probabilities=[1.],
                        cost_values=[0.], cost_probabilities=[1.])
        with self.assertRaises(ValueError):
            choose_fixed1({"a": forecast}, UtilityContract("fixture", 1e308, 0.),
                          preparation_seconds=0., preparation_cost=0.)


if __name__ == "__main__":
    unittest.main()
