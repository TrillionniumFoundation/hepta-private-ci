"""Synthetic ledger fixtures: these tests start zero model fits."""

import copy
import hashlib
import unittest

from qualification.hcsn_differentiable.benchmark_admission import (
    ARMS, COST_PARTS, ENERGY_SCOPE, ERROR_AXES, METRICS, validate_plan, validate_results,
)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture():
    plan = {"schema": "hcsn-real-benchmark-v1", "study_id": "new-fixture-only",
            "budget_origin": "new_study_only", "old_study_credit": 0,
            "data_sha256": digest("data"), "split_sha256": digest("splits"),
            "protocol_sha256": digest("protocol"), "measurement_context_sha256": digest("cpu"),
            "timestamp_unit_verified": True, "max_gap_seconds": .03,
            "qualified_max_dt_seconds": .1, "long_gap_policy": "reject",
            "test_used_for_selection": False, "training_seeds": [1, 2, 3, 4, 5],
            "frontend": {"sha256": digest("frontend"), "frozen": True,
                         "fit_partition": "train", "causal": True},
            "budget": {"per_arm_wall_seconds": 100, "tuning_trials": 10,
                       "max_trainable_parameters": 1000, "authorization_reference": "fixture"},
            "numerical_qualification": {"passed": True, "source_sha256": digest("hcsn"),
                                        "evidence_sha256": digest("qualification")},
            "partitions": {}, "arms": {}}
    for part in ("train", "dev", "test"):
        plan["partitions"][part] = {"subjects": [part], "sequence_ids": [part],
                                     "sequence_sha256": [digest(part)]}
    for axis in ERROR_AXES:
        plan["numerical_qualification"][axis] = {"budget": 1e-4, "observed": 1e-6}
    readouts = {"call_only": ["call"], "risk_only": ["risk"], "dual": ["call", "risk"],
                "content_only": [], "plain_dual_gate": []}
    for arm in ARMS:
        plan["arms"][arm] = {"implementation_sha256": digest(arm), "parameters": 100,
                             "content_width": 8, "frontend_sha256": digest("frontend"),
                             "search_space_sha256": digest("search"),
                             "physical_readouts": readouts.get(arm, [])}
    runs = []
    for arm in ARMS:
        for seed in plan["training_seeds"]:
            identity = f"{arm}/{seed}"
            runs.append({"arm": arm, "training_seed": seed, "run_id": identity,
                         "independent_unit": "training_run", "status": "completed",
                         "checkpoint_sha256": digest(identity + "checkpoint"),
                         "initialization_sha256": digest(identity + "init"),
                         "implementation_sha256": digest(arm), "split_sha256": digest("splits"),
                         "frontend_sha256": digest("frontend"), "device": "cpu",
                         "measurement_context_sha256": digest("cpu"),
                         "execution_receipt_sha256": digest(identity + "receipt"),
                         "quality": {"macro_f1": .5, "brier": .1, "ece": .2},
                         "tuning_trials_charged": 1,
                         "cost_seconds": dict.fromkeys(COST_PARTS, 1) | {"total": 6, "ledger_complete": True},
                         "metrics": {k: {"value": 1, "status": "measured",
                                         "scope": ENERGY_SCOPE if k == "energy_joules" else "fixture"}
                                     for k in METRICS}})
    return plan, runs


class BenchmarkAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.runs = fixture()

    def test_complete_fixture_is_consistent_without_training(self):
        self.assertEqual(validate_plan(self.plan), [])
        self.assertTrue(validate_results(self.plan, self.runs)["efficiency_eligible"])

    def test_each_group_leakage_axis_is_rejected(self):
        for field in ("subjects", "sequence_ids", "sequence_sha256"):
            plan = copy.deepcopy(self.plan)
            plan["partitions"]["test"][field] = plan["partitions"]["train"][field]
            self.assertIn(f"leakage across {field}", validate_plan(plan))

    def test_test_selection_and_training_fitted_frontend_are_required(self):
        self.plan["test_used_for_selection"] = True
        self.plan["frontend"]["fit_partition"] = "train+test"
        self.assertGreaterEqual(len(validate_plan(self.plan)), 2)

    def test_gap_and_unclosed_error_block_real_task_entry(self):
        self.plan["max_gap_seconds"] = .101
        self.plan["numerical_qualification"]["tail"]["observed"] = .01
        errors = validate_plan(self.plan)
        self.assertIn("gap exceeds qualified single step", errors)
        self.assertIn("unclosed numerical error: tail", errors)

    def test_content_only_cannot_retain_active_physical_bypass(self):
        self.plan["arms"]["content_only"]["physical_readouts"] = ["active"]
        self.assertIn("physical bypass mismatch: content_only", validate_plan(self.plan))

    def test_plain_gate_capacity_is_checked(self):
        self.plan["arms"]["plain_dual_gate"]["parameters"] = 50
        self.assertTrue(any("ordinary dual gate" in e for e in validate_plan(self.plan)))

    def test_reused_checkpoint_is_not_an_independent_training_seed(self):
        self.runs[1]["checkpoint_sha256"] = self.runs[0]["checkpoint_sha256"]
        self.runs[1]["episodes"] = 10000
        self.assertFalse(validate_results(self.plan, self.runs)["quality_eligible"])

    def test_episodes_cannot_replace_training_runs(self):
        self.runs[0]["independent_unit"] = "episode"
        self.assertFalse(validate_results(self.plan, self.runs)["quality_eligible"])

    def test_unknown_energy_is_explicit_and_never_an_efficiency_win(self):
        self.runs[0]["metrics"]["energy_joules"] = {"value": None, "status": "unknown", "reason": "no meter"}
        report = validate_results(self.plan, self.runs)
        self.assertTrue(report["quality_eligible"])
        self.assertFalse(report["efficiency_eligible"])

    def test_zero_filled_energy_and_unknown_compute_are_rejected(self):
        self.runs[0]["metrics"]["energy_joules"]["value"] = 0
        self.runs[0]["cost_seconds"]["tuning"] = None
        self.assertFalse(validate_results(self.plan, self.runs)["contract_valid"])

    def test_budget_is_aggregate_over_seeds_and_failed_attempts(self):
        self.plan["budget"]["per_arm_wall_seconds"] = 10
        self.assertIn("aggregate compute budget exceeded or unknown",
                      validate_results(self.plan, self.runs)["errors"])

    def test_missing_baseline_or_unmatched_measurement_conditions_reject(self):
        self.runs.pop()
        self.runs[0]["measurement_context_sha256"] = digest("different-hardware")
        self.assertFalse(validate_results(self.plan, self.runs)["quality_eligible"])


if __name__ == "__main__":
    unittest.main()
