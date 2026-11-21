import json
import tempfile
import unittest
from evaluation import OwnerContext, RECOMMEND, STOP, evaluate
from fixtures import FIXED_TEST_TIME, rebind_protocol, specialization_fixture_documents, write_fixture


class SpecializationTests(unittest.TestCase):
    def result(self, mutate=None):
        docs = specialization_fixture_documents()
        if mutate:
            mutate(docs)
            rebind_protocol(docs)
        with tempfile.TemporaryDirectory() as directory:
            path, sha = write_fixture(directory, docs)
            return evaluate(OwnerContext(directory, path, sha), FIXED_TEST_TIME)

    def stopped(self, result, reason):
        self.assertEqual(result["decision"], STOP)
        self.assertIsNone(result["selected_candidate"])
        self.assertFalse(result["production_eligible"])
        self.assertIn(reason, json.dumps(result))

    def test_equal_quality_and_conservative_savings_can_recommend(self):
        r = self.result()
        self.assertEqual(r["decision"], RECOMMEND)
        self.assertEqual(r["selected_candidate"], "EDIT")
        c = r["candidate_results"][0]
        self.assertEqual(c["weighted_gain_lower"], 0.0)
        self.assertEqual(c["incremental_resources_upper_bound"], {"CPU_second": -90})
        self.assertAlmostEqual(c["converted_future_cost"], -.9)
        self.assertAlmostEqual(c["net_value_lower"], .9)
        self.assertFalse(r["production_eligible"])
        self.assertEqual(r["pareto_candidates"], ["EDIT"])

    def test_quality_loss_outside_frozen_tolerance_stops(self):
        def mutate(d):
            d["protocol"]["maximum_quality_loss"] = {"iid": .001, "ood": .001}
            for row in d["outcomes"]["records"]:
                if row["candidate_id"] != "ORIGINAL":
                    row["utility"] -= .01
        self.stopped(self.result(mutate), "quality retention")

    def test_missing_original_lower_bound_is_not_zero(self):
        r = self.result(lambda d: d["costs"]["original"]["resources_lower_bound"].update(CPU_second=None))
        self.stopped(r, "missing_future_bound:CPU_second")
        self.assertTrue(all(c["net_value_lower"] is None for c in r["candidate_results"]))

    def test_missing_candidate_upper_bound_stops(self):
        def mutate(d):
            for c in d["costs"]["records"].values():
                c["resources_upper_bound"]["CPU_second"] = None
        self.stopped(self.result(mutate), "missing_future_bound:CPU_second")

    def test_unknown_baseline_component_stops(self):
        self.stopped(self.result(lambda d: d["costs"]["original"].update(unmeasured_components=["IO"])),
                     "original:IO")

    def test_missing_conversion_has_sensitivity_but_stops(self):
        r = self.result(lambda d: d["protocol"].update(exchange_rates=None))
        self.stopped(r, "missing fixed horizon or resource-to-utility conversion")
        c = r["candidate_results"][0]
        self.assertEqual(c["resource_conversion_sensitivity"]["CPU_second"]["strict_net_positive_condition_with_other_costs_zero"],
                         "lambda > boundary")
        self.assertEqual(r["pareto_candidates"], ["EDIT"])

    def test_missing_horizon_stops(self):
        def mutate(d):
            d["protocol"]["horizon_episodes"] = None
            d["costs"]["horizon_episodes"] = None
        self.stopped(self.result(mutate), "missing fixed horizon")

    def test_bound_horizon_must_match(self):
        self.stopped(self.result(lambda d: d["costs"].update(horizon_episodes=1000)), "horizon mismatch")

    def test_past_timing_is_not_a_future_bound(self):
        self.stopped(self.result(lambda d: d["costs"]["original"].update(basis="measured_past_timing")), "bound basis")

    def test_resource_coordinates_cannot_be_filled_with_zero(self):
        self.stopped(self.result(lambda d: d["costs"]["original"]["resources_lower_bound"].update(GPU_second=100)),
                     "resource coordinates differ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
