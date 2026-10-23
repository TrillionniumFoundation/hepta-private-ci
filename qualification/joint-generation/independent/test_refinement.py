import copy
import unittest
from unittest.mock import patch

from independent.accounting import WorkLedger
from independent.controller_cost import controller_work
from independent.evaluation import output_work
from independent.gain_head import fit_work, head_work
from independent.inference import FrozenGenerator
from independent.learning import setup_work, value_work
from independent.refinement import admit_round, forecast, reserve_work
from model import JointModel


def combine(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + value
    return result


def scaled(part, count):
    return {key: value * count for key, value in part.items()}


def fixtures():
    selected = [{"seed": 11, "mode": "full"}, {"seed": 23, "mode": "low"},
                {"seed": 47, "mode": "ensemble"}]
    candidates = [
        {"name": "candidate-11", "updates": 4, "candidate_step_units": 3000,
         "objective_step_cpu_seconds": 1.2, "serialization_cpu_seconds": 0.03},
        {"name": "candidate-23", "updates": 5, "candidate_step_units": 4000,
         "objective_step_cpu_seconds": 4.0, "serialization_cpu_seconds": 0.07},
    ]
    common = {"calibrations": {seed: {
        "cpu_ns": {"full": 10000000, "low": 5000000, "ensemble": 20000000},
        "prepare_cpu_ns": {"full": 0, "low": 100000, "ensemble": 200000},
    } for seed in (11, 23, 47)}}
    plan = {"refinement_cpu_unit_safety": 2.0, "refinement_service_cpu_multiplier": 1.5,
            "data_profile": {"sources_per_class": {"validation": 1},
                             "instructions_per_source": 2, "variants": 1},
            "static_modes": ["full", "low", "ensemble"], "calibration_rows": 6,
            "calibration_repeats": 3, "tail_reserve_cpu_seconds": 10.0,
            "control_reserve_cpu_seconds": 5.0, "cpu_seconds_per_system": 1000.0}
    inventories = {"service": {"macs": 200}, "observer": {"scalar_ops": 50},
                   "critic": {"macs": 30}, "paired_calibration": {"scalar_ops": 70},
                   "tail": {"macs": 230, "scalar_ops": 120},
                   "revalidation": {"macs": 40, "scalar_ops": 10}}
    return selected, candidates, common, plan, inventories


class RefinementTests(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=4, seed=19851)
        self.rows = {"train_rows": 48, "validation_rows": 12,
                     "calibration_rows": 24, "calibration_repeats": 3}
        self.affine_plan = {"controller": {
            "gain_head": "low-hidden-instruction-affine-v1", "ridge_regularization": 0.001}}

    def outputs(self, n):
        pixels = self.model.dimensions[2]
        return combine(scaled(output_work(12, pixels), n), {
            "scalar_ops": 3 * n * pixels, "compare_ops": 2 * n * pixels,
            "exp_ops": n * pixels, "div_ops": n * pixels})

    def test_static_reserves_no_unused_critic_or_paired_calibration(self):
        before = self.model.digest()
        for mode in ("full", "low", "ensemble"):
            reserved = reserve_work(self.model, "supervised", mode, **self.rows)
            self.assertEqual((reserved["critic"], reserved["paired_calibration"]), ({}, {}))
            self.assertEqual(reserved["tail"], combine(reserved["service"], reserved["observer"]))
            self.assertGreater(WorkLedger("price").estimate_kernel(**reserved["revalidation"]), 0)
        self.assertEqual(self.model.digest(), before)

    def test_affine_plan_does_not_charge_static_fit_or_head(self):
        for mode in ("full", "low", "ensemble"):
            expected = reserve_work(self.model, "supervised", mode, **self.rows)
            with patch("independent.gain_head.head_work", side_effect=AssertionError("unused head")), \
                    patch("independent.refinement.controller_work", side_effect=AssertionError("unused fit")):
                actual = reserve_work(self.model, "supervised", mode, **self.rows,
                                      plan=self.affine_plan)
            self.assertEqual(actual, expected)

    def test_affine_reserves_exact_fit_pairs_and_complete_service_without_extra_encoder(self):
        before = self.model.digest()
        gen = FrozenGenerator(self.model, prepare_low=False)
        n, m, h = self.rows["validation_rows"], self.rows["calibration_rows"], self.model.dimensions[3]
        reserved = reserve_work(self.model, "ndu_control", "full", **self.rows,
                                plan=self.affine_plan)
        total = controller_work(self.model, self.rows["train_rows"], m,
                                self.rows["calibration_repeats"], plan=self.affine_plan)
        self.assertEqual(combine(reserved["critic"], reserved["paired_calibration"]), total)
        pair = combine(scaled(gen.low_work(m), 2), gen.full_work(m),
                       scaled(head_work(h, m), 2), scaled(self.outputs(m), 2),
                       scaled(gen.prepare_work(), 2))
        self.assertEqual(reserved["paired_calibration"], scaled(pair, self.rows["calibration_repeats"]))
        expected_service = combine(scaled(gen.full_work(n), 2), gen.low_work(n),
            head_work(h, n), {"scalar_ops": n, "compare_ops": n},
            scaled(gen.prepare_work(), 2), scaled(self.outputs(n), 2))
        self.assertEqual(reserved["service"], expected_service)
        fitting = fit_work(h, self.rows["train_rows"], self.affine_plan)
        for key, units in fitting.items():
            self.assertGreaterEqual(reserved["critic"].get(key, 0), units, key)
        self.assertEqual(reserved["tail"], combine(reserved["service"], reserved["observer"],
                                                reserved["critic"], reserved["paired_calibration"]))
        self.assertEqual(self.model.digest(), before)

    def test_explicit_ridge_plan_preserves_legacy_reserves(self):
        expected = reserve_work(self.model, "ndu_control", "full", **self.rows)
        actual = reserve_work(self.model, "ndu_control", "full", **self.rows,
                              plan={"controller": {"gain_head": "probability-ridge-v1"}})
        self.assertEqual(actual, expected)

    def test_authoritative_inventory_cannot_omit_reserved_pairs(self):
        with patch("independent.refinement.controller_work", return_value={}):
            with self.assertRaisesRegex(ValueError, "omits reserved paired work"):
                reserve_work(self.model, "ndu_control", "full", **self.rows,
                             plan=self.affine_plan)

    def test_control_reserves_two_training_views_and_raw_values_plus_complete_pairs(self):
        generator = FrozenGenerator(self.model, prepare_low=False)
        n = self.rows["train_rows"]
        cached = reserve_work(self.model, "ndu_control", "full", **self.rows)
        uncached = reserve_work(self.model, "ndu_control", "full", **self.rows, raw_reward_cached=False)
        self.assertEqual(combine(cached["critic"], cached["paired_calibration"]),
                         controller_work(self.model, n, self.rows["calibration_rows"],
                                         self.rows["calibration_repeats"]))
        lower_bound = combine(generator.low_work(n), generator.full_work(n),
                              generator.prepare_work(), scaled(value_work("additive", n), 2))
        for key, minimum in lower_bound.items():
            self.assertGreaterEqual(cached["critic"].get(key, 0), minimum, key)
        differences = {key: uncached["critic"].get(key, 0) - cached["critic"].get(key, 0)
                       for key in set(cached["critic"]) | set(uncached["critic"])}
        self.assertEqual({key: value for key, value in differences.items() if value},
                         setup_work(self.model.dimensions, "additive"))
        m = self.rows["calibration_rows"]
        pixels = self.model.dimensions[2]
        outputs = combine(scaled(output_work(12, pixels), m), {
            "scalar_ops": 3 * m * pixels, "compare_ops": 2 * m * pixels,
            "exp_ops": m * pixels, "div_ops": m * pixels})
        pair = combine(scaled(generator.low_work(m), 2), generator.full_work(m),
                       scaled(generator.critic_work(m), 2), scaled(outputs, 2),
                       scaled(generator.prepare_work(), 2))
        self.assertEqual(cached["paired_calibration"], scaled(pair, self.rows["calibration_repeats"]))
        self.assertEqual(cached["tail"], combine(cached["service"], cached["observer"],
                                                cached["critic"], cached["paired_calibration"]))

    def test_forecast_prices_all_three_seeds_and_uses_cpu_per_update_unit(self):
        selected, candidates, common, plan, inventories = fixtures()
        ledger = WorkLedger("forecast", total_cap=1000000)
        before = ledger.snapshot()
        receipt = forecast("supervised", selected, candidates, common, plan, inventories, ledger)
        self.assertEqual(ledger.snapshot(), before)
        self.assertAlmostEqual(receipt["training_cpu_per_unit_max"], 0.0002)
        self.assertEqual(len(receipt["training_rate_inputs"]), len(candidates))
        self.assertEqual(receipt["tail_units"], 1740)
        self.assertEqual(receipt["changed_model_units"], 270)
        self.assertAlmostEqual(receipt["arithmetic_cpu_seconds"], 0.132)
        self.assertAlmostEqual(receipt["changed_model_cpu_seconds"], 0.318)
        self.assertAlmostEqual(receipt["serialization_cpu_seconds_max"], 0.07)
        self.assertEqual([row["mode"] for row in receipt["service_profiles"]],
                         ["full", "low", "ensemble"])
        self.assertEqual([row["requests"] for row in receipt["service_profiles"]], [24, 24, 24])
        self.assertEqual([row["measures"] for row in receipt["service_profiles"]], [1, 1, 1])

    def test_control_forecast_uses_worst_training_profile_and_floor_only_once(self):
        selected, candidates, common, plan, inventories = fixtures()
        ledger = WorkLedger("control-forecast", total_cap=1000000)
        before = ledger.snapshot()
        receipt = forecast("ndu_control", selected, candidates, common, plan, inventories, ledger)
        self.assertEqual([row["mode"] for row in receipt["service_profiles"]], ["ensemble"] * 3)
        self.assertEqual([row["requests"] for row in receipt["service_profiles"]], [84] * 3)
        self.assertEqual([row["measures"] for row in receipt["service_profiles"]], [8] * 3)
        self.assertAlmostEqual(receipt["service_cpu_seconds"], 7.56)
        self.assertAlmostEqual(receipt["preparation_cpu_seconds"], 0.0072)
        self.assertEqual(receipt["tail_cpu_floor"], 15.0)
        self.assertEqual(receipt["tail_cpu_seconds"], 15.0)
        plan["tail_reserve_cpu_seconds"], plan["control_reserve_cpu_seconds"] = 0.1, 0.2
        observed = forecast("ndu_control", selected, candidates, common, plan, inventories, ledger)
        self.assertAlmostEqual(observed["tail_cpu_seconds"], 7.6992)
        self.assertEqual(ledger.snapshot(), before)

    def test_admission_requires_whole_seed_round_and_revalidation_without_charging(self):
        receipt = {"tail_units": 100, "changed_model_units": 20, "tail_cpu_seconds": 3.0,
                   "changed_model_cpu_seconds": 1.0, "arithmetic_safety": 2.0,
                   "training_cpu_per_unit_max": 0.1, "cpu_cap": 20.0}
        round_units = 3 * 7
        short = WorkLedger("short-round", total_cap=140)
        before = short.snapshot()
        self.assertFalse(admit_round(receipt, short, 1.0, round_units, guard_seconds=0.5))
        self.assertEqual(short.snapshot(), before)
        exact = WorkLedger("exact-round", total_cap=141)
        before = exact.snapshot()
        self.assertTrue(admit_round(receipt, exact, 1.0, round_units, guard_seconds=0.5))
        self.assertEqual(exact.snapshot(), before)
        cpu_bound = {**receipt, "cpu_cap": 15.0}
        self.assertTrue(admit_round(cpu_bound, exact, 1.0, round_units, guard_seconds=10.0))
        cpu_short = {**cpu_bound, "cpu_cap": 14.999999}
        self.assertFalse(admit_round(cpu_short, exact, 1.0, round_units, guard_seconds=10.0))
        self.assertEqual(exact.snapshot(), before)

    def test_bad_count_inputs_are_explicitly_rejected(self):
        for name in self.rows:
            for invalid in (0, -1, True, 1.5):
                with self.subTest(api="reserve", name=name, invalid=invalid):
                    with self.assertRaises(ValueError):
                        reserve_work(self.model, "ndu_control", "full", **{**self.rows, name: invalid})
        selected, candidates, common, plan, inventories = fixtures()
        ledger = WorkLedger("bad-inputs", total_cap=1000000)
        for invalid in (0, -1, True, 1.5):
            changed = copy.deepcopy(candidates)
            changed[0]["updates"] = invalid
            with self.subTest(api="forecast", updates=invalid):
                with self.assertRaises(ValueError):
                    forecast("supervised", selected, changed, common, plan, inventories, ledger)
        receipt = forecast("supervised", selected, candidates, common, plan, inventories, ledger)
        for invalid in (0, -1, True, 1.5):
            with self.subTest(api="admit", step_units=invalid):
                with self.assertRaises(ValueError):
                    admit_round(receipt, ledger, 0.0, invalid, guard_seconds=1.0)
        for cpu, guard in ((-1.0, 1.0), (float("nan"), 1.0),
                           (0.0, -1.0), (0.0, float("inf"))):
            with self.subTest(api="admit", cpu=cpu, guard=guard):
                with self.assertRaises(ValueError):
                    admit_round(receipt, ledger, cpu, 10, guard_seconds=guard)


if __name__ == "__main__":
    unittest.main()
