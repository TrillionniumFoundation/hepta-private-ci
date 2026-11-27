import copy
import itertools
import unittest
from unittest.mock import patch

from independent.accounting import WorkLedger
from independent.controller_cost import controller_work
from independent.evaluation import output_work
from independent.gain_head import fit_work, head_work
from independent.inference import FrozenGenerator
from independent.learning import setup_work, value_work
from independent.refinement import admit_round, forecast, observer_work, reserve_work, validation_work
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

    def test_cached_static_reserves_one_actual_prepare_and_sampler_without_rowwise_decode(self):
        from independent.output_codec import preparation_work, request_work
        plan = {"output_codec_profile": "local-png-codebook-v1", "static_modes": ["full"]}
        gen = FrozenGenerator(self.model, prepare_low=False)
        for n in (1, 73, 768):
            for mode in ("full", "low", "ensemble"):
                generation = gen.full_work(n) if mode == "full" else combine(gen.low_work(n), gen.prepare_work())
                if mode == "ensemble":
                    generation = combine(generation, gen.full_work(n), {"scalar_ops": 24 * n, "div_ops": 24 * n})
                expected = combine(generation, preparation_work(), request_work(n))
                for system in ("supervised", "anchor", "additive", "ndu"):
                    with self.subTest(n=n, mode=mode, system=system), \
                            patch("independent.output_codec.prepare_codec", side_effect=AssertionError("forecast encoded PNG")), \
                            patch("independent.refinement.controller_work", side_effect=AssertionError("unused controller")):
                        rows = {**self.rows, "validation_rows": n}
                        actual = reserve_work(self.model, system, mode, **rows, plan=plan)
                    self.assertEqual(actual["service"], expected)
                    self.assertEqual(actual["tail"], combine(expected, actual["observer"]))
                    self.assertEqual((actual["critic"], actual["paired_calibration"]), ({}, {}))
                    self.assertEqual(actual["revalidation"], validation_work(self.model, n, ["full"]))

    def test_cached_full_reserve_matches_executed_handmade_measure_and_costs_more_for_one_row(self):
        import numpy as np
        from independent.evaluation import measure
        for n in (1, 73):
            full = np.zeros((n, 202))
            full[:, :192] = np.linspace(0, 1, n * 192).reshape(n, 192)
            full[:, [192, 196, 199]] = 1
            plan = {"output_codec_profile": "local-png-codebook-v1", "static_modes": ["full"],
                "compute_price": .02, "service_horizon": 100000, "runtime_backend": "python",
                "runtime_batch_size": 64, "inference_cap_full_equivalents": 2}
            reserved = reserve_work(self.model, "ndu", "full", **{**self.rows, "validation_rows": n}, plan=plan)
            with patch("independent.evaluation.time.process_time_ns", side_effect=itertools.count(1000, 100).__next__), \
                    patch("independent.evaluation.time.perf_counter_ns", side_effect=itertools.count(2000, 100).__next__):
                actual = measure(self.model, None, "full", {"full": full}, plan, 100000, seed=11, observe=False)
            billed = sum(actual["per_row_cost"]["work_units"]) + actual["cost"]["prepare"]["consumed_units"]
            quote = WorkLedger("exact-cached-quote").estimate_kernel(**reserved["service"])
            self.assertEqual(billed, quote)
            self.assertEqual(actual["cost"]["prepare"]["totals"]["png_encodes"], 12)
            self.assertEqual(actual["cost"]["operator_totals"].get("decoder_elements", 0), 0)
            self.assertGreater(actual["cost"]["output_codec_storage"]["retained_encoded_ascii_bytes"], 0)
            rowwise = reserve_work(self.model, "ndu", "full", **{**self.rows, "validation_rows": n})
            old_quote = WorkLedger("rowwise-quote").estimate_kernel(**rowwise["service"])
            if n == 1:
                self.assertGreater(quote, old_quote)
            else:
                self.assertLess(quote, old_quote)

    def test_explicit_rowwise_preserves_all_legacy_reserves_and_controller_cache_rejects(self):
        for system in ("supervised", "ndu_control"):
            for mode in ("full", "low", "ensemble"):
                expected = reserve_work(self.model, system, mode, **self.rows)
                actual = reserve_work(self.model, system, mode, **self.rows,
                    plan={"output_codec_profile": "rowwise-png-v1"})
                self.assertEqual(actual, expected)
        with patch("independent.refinement.controller_work", side_effect=AssertionError("unsupported fit quoted")):
            with self.assertRaisesRegex(ValueError, "controller/codebook"):
                reserve_work(self.model, "ndu_control", "full", **self.rows,
                    plan={"output_codec_profile": "local-png-codebook-v1"})
        for invalid in (None, True, "unknown"):
            with self.subTest(profile=invalid), self.assertRaisesRegex(ValueError, "output codec"):
                reserve_work(self.model, "ndu", "full", **self.rows,
                    plan={"output_codec_profile": invalid})

    def test_cached_forecast_uses_internal_train_monitor_rows_and_billed_prepare_samples(self):
        selected, candidates, common, plan, inventories = fixtures()
        plan.update(output_codec_profile="local-png-codebook-v1", static_modes=["full"],
                    preparation_forecast="median-plus-one-observed-excess-v1",
                    experiment_id="codec-train-d1", training_diagnostic={"monitor_sources_per_class": 4})
        plan["data_profile"].update(sources_per_class={"validation": 6}, instructions_per_source=8, variants=2)
        for row in selected:
            row["mode"] = "full"
            common["calibrations"][row["seed"]]["prepare_cpu_samples_ns"] = {"full": [100, 200, 300]}
            common["calibrations"][row["seed"]]["prepare_cpu_ns"]["full"] = 300
        ledger = WorkLedger("cached-internal-monitor", total_cap=1000000)
        before = ledger.snapshot()
        receipt = forecast("ndu", selected, candidates, common, plan, inventories, ledger)
        self.assertEqual([row["requests"] for row in receipt["service_profiles"]], [768] * 3)
        self.assertEqual([row["measures"] for row in receipt["service_profiles"]], [1] * 3)
        self.assertEqual([row["prepare_cpu_forecast_ns"] for row in receipt["service_profiles"]], [300] * 3)
        self.assertAlmostEqual(receipt["preparation_cpu_seconds"], 3 * 300 * 1.5 / 1e9)
        self.assertEqual(ledger.snapshot(), before)
        for invalid in (None, {}, {"monitor_sources_per_class": True}, {"monitor_sources_per_class": 0}):
            with self.subTest(diagnostic=invalid), self.assertRaisesRegex(ValueError, "TRAIN-only monitor geometry"):
                forecast("ndu", selected, candidates, common,
                         {**plan, "training_diagnostic": invalid}, inventories, ledger)

    def test_observation_reuse_removes_only_duplicate_setup_from_full_reserves(self):
        n = self.rows["validation_rows"]
        gen = FrozenGenerator(self.model, prepare_low=False)
        setup = setup_work(self.model.dimensions, "additive")
        old_validation = combine(gen.full_work(n), gen.low_work(n), gen.prepare_work(),
            {"scalar_ops": 24 * n, "div_ops": 24 * n},
            scaled(observer_work(n), 3), scaled(setup, 6))
        old_observation = combine(scaled(setup, 3), observer_work(n),
                                  {"macs": 2 * n * 12 * 12, "scalar_ops": 2 * n})
        self.assertEqual(combine(validation_work(self.model, n), scaled(setup, 5)), old_validation)
        cases = [("supervised", mode, None) for mode in ("full", "low", "ensemble")]
        cases += [("ndu_control", "full", plan) for plan in (None, self.affine_plan)]
        for system, mode, plan in cases:
            with self.subTest(system=system, mode=mode, plan=plan):
                current = reserve_work(self.model, system, mode, **self.rows, plan=plan)
                with patch("independent.refinement._observation_work", return_value=old_observation), \
                        patch("independent.refinement.validation_work", return_value=old_validation):
                    previous = reserve_work(self.model, system, mode, **self.rows, plan=plan)
                removed = scaled(setup, 2 if system == "ndu_control" else 1)
                self.assertEqual(combine(current["observer"], removed), previous["observer"])
                self.assertEqual(combine(current["tail"], removed), previous["tail"])
                self.assertEqual(combine(current["revalidation"], scaled(setup, 5)),
                                 previous["revalidation"])
                for key in ("service", "critic", "paired_calibration"):
                    self.assertEqual(current[key], previous[key], key)

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

    def test_folded_forecast_uses_actual_charged_units_instead_of_worst_step_quotes(self):
        selected, candidates, common, plan, inventories = fixtures()
        plan["adaptation_kernel"] = "folded-mixed-encoder-v1"
        candidates[0]["objective_step_units"] = 6000
        candidates[1]["objective_step_units"] = 5000
        ledger = WorkLedger("actual-step-forecast", total_cap=1000000)
        before = ledger.snapshot()
        receipt = forecast("supervised", selected, candidates, common, plan, inventories, ledger)
        for actual, expected in zip(receipt["training_cpu_per_unit_samples"], (0.0002, 0.0008)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(receipt["training_cpu_per_unit_max"], 0.0008)
        self.assertAlmostEqual(receipt["arithmetic_cpu_seconds"], 0.528)
        self.assertAlmostEqual(receipt["changed_model_cpu_seconds"], 0.642)
        self.assertEqual(receipt["training_rate_unit_basis"], "objective-step-ledger-deltas-v1")
        self.assertEqual(receipt["training_rate_inputs"], [
            {key: row[key] for key in ("name", "updates", "candidate_step_units",
                                      "objective_step_cpu_seconds", "objective_step_units")}
            for row in candidates])
        self.assertEqual(ledger.snapshot(), before)

    def test_actual_unit_boundary_and_legacy_receipts_remain_compatible(self):
        selected, candidates, common, plan, inventories = fixtures()
        ledger = WorkLedger("legacy-step-forecast", total_cap=1000000)
        legacy = forecast("supervised", selected, candidates, common, plan, inventories, ledger)
        for row in candidates:
            row["objective_step_units"] = 1
        self.assertEqual(forecast("supervised", selected, candidates, common, plan, inventories, ledger),
                         legacy)
        plan["adaptation_kernel"] = "folded-mixed-encoder-v1"
        for row in candidates:
            row["objective_step_units"] = row["updates"] * row["candidate_step_units"]
        expected = copy.deepcopy(legacy)
        expected["training_rate_unit_basis"] = "objective-step-ledger-deltas-v1"
        for source, recorded in zip(candidates, expected["training_rate_inputs"]):
            recorded["objective_step_units"] = source["objective_step_units"]
        self.assertEqual(forecast("supervised", selected, candidates, common, plan, inventories, ledger),
                         expected)

    def test_folded_forecast_requires_valid_actual_units_for_every_candidate(self):
        selected, candidates, common, plan, inventories = fixtures()
        plan["adaptation_kernel"] = "folded-mixed-encoder-v1"
        for row in candidates:
            row["objective_step_units"] = row["updates"] * row["candidate_step_units"]
        ledger = WorkLedger("invalid-actual-step-forecast", total_cap=1000000)
        for index, row in enumerate(candidates):
            for invalid in (None, True, 0, -1, 1.5, float("nan"), float("inf"),
                            row["objective_step_units"] + 1):
                changed = copy.deepcopy(candidates)
                changed[index]["objective_step_units"] = invalid
                with self.subTest(candidate=index, actual_units=invalid):
                    with self.assertRaisesRegex(ValueError, "actual objective-step units"):
                        forecast("supervised", selected, changed, common, plan, inventories, ledger)
            changed = copy.deepcopy(candidates)
            del changed[index]["objective_step_units"]
            with self.subTest(candidate=index, actual_units="missing"):
                with self.assertRaisesRegex(ValueError, "actual objective-step units"):
                    forecast("supervised", selected, changed, common, plan, inventories, ledger)
        for invalid in (None, "unknown", True, 0):
            with self.subTest(adaptation_kernel=invalid):
                with self.assertRaisesRegex(ValueError, "unsupported adaptation kernel"):
                    forecast("supervised", selected, candidates, common,
                             {**plan, "adaptation_kernel": invalid}, inventories, ledger)

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

    def preparation_fixture(self):
        selected, candidates, common, plan, inventories = fixtures()
        plan["preparation_forecast"] = "median-plus-one-observed-excess-v1"
        for calibration in common["calibrations"].values():
            calibration["prepare_cpu_samples_ns"] = {
                mode: [10000, 20000, 200000] for mode in plan["static_modes"]}
            calibration["prepare_cpu_ns"] = {mode: 200000 for mode in plan["static_modes"]}
        return selected, candidates, common, plan, inventories

    def test_repeated_preparation_retains_one_observed_excess_without_charging(self):
        selected, candidates, common, plan, inventories = self.preparation_fixture()
        ledger = WorkLedger("preparation-forecast", total_cap=1000000)
        before, original = ledger.snapshot(), copy.deepcopy(common)
        receipt = forecast("ndu_control", selected, candidates, common, plan, inventories, ledger)
        for profile in receipt["service_profiles"]:
            self.assertEqual(profile["measures"], 8)
            self.assertEqual(profile["prepare_cpu_samples_ns"], [10000, 20000, 200000])
            self.assertEqual(profile["prepare_cpu_median_ns"], 20000)
            self.assertEqual(profile["prepare_cpu_max_ns"], 200000)
            self.assertEqual(profile["prepare_cpu_observed_excess_ns"], 180000)
            self.assertEqual(profile["prepare_cpu_forecast_ns"], 8 * 20000 + 180000)
            self.assertEqual(profile["preparation_forecast"], plan["preparation_forecast"])
        self.assertAlmostEqual(receipt["preparation_cpu_seconds"], 3 * 340000 * 1.5 / 1e9)
        self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(common, original)

    def test_single_preparation_matches_legacy_max_and_equal_samples_scale_normally(self):
        selected, candidates, common, plan, inventories = self.preparation_fixture()
        ledger = WorkLedger("single-preparation")
        current = forecast("supervised", selected, candidates, common, plan, inventories, ledger)
        legacy_plan = {key: value for key, value in plan.items() if key != "preparation_forecast"}
        legacy = forecast("supervised", selected, candidates, common, legacy_plan, inventories, ledger)
        self.assertEqual(current["preparation_cpu_seconds"], legacy["preparation_cpu_seconds"])
        self.assertTrue(all(row["prepare_cpu_forecast_ns"] == 200000 for row in current["service_profiles"]))
        for calibration in common["calibrations"].values():
            calibration["prepare_cpu_samples_ns"]["ensemble"] = [200000] * 3
        equal = forecast("ndu_control", selected, candidates, common, plan, inventories, ledger)
        self.assertTrue(all(row["prepare_cpu_observed_excess_ns"] == 0 for row in equal["service_profiles"]))
        self.assertTrue(all(row["prepare_cpu_forecast_ns"] == 8 * 200000 for row in equal["service_profiles"]))

    def test_new_preparation_policy_rejects_missing_invalid_or_inconsistent_train_samples(self):
        selected, candidates, common, plan, inventories = self.preparation_fixture()
        ledger = WorkLedger("invalid-preparation")
        for invalid in (None, [], [10000, 200000], [1, 2, 3, 200000],
                        [10000, float("nan"), 200000], [10000, float("inf"), 200000],
                        [10000, -1, 200000], [10000, True, 200000],
                        [10000, 20000.0, 200000], [10000, 20000, 2**63], [10000, 20000, 199999]):
            changed = copy.deepcopy(common)
            changed["calibrations"][11]["prepare_cpu_samples_ns"]["ensemble"] = invalid
            with self.subTest(samples=invalid):
                with self.assertRaises(ValueError):
                    forecast("ndu_control", selected, candidates, changed, plan, inventories, ledger)
        changed = copy.deepcopy(common)
        del changed["calibrations"][11]["prepare_cpu_samples_ns"]
        with self.assertRaises(ValueError):
            forecast("ndu_control", selected, candidates, changed, plan, inventories, ledger)
        for invalid in (None, "unknown"):
            with self.assertRaises(ValueError):
                forecast("ndu_control", selected, candidates, common,
                         {**plan, "preparation_forecast": invalid}, inventories, ledger)
        for invalid in (0, -1, True, 3.0, float("nan"), float("inf"), 2**63):
            with self.subTest(repeats=invalid):
                with self.assertRaises(ValueError):
                    forecast("ndu_control", selected, candidates, common,
                             {**plan, "calibration_repeats": invalid}, inventories, ledger)

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
