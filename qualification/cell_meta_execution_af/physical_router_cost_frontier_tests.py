"""Genuine CPU fixture and adversarial read-only observed-cost boundary tests.

These are synthetic reference mechanisms, not authenticated target-host metrics.
"""
from __future__ import annotations

import copy
import math
import tempfile
import unittest
from pathlib import Path

from qualification.cell_meta_execution_af import physical_router_trial as trial
from qualification.cell_meta_execution_af import physical_router_top1 as top1
from qualification.cell_meta_execution_af import physical_router_hard_train as hard
from qualification.cell_meta_execution_af import physical_router_frozen_baseline as frozen
from qualification.cell_meta_execution_af import physical_router_fivearm_review as five
from qualification.cell_meta_execution_af import physical_router_paired_screen as paired
from qualification.cell_meta_execution_af import physical_router_cost_frontier as costs
from qualification.cell_meta_execution_af import physical_router_audit as audit


class ObservedWorkFrontierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundles = {}
        # One original source cohort with three different training seeds.
        original = trial.synthetic_panel(seed=41, rule="conditional", rows=32)
        for seed in paired.SEEDS:
            panel = copy.deepcopy(original)
            panel["source"]["seed"] = seed
            soft = trial.run(panel, steps=2)
            posthoc = top1.create_report(panel, soft)
            learned = hard.produce(panel, soft, posthoc)
            frozen_report = frozen.produce(panel, soft, posthoc, learned)
            five_report = five.descriptive(panel, soft, posthoc, learned, frozen_report)
            cls.bundles[seed] = {"panel": panel, "soft": soft,
                                 "posthoc": posthoc, "hard": learned,
                                 "frozen": frozen_report, "five": five_report}
        cls.paired = paired.screen(cls.bundles)
        cls.result = costs.evaluate(cls.bundles, cls.paired)

    def invalid_meter(self, seed, arm, field, value):
        local = copy.deepcopy(self.bundles[seed])
        local["hard"]["results"][arm]["meters"][field] = value
        with self.assertRaises(costs.CostFrontierDenied):
            costs._per_seed(local)

    def test_three_seed_five_arm_counts_and_no_authority(self):
        self.assertEqual(self.result["schema"], costs.SCHEMA)
        self.assertEqual(set(self.result["per_seed_observed_work"]), {"41", "47", "53"})
        self.assertEqual(self.result["unique_original_rows_not_multiplied_by_seeds"], 192)
        self.assertFalse(self.result["full_lifecycle_cost_matched"])
        self.assertFalse(self.result["all_costs_independently_attested"])
        self.assertFalse(self.result["statistical_or_resource_winner_certified"])
        self.assertEqual(self.result["production_admission"], "BLOCKED")
        self.assertEqual(self.result["authority_posture"], "DENY_ALL")

    def test_canonical_saved_json_seed_keys_replay(self):
        # Independent screener's runtime map uses integer seed keys, but JSON
        # materializes object keys as strings. This must not reject true evidence.
        serialized = audit.canonical(self.paired)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"paired.json"
            path.write_bytes(serialized)
            restored = audit.load(path)
        self.assertNotEqual(self.paired, restored)
        self.assertEqual(costs.evaluate(self.bundles, restored), self.result)

    def test_adaptive_nosplit_receives_no_extra_router_work(self):
        # Use a separately generated stable task; all three conditional
        # cohorts can legitimately trigger split when features are shared.
        panel = trial.synthetic_panel(seed=41, rule="stable", rows=32)
        soft = trial.run(panel, steps=2)
        posthoc = top1.create_report(panel, soft)
        learned = hard.produce(panel, soft, posthoc)
        frozen_report = frozen.produce(panel, soft, posthoc, learned)
        five_report = five.descriptive(panel, soft, posthoc, learned, frozen_report)
        vals = costs._per_seed({"panel":panel,"hard":learned,
                                "frozen":frozen_report,"five":five_report})["arms"]
        adaptive = vals[-1]
        self.assertFalse(adaptive["split_proposed"])
        self.assertEqual(adaptive["additional_router_train_rows"], 0)
        self.assertEqual(adaptive["additional_router_eval_rows"], 0)
        self.assertEqual(adaptive["stage2_route_samples"], 0)

    def test_frozen_has_zero_stage2_but_not_free_stage1(self):
        f = self.result["per_seed_observed_work"]["41"]["arms"][0]
        self.assertEqual(f["reused_stage1_primary_head_rows"], 64)
        self.assertEqual(f["stage2_primary_train_head_rows"], 0)
        self.assertEqual(f["stage2_head_optimizer_updates"], 0)
        self.assertEqual(f["eval_primary_head_rows"], 128)
        self.assertEqual(f["head_weight_payload_bytes_fp32"], 20)
        self.assertIsNone(f["reported_training_cpu_seconds"])

    def test_hard_arms_share_primary_work_not_full_cost(self):
        vals = self.result["per_seed_observed_work"]["41"]["arms"]
        self.assertEqual(len({x["all_primary_head_rows_including_stage1"]
                              for x in vals[1:]}), 1)
        self.assertGreater(vals[2]["additional_diagnostic_head_rows"],
                           vals[1]["additional_diagnostic_head_rows"])
        self.assertEqual(vals[1]["additional_router_train_rows"], 0)
        self.assertGreater(vals[2]["additional_router_train_rows"], 0)
        self.assertTrue(self.result["additional_diagnostic_and_router_work_differs_between_arms"])

    def test_split_and_stochastic_router_training_not_free(self):
        vals = self.result["per_seed_observed_work"]["41"]["arms"]
        self.assertEqual(vals[2]["stage2_route_samples"], 0)
        self.assertGreater(vals[3]["stage2_route_samples"], 0)
        self.assertEqual(vals[3]["stage2_router_optimizer_updates"], 2)
        self.assertEqual(vals[4]["stage2_router_optimizer_updates"], 2)
        self.assertTrue(vals[3]["cpu_timings_do_not_have_identical_scope"])

    def test_undisclosed_encoder_and_power_stay_null_not_zero(self):
        self.assertFalse(self.result["actual_encoder_hardware_forward_receipt_available"])
        self.assertIn("cpu_energy_or_gpu_energy_joules",
                      self.result["unmeasured_resource_components"])
        self.assertIn("independent_evaluation_search_and_failed_candidate_work",
                      self.result["unmeasured_resource_components"])
        self.assertFalse(self.result["cpu_timing_scope_is_comparable"])

    def test_bad_stage2_head_count_denied(self):
        self.invalid_meter(41, 1, "train_head_0_rows", 0)

    def test_fake_forward_conservation_denied(self):
        self.invalid_meter(41, 0, "sample_exposures", 1)

    def test_hidden_split_diagnostic_denied(self):
        self.invalid_meter(41, 1, "diagnostic_head_rows", 128)

    def test_fabricated_fixed_router_samples_denied(self):
        self.invalid_meter(41, 1, "sampled_routes", 1)

    def test_suppressed_learned_gradient_work_denied(self):
        self.invalid_meter(41, 2, "learned_gate_optimizer_steps", 0)

    def test_hidden_route_eval_rows_denied(self):
        self.invalid_meter(41, 1, "eval_router_rows", 0)

    def test_fake_split_parity_router_rows_denied(self):
        self.invalid_meter(41, 1, "diagnostic_router_rows", 0)

    def test_wrong_stage2_updates_denied(self):
        self.invalid_meter(41, 0, "optimizer_steps", 0)

    def test_negative_or_nonfinite_cpu_cost_denied(self):
        for value in (-0.1, math.nan, math.inf):
            with self.subTest(value=value):
                self.invalid_meter(41, 0, "train_cpu_seconds", value)

    def test_unaccounted_head_residency_denied(self):
        local = copy.deepcopy(self.bundles[41])
        local["hard"]["results"][1]["resident_weight_bytes_fp32"] = 1
        with self.assertRaises(costs.CostFrontierDenied):
            costs._per_seed(local)

    def test_frozen_must_have_zero_router_count(self):
        local = copy.deepcopy(self.bundles[41])
        local["frozen"]["meters"]["additional_eval_router_rows"] = 1
        with self.assertRaises(costs.CostFrontierDenied):
            costs._per_seed(local)

    def test_forged_source_budget_or_model_use_denied(self):
        local = copy.deepcopy(self.bundles[41])
        local["five"]["complete_lifecycle_compute_matched"] = True
        with self.assertRaises(costs.CostFrontierDenied):
            costs._per_seed(local)
        local = copy.deepcopy(self.bundles[41])
        local["five"]["production_admission"] = "ACCEPTED"
        with self.assertRaises(costs.CostFrontierDenied):
            costs._per_seed(local)

    def test_recomputed_original_source_review_detects_changed_seed(self):
        changes = copy.deepcopy(self.bundles)
        changes[47]["panel"]["source"]["seed"] = 48
        with self.assertRaises((paired.PairedScreenDenied, ValueError)):
            costs.evaluate(changes, self.paired)

    def test_modified_paired_report_even_with_sha_not_trusted(self):
        changed = copy.deepcopy(self.paired)
        changed["retrospective_paired"]["future_1"]["comparisons"][
            "adaptive_minus_fixed"]["mean_brier_delta"] += 0.1
        with self.assertRaises(costs.CostFrontierDenied):
            costs.evaluate(self.bundles, changed)

    def test_missing_seed_denied(self):
        with self.assertRaises(paired.PairedScreenDenied):
            costs.evaluate({41: self.bundles[41], 47: self.bundles[47]}, self.paired)


if __name__ == "__main__":
    unittest.main()

# Dedicated workflow source regression, independent of PyYAML being installed.
class WorkflowBoundaryTests(unittest.TestCase):
    def test_no_blank_line_between_pycompile_continuations(self):
        root = Path(__file__).resolve().parents[2]
        workflow = root / ".github/workflows/hepta-cell-meta-granite-real.yml"
        source = workflow.read_text(encoding="utf-8")
        self.assertNotIn("\\\n\n", source)
        self.assertIn("physical_router_cost_frontier.py", source)
        self.assertIn("physical_router_cost_frontier_tests.py", source)
        self.assertIn("observed-work-frontier.json", source)
