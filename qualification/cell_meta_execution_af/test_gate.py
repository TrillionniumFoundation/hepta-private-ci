"""Adversarial synthetic tests: source conformance, never host/effect acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from qualification.cell_meta_execution_af import gate


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def synth() -> dict:
    meta = {
        "source_sha": "1" * 40, "source_tree": "2" * 40,
        "objective_sha256": sha("objective"), "no_change_sha256": sha("unchanged"),
        "budget_sha256": sha("budget"), "source_dataset_sha256": sha("source"),
        "train_task_families": ["training-family-alpha", "training-family-beta"],
        "protected_slices": ["legacy-code", "legacy-retrieval"],
        "independent_snapshots": [sha("baseline-snapshot-1"), sha("baseline-snapshot-2"), sha("baseline-snapshot-3")],
        "generator_id": "proposal-generator", "outcome_observer_id": "sealed-observer",
        "evaluator_id": "independent-evaluator", "selector_id": "independent-selector",
        "executor_id": "bounded-executor", "train_cutoff": "2026-09-30T00:00:00Z",
        "frozen_at": "2026-10-01T00:00:00Z",
        "future_windows": {
            "future_1": {"start": "2026-10-02T00:00:00Z", "end": "2026-10-03T00:00:00Z"},
            "future_2": {"start": "2026-10-04T00:00:00Z", "end": "2026-10-05T00:00:00Z"},
        },
    }
    result = {"schema": gate.SCHEMA, "candidate": meta, "studies": {}}
    for study, arms in gate.ARMS.items():
        rows = []
        for arm in arms:
            better = arm in gate.CONTRASTS[study]
            for window in ("future_1", "future_2"):
                u = 1.4 if better else 1.0
                rows.append({
                    "arm": arm, "window": window,
                    **({"heldout_task_families": ["novel-family-1" if window == "future_1" else "novel-family-2"]}
                       if study == "D" else {}),
                    **({"fixed_circuit_graph_sha256": sha("immutable-circuit-graph"),
                        "routing_policy_sha256": sha("route-policy-" + arm),
                        "actual_route_trace_sha256": sha(f"{arm}/{window}/actual-route"),
                        "sequential_cell_depth": 2 if arm == "fixed_graph" else 3}
                       if study == "C" else {}),
                    "task_set_sha256": sha(f"{study}/{window}/paired-input"),
                    "prediction_sha256": sha(f"{study}/{window}/{arm}/pre-label"),
                    "outcome_receipt_sha256": sha(f"{study}/{window}/{arm}/finalized"),
                    "evaluation_receipt_sha256": sha(f"{study}/{window}/{arm}/evaluated"),
                    "model_bundle_sha256": sha(f"{study}/{arm}/bundle"),
                    "model_bundle_frozen_at": "2026-10-01T00:00:00Z",
                    "independent_episodes": 600, "effective_sample_size": 450.0,
                    "predictions_committed_at": "2026-10-02T12:00:00Z" if window == "future_1" else "2026-10-04T12:00:00Z",
                    "outcomes_finalized_at": "2026-10-03T12:00:00Z" if window == "future_1" else "2026-10-05T12:00:00Z",
                    "metrics": {
                        "net_utility_lcb": u, "net_utility_ucb": u + 0.1,
                        "brier": 0.19 if better else 0.24,
                        "ece": 0.03 if better else 0.07,
                        "ood_false_accept": 0.04 if better else 0.08,
                        "negative_transfer_rate": 0.02 if better else 0.05,
                        "old_task_degradation": 0.01 if better else 0.0,
                        "protected_slice_degradation": {
                            "legacy-code": 0.01 if better else 0.0,
                            "legacy-retrieval": 0.0,
                        },
                        "real_model_invocations": 600,
                        "training_bytes": 4096 if better else 0,
                        "inference_bytes": 8192,
                    },
                })
        result["studies"][study] = {
            "budget_sha256": meta["budget_sha256"], "interval_alpha": 0.003,
            "objective_sha256": meta["objective_sha256"], "records": rows,
        }
    resource_rows = []
    for mode in gate.DEPLOYMENTS:
        for scale in gate.SCALES:
            for load in gate.LOADS:
                resource_rows.append({
                    "mode": mode, "logical_cells": scale, "load_profile": load,
                    "host_id": "benchmark-host", "runtime_profile_sha256": sha("runtime"),
                    "device_profile_sha256": sha("device"),
                    "attempt_trace_sha256": sha(f"{scale}|{load}|attempted-requests"),
                    "terminal_receipt_sha256": sha(f"{mode}/{scale}/{load}/terminal"),
                    "active_concurrency": 8 if load == "fixed_active" else scale // 4,
                    "observed_peak_active_requests": 8 if load == "fixed_active" else scale // 4,
                    "observed_peak_inflight_backend_calls": 1,
                    "attempted": 1000, "completed": 990, "failed": 5, "rejected": 5,
                    "backend_calls": 1000, "native_batch_requests": 990,
                    "rss_peak_bytes": 100_000_000, "gpu_peak_bytes": 0,
                    "network_bytes": 50_000, "fsync_count": 8, "replayed_effects": 0,
                    "p50_ms": 4.0, "p95_ms": 8.0, "p99_ms": 12.0,
                    "cpu_seconds": 24.0, "elapsed_seconds": 32.0,
                    "queue_p99_ms": 3.0, "lock_wait_ms": 2.0,
                    "cas_p99_ms": 1.0, "signature_p99_ms": 1.0,
                    "cns_p99_ms": 1.0, "recovery_ms": 100.0,
                    "real_worker_executed": True, "crash_recovery_tested": True,
                })
    result["resources"] = {
        "host_id": "benchmark-host", "device_profile_sha256": sha("device"),
        "runtime_profile_sha256": sha("runtime"), "runs": resource_rows,
    }
    codex_rows = []
    for route in gate.ROUTES:
        for task in ("shell-task", "refactor-task"):
            for case in gate.CASES:
                allowed = case == "allowed"
                direct = route == "direct_effect"
                codex_rows.append({
                    "route": route, "task_id": task, "case": case,
                    "host_id": "benchmark-host", "device_profile_sha256": sha("device"),
                    "task_input_sha256": sha(task + "/same-input"),
                    "policy_sha256": sha("bound-policy-" + case),
                    "terminal_observation_sha256": sha(f"{route}/{task}/{case}/terminal"),
                    "sandbox_sha256": sha("same-sandbox"),
                    "status": "succeeded" if allowed else "rejected",
                    "authorized": allowed, "external_effect_observed": allowed,
                    "effect_owner_receipt_sha256": sha(f"{route}/{task}/owner") if allowed else None,
                    "tool_attempts": 1, "model_calls": 0 if direct else 1,
                    "token_count": 0 if direct else 100,
                    "provider_direct_effect_attempts": 0,
                    "effect_gateway_attempts": 1,
                    "agent_planner_invocations": 1 if route == "full_codex_agent" else 0,
                    "original_owner_readbacks": 1,
                    "execution_path_sha256": sha("execution-binary/" + route),
                    "effect_gateway_binary_sha256": sha("shared-effect-gateway"),
                    "original_effect_owner_id": "fixed-owner/" + task,
                    "negative_effect_owner_readback_sha256": sha(f"{route}/{task}/{case}/negative") if not allowed else None,
                    "rss_peak_bytes": 2_000_000, "cpu_seconds": 1.0,
                    "elapsed_seconds": 2.0, "task_quality": 1.0 if allowed else 0.0,
                    "total_cost": 0.03 if allowed else 0.0,
                    "real_invocation_observed": True,
                })
    result["codex"] = {
        "host_id": "benchmark-host", "task_suite_sha256": sha("task-suite"),
        "device_profile_sha256": sha("device"),
        "task_ids": ["shell-task", "refactor-task"], "runs": codex_rows,
    }
    result["split_safety"] = {
        "coordinator_ledger": {
            "coordinator_id": "cell-split-coordinator",
            "prepared_intent_sha256": sha("durable-ledger-prepared"),
            "committed_receipt_sha256": sha("durable-ledger-committed"),
            "synced_prefix_sha256": sha("durable-ledger-synced"),
            "recovered_frontier_sha256": sha("durable-ledger-recovered"),
            "single_writer_fenced": True,
        },
        "no_change_sha256": meta["no_change_sha256"],
        "split_plan_sha256": sha("split-plan"),
        "split_operation_id": "split-operation-alpha",
        "scope_id": "scope-alpha",
        "source_generation": 7,
        "target_generation": 8,
        "effects": [
            {"phase": p, "original_owner_id": "owner-" + p,
             "split_plan_sha256": sha("split-plan"), "split_operation_id": "split-operation-alpha",
             "scope_id": "scope-alpha", "source_generation": 7, "target_generation": 8,
             "ledger_step_index": index + 1,
             "predecessor_receipt_sha256": sha(gate.PHASES[index-1] + "signed") if index else None,
             "terminal": "committed", "generation_fenced": True,
             "signed_receipt_sha256": sha(p + "signed"),
             "signed_readback_sha256": sha(p + "readback"),
             "independent_witness_sha256": sha(p + "witness")}
            for index, p in enumerate(gate.PHASES)
        ],
        "restarts": [
            {"case": kind, "no_duplicate_effect": True,
             "readback_reconciled": True,
             "observer_receipt_sha256": sha(kind + "observed")}
            for kind in gate.CRASH_CASES
        ],
        "independent_final_use": True, "selector_current_after_last_readback": True,
    }
    return result


def check_bad(case: dict, field: str, reason: str = "") -> dict:
    report = gate.verify(case)
    val = report["gates"][field]
    if val["status"] != "blocked":
        raise AssertionError(f"expected {field} to block, got {val}")
    if reason and reason not in val["reason"]:
        raise AssertionError(f"wanted {reason!r} in {val['reason']!r}")
    assert report["authority_posture"] == "DENY_ALL"
    assert report["physical_split_permitted"] is False
    return report


class AfEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.d = synth()

    def test_complete_synthetic_envelope_is_never_authority(self):
        r = gate.verify(self.d)
        self.assertEqual(r["status"], "shadow_structural_review_only")
        self.assertFalse(r["physical_split_permitted"])
        self.assertFalse(r["production_selection_permitted"])
        self.assertEqual(r["authority_posture"], "DENY_ALL")
        self.assertEqual(r["gates"]["E"]["run_count"], 24)
        self.assertEqual(r["gates"]["F"]["run_count"], 12)
        self.assertEqual(r["gates"]["A"]["provisional_gain_arms"], ["learning_head"])

    def test_missing_experiment_cannot_hide_behind_other_passes(self):
        del self.d["studies"]["D"]
        check_bad(self.d, "D", "missing D")

    def test_duplicate_arm_blocked(self):
        self.d["studies"]["A"]["records"].append(copy.deepcopy(self.d["studies"]["A"]["records"][0]))
        check_bad(self.d, "A", "duplicate")

    def test_missing_no_change_baseline_blocked(self):
        self.d["studies"]["A"]["records"] = [x for x in self.d["studies"]["A"]["records"] if x["arm"] != "no_change"]
        check_bad(self.d, "A", "missing")

    def test_unregistered_extra_arm_blocked(self):
        item = copy.deepcopy(self.d["studies"]["A"]["records"][0]); item["arm"] = "made_up"
        self.d["studies"]["A"]["records"].append(item)
        check_bad(self.d, "A", "unregistered")

    def test_future_task_drift_blocked(self):
        self.d["studies"]["B"]["records"][0]["task_set_sha256"] = sha("unmatched")
        check_bad(self.d, "B", "unpaired")

    def test_reused_future_windows_blocked(self):
        for row in self.d["studies"]["C"]["records"]:
            row["task_set_sha256"] = sha("same")
        check_bad(self.d, "C", "reused")

    def test_prediction_after_labels_blocked(self):
        self.d["studies"]["A"]["records"][0]["predictions_committed_at"] = "2026-10-06T00:00:00Z"
        check_bad(self.d, "A", "post-label")

    def test_unfrozen_future_baseline_blocked(self):
        self.d["candidate"]["frozen_at"] = "2026-10-04T00:00:00Z"
        check_bad(self.d, "identity", "chronology")

    def test_budget_mismatch_blocked(self):
        self.d["studies"]["D"]["budget_sha256"] = sha("looser")
        check_bad(self.d, "D", "unfair budget")

    def test_utility_interval_inversion_blocked(self):
        self.d["studies"]["B"]["records"][0]["metrics"]["net_utility_lcb"] = 100.0
        check_bad(self.d, "B", "inverted utility")

    def test_second_future_window_regression_keeps_efficacy_unproven(self):
        for row in self.d["studies"]["A"]["records"]:
            if row["arm"] == "learning_head" and row["window"] == "future_2":
                row["metrics"]["net_utility_lcb"] = 0.5
                row["metrics"]["net_utility_ucb"] = 0.6
        report = gate.verify(self.d)
        self.assertEqual(report["gates"]["A"]["provisional_gain_arms"], [])
        self.assertFalse(report["production_selection_permitted"])

    def test_old_task_regression_vetoes_positive_utility(self):
        for row in self.d["studies"]["B"]["records"]:
            if row["arm"] == "child_heads":
                row["metrics"]["old_task_degradation"] = 0.03
        self.assertEqual(gate.verify(self.d)["gates"]["B"]["provisional_gain_arms"], [])

    def test_calibration_regression_vetoes_positive_utility(self):
        for row in self.d["studies"]["D"]["records"]:
            if row["arm"] == "learned_rule":
                row["metrics"]["ece"] = 0.20
        self.assertEqual(gate.verify(self.d)["gates"]["D"]["provisional_gain_arms"], [])

    def test_fake_source_digest_blocked(self):
        self.d["candidate"]["source_sha"] = "abc"
        check_bad(self.d, "identity", "Git SHA")

    def test_self_signed_observer_blocked(self):
        self.d["candidate"]["outcome_observer_id"] = self.d["candidate"]["generator_id"]
        check_bad(self.d, "identity", "must differ")

    def test_missing_4096_physical_result_blocked(self):
        self.d["resources"]["runs"] = [r for r in self.d["resources"]["runs"] if not (r["logical_cells"] == 4096 and r["mode"] == "shared_worker")]
        check_bad(self.d, "E", "missing")

    def test_fixed_concurrency_drift_blocked(self):
        self.d["resources"]["runs"][0]["active_concurrency"] = 4
        self.d["resources"]["runs"][0]["observed_peak_active_requests"] = 4
        check_bad(self.d, "E", "unmatched")

    def test_resource_attempt_accounting_blocked(self):
        self.d["resources"]["runs"][0]["completed"] += 1
        check_bad(self.d, "E", "accounting")

    def test_impossible_batch_efficiency_blocked(self):
        self.d["resources"]["runs"][0]["backend_calls"] = 0
        check_bad(self.d, "E", "batch accounting")

    def test_source_only_cpu_fixture_not_physical_measurement(self):
        self.d["resources"]["runs"][0]["real_worker_executed"] = False
        check_bad(self.d, "E", "source-only")

    def test_resource_cross_host_mismatch(self):
        self.d["resources"]["runs"][0]["host_id"] = "other-host"
        check_bad(self.d, "E", "host drift")

    def test_resource_trace_mismatch(self):
        self.d["resources"]["runs"][0]["attempt_trace_sha256"] = sha("different")
        check_bad(self.d, "E", "unmatched")

    def test_codex_denied_effect_leak_blocked(self):
        self.d["codex"]["runs"][1]["external_effect_observed"] = True
        check_bad(self.d, "F", "denied action leaked")

    def test_codex_app_server_success_not_effect_receipt(self):
        item = next(x for x in self.d["codex"]["runs"] if x["route"] == "app_server_provider" and x["case"] == "allowed")
        item["effect_owner_receipt_sha256"] = None
        check_bad(self.d, "F", "SHA256")

    def test_direct_tool_cannot_hide_model_calls(self):
        item = next(x for x in self.d["codex"]["runs"] if x["route"] == "direct_effect")
        item["model_calls"] = 1
        check_bad(self.d, "F", "conceal")

    def test_codex_unpaired_task_blocked(self):
        self.d["codex"]["runs"][0]["task_input_sha256"] = sha("different-task")
        check_bad(self.d, "F", "unmatched task")

    def test_codex_failed_outcome_is_not_success(self):
        r = self.d["codex"]["runs"][0]
        r["status"] = "failed"; r["external_effect_observed"] = False
        r["effect_owner_receipt_sha256"] = None
        r["negative_effect_owner_readback_sha256"] = sha("signed-owner-negative-readback")
        report = gate.verify(self.d)
        self.assertEqual(report["gates"]["F"]["status"], "codex_path_comparison_structurally_complete")
        self.assertEqual(report["gates"]["F"]["observed_successes"]["full_codex_agent"], 1)

    def test_split_missing_original_owner_receipt(self):
        self.d["split_safety"]["effects"][0]["signed_readback_sha256"] = None
        check_bad(self.d, "split_safety", "SHA256")

    def test_split_ledger_generation_fence_mandatory(self):
        self.d["split_safety"]["coordinator_ledger"]["single_writer_fenced"] = False
        check_bad(self.d, "split_safety", "ledger owner fence")

    def test_low_independent_ess_is_not_qualified(self):
        self.d["studies"]["A"]["records"][0]["effective_sample_size"] = 399.0
        check_bad(self.d, "A", "ESS/support")

    def test_variable_concurrency_out_of_order_is_invalid(self):
        for r in self.d["resources"]["runs"]:
            if r["logical_cells"] == 4096 and r["load_profile"] == "vary_active":
                r["active_concurrency"] = 10
                r["observed_peak_active_requests"] = 10
        check_bad(self.d, "E", "must increase")

    def test_hidden_protected_slice_regression_vetoes_gain(self):
        for row in self.d["studies"]["A"]["records"]:
            if row["arm"] == "learning_head":
                row["metrics"]["protected_slice_degradation"]["legacy-retrieval"] = 0.11
        self.assertEqual(gate.verify(self.d)["gates"]["A"]["provisional_gain_arms"], [])

    def test_missing_protected_slice_is_not_an_aggregate_success(self):
        del self.d["studies"]["B"]["records"][0]["metrics"]["protected_slice_degradation"]["legacy-code"]
        check_bad(self.d, "B", "protected slices")

    def test_uncorrected_confidence_level_rejected(self):
        self.d["studies"]["C"]["interval_alpha"] = 0.05
        check_bad(self.d, "C", "multiple-testing")

    def test_independent_snapshot_count_below_three_rejected(self):
        self.d["candidate"]["independent_snapshots"] = self.d["candidate"]["independent_snapshots"][:2]
        check_bad(self.d, "identity", "at least three")

    def test_meta_learning_train_family_leakage_rejected(self):
        for r in self.d["studies"]["D"]["records"]:
            r["heldout_task_families"] = ["training-family-alpha"]
        check_bad(self.d, "D", "train/test overlap")

    def test_meta_learning_future_family_reuse_rejected(self):
        for r in self.d["studies"]["D"]["records"]:
            r["heldout_task_families"] = ["same-unseen-family"]
        check_bad(self.d, "D", "reused between")

    def test_meta_learned_router_cannot_hide_graph_change(self):
        row = next(r for r in self.d["studies"]["C"]["records"] if r["arm"] == "learned_router")
        row["fixed_circuit_graph_sha256"] = sha("different-graph")
        check_bad(self.d, "C", "changed graph")

    def test_meta_fixed_and_learned_policy_identity_must_differ(self):
        for r in self.d["studies"]["C"]["records"]:
            if r["arm"] == "learned_router":
                r["routing_policy_sha256"] = sha("route-policy-fixed_graph")
        check_bad(self.d, "C", "indistinguishable")

    def test_non_object_input_denied_without_crash(self):
        r = gate.verify(["not-an-evidence-object"])
        self.assertEqual(r["gates"]["identity"]["status"], "blocked")
        self.assertFalse(r["physical_split_permitted"])

    def test_unhashable_protected_slice_denied_without_crash(self):
        self.d["candidate"]["protected_slices"] = [["unhashable"]]
        check_bad(self.d, "identity")

    def test_unhashable_snapshot_denied_without_crash(self):
        self.d["candidate"]["independent_snapshots"] = [["unhashable"]]
        check_bad(self.d, "identity")

    def test_huge_numeric_measurement_denied_without_crash(self):
        self.d["studies"]["A"]["records"][0]["effective_sample_size"] = 10 ** 1000
        check_bad(self.d, "A", "finite number")

    def test_split_late_selector_withdrawal_blocked(self):
        self.d["split_safety"]["selector_current_after_last_readback"] = False
        check_bad(self.d, "split_safety", "selector")

    def test_split_restart_duplicate_effect_blocked(self):
        self.d["split_safety"]["restarts"][1]["no_duplicate_effect"] = False
        check_bad(self.d, "split_safety", "recovery")


    def test_model_bundle_replaced_between_future_windows_blocked(self):
        target = next(r for r in self.d["studies"]["A"]["records"]
                      if r["arm"] == "learning_head" and r["window"] == "future_2")
        target["model_bundle_sha256"] = sha("post-future-1-model")
        check_bad(self.d, "A", "bundle changed")

    def test_model_bundle_frozen_after_future_outcomes_blocked(self):
        target = self.d["studies"]["D"]["records"][0]
        target["model_bundle_frozen_at"] = "2026-10-04T00:00:00Z"
        check_bad(self.d, "D", "not frozen")

    def test_codex_failed_unauthorized_effect_blocked(self):
        row = next(r for r in self.d["codex"]["runs"]
                   if r["route"] == "full_codex_agent" and r["case"] == "allowed")
        row["status"] = "failed"
        row["authorized"] = False
        check_bad(self.d, "F", "unauthorized external effect")

    def test_codex_indeterminate_unauthorized_effect_blocked(self):
        row = next(r for r in self.d["codex"]["runs"]
                   if r["route"] == "app_server_provider" and r["case"] == "allowed")
        row["status"] = "indeterminate"
        row["authorized"] = False
        check_bad(self.d, "F", "unauthorized external effect")

    def test_codex_orphan_owner_receipt_blocked(self):
        row = next(r for r in self.d["codex"]["runs"]
                   if r["route"] == "full_codex_agent" and r["case"] == "allowed")
        row["status"] = "failed"
        row["external_effect_observed"] = False
        check_bad(self.d, "F", "receipt without observed effect")

    def test_codex_truthy_nonboolean_flag_blocked(self):
        row = next(r for r in self.d["codex"]["runs"]
                   if r["route"] == "app_server_provider" and r["case"] == "allowed")
        row["status"] = "failed"
        row["authorized"] = "false"
        row["external_effect_observed"] = False
        row["effect_owner_receipt_sha256"] = None
        check_bad(self.d, "F", "malformed authorization")

    def test_E_same_host_changed_device_profile_blocked(self):
        self.d["resources"]["runs"][0]["device_profile_sha256"] = sha("different-device")
        check_bad(self.d, "E", "device profile drift")

    def test_F_different_device_profile_blocked(self):
        self.d["codex"]["device_profile_sha256"] = sha("different-device")
        check_bad(self.d, "F", "does not match E")

    def test_paired_placement_deltas_do_not_select_a_winner(self):
        for r in self.d["resources"]["runs"]:
            if r["mode"] == "per_cell_process" and r["logical_cells"] == 4096 and r["load_profile"] == "fixed_active":
                r["p99_ms"] = 19.0
                r["rss_peak_bytes"] += 20_000_000
        report = gate.verify(self.d)
        diagnostics = report["gates"]["E"]["paired_placement_diagnostics"]
        self.assertEqual(diagnostics["per_cell_process/4096/fixed_active"]["p99_delta_ms"], 7.0)
        self.assertEqual(diagnostics["per_cell_process/4096/fixed_active"]["rss_delta_bytes"], 20_000_000)
        self.assertFalse(report["gates"]["E"]["placement_selection_authorized"])
        self.assertFalse(report["production_selection_permitted"])

    def test_F_route_costs_are_reported_without_codex_extraction_authority(self):
        result = gate.verify(self.d)["gates"]["F"]
        self.assertEqual(result["per_route_cost_diagnostics"]["full_codex_agent"]["allowed"]["tasks"], 2)
        self.assertEqual(result["per_route_cost_diagnostics"]["direct_effect"]["allowed"]["model_calls"], 0)
        self.assertEqual(result["per_route_cost_diagnostics"]["full_codex_agent"]["allowed"]["model_calls"], 2)
        self.assertFalse(result["codex_extraction_authorized"])

    def test_E_invalid_derived_throughput_fails_closed(self):
        self.d["resources"]["runs"][0]["elapsed_seconds"] = 5e-324
        check_bad(self.d, "E", "non-finite derived throughput")

    def test_F_overflowed_aggregate_cost_fails_closed(self):
        for row in self.d["codex"]["runs"]:
            if row["route"] == "full_codex_agent" and row["case"] == "allowed":
                row["total_cost"] = 1e308
        check_bad(self.d, "F", "non-finite aggregate total_cost")

    def test_missing_E_resources_blocks_F_without_crashing(self):
        del self.d["resources"]
        report = gate.verify(self.d)
        self.assertEqual(report["gates"]["E"]["status"], "blocked")
        self.assertEqual(report["gates"]["F"]["status"], "blocked")
        self.assertEqual(report["authority_posture"], "DENY_ALL")

    def test_F_row_device_profile_drift_blocked(self):
        self.d["codex"]["runs"][0]["device_profile_sha256"] = sha("new-gpu")
        check_bad(self.d, "F", "device profile drift")

    def test_indeterminate_codex_turn_requires_resolution(self):
        row = next(x for x in self.d["codex"]["runs"]
                   if x["route"] == "full_codex_agent" and x["case"] == "allowed")
        row["status"] = "indeterminate"
        check_bad(self.d, "F", "unresolved original-effect terminality")

    def test_failed_codex_without_negative_owner_readback_is_blocked(self):
        row = next(x for x in self.d["codex"]["runs"]
                   if x["route"] == "direct_effect" and x["case"] == "allowed")
        row["status"] = "failed"
        row["external_effect_observed"] = False
        row["effect_owner_receipt_sha256"] = None
        check_bad(self.d, "F", "negative_effect_owner_readback_sha256")

    def test_failed_codex_signed_negative_readback_is_not_a_success(self):
        row = next(x for x in self.d["codex"]["runs"]
                   if x["route"] == "direct_effect" and x["case"] == "allowed")
        row["status"] = "failed"
        row["external_effect_observed"] = False
        row["effect_owner_receipt_sha256"] = None
        row["negative_effect_owner_readback_sha256"] = sha("signed-negative")
        result = gate.verify(self.d)
        self.assertEqual(result["gates"]["F"]["status"], "codex_path_comparison_structurally_complete")
        self.assertEqual(result["gates"]["F"]["observed_successes"]["direct_effect"], 1)
        self.assertFalse(result["production_selection_permitted"])

    def test_unchanged_meta_router_behavior_cannot_claim_gain(self):
        fixed = {r["window"]: r["actual_route_trace_sha256"]
                 for r in self.d["studies"]["C"]["records"] if r["arm"] == "fixed_graph"}
        for r in self.d["studies"]["C"]["records"]:
            if r["arm"] == "learned_router":
                r["actual_route_trace_sha256"] = fixed[r["window"]]
        report = gate.verify(self.d)["gates"]["C"]
        self.assertNotIn("learned_router", report["provisional_gain_arms"])
        self.assertFalse(report["behavior_difference_observed"]["learned_router"])
        self.assertIn("adaptive_depth", report["provisional_gain_arms"])

    def test_unchanged_meta_depth_cannot_claim_adaptive_depth_gain(self):
        for r in self.d["studies"]["C"]["records"]:
            if r["arm"] == "adaptive_depth":
                r["sequential_cell_depth"] = 2
        report = gate.verify(self.d)["gates"]["C"]
        self.assertNotIn("adaptive_depth", report["provisional_gain_arms"])
        self.assertFalse(report["behavior_difference_observed"]["adaptive_depth"])

    def test_too_many_codex_classes_are_rejected_before_expansion(self):
        self.d["codex"]["task_ids"] = [f"task-{i:03}" for i in range(65)]
        check_bad(self.d, "F", "2..64 distinct")

    def test_excessive_protected_slices_are_rejected(self):
        self.d["candidate"]["protected_slices"] = [f"protected-{i:03}" for i in range(65)]
        check_bad(self.d, "identity", "protected slices")

    def test_duplicate_json_key_rejected_by_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "duplicate.json"
            out = Path(td) / "report.json"
            p.write_text('{"schema": "first", "schema": "second"}', encoding="utf-8")
            self.assertEqual(gate.main([str(p), "--out", str(out)]), 2)
            self.assertIn("duplicate JSON key", json.loads(out.read_text())["error"])

    def test_nonfinite_json_literal_rejected_by_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nonfinite.json"
            out = Path(td) / "report.json"
            p.write_text('{"schema": NaN}', encoding="utf-8")
            self.assertEqual(gate.main([str(p), "--out", str(out)]), 2)
            self.assertIn("non-finite JSON constant", json.loads(out.read_text())["error"])

    def test_large_external_json_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "huge.json"
            out = Path(td) / "report.json"
            p.write_bytes(b" " * (gate.MAX_INPUT_BYTES + 1))
            self.assertEqual(gate.main([str(p), "--out", str(out)]), 2)
            self.assertIn("exceeds size bound", json.loads(out.read_text())["error"])

    def test_non_file_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "report.json"
            self.assertEqual(gate.main([td, "--out", str(out)]), 2)
            self.assertIn("regular file", json.loads(out.read_text())["error"])

    def test_cross_arm_label_exposure_precedes_candidate_prediction(self):
        rows = self.d["studies"]["A"]["records"]
        baseline = next(x for x in rows if x["arm"] == "no_change" and x["window"] == "future_1")
        baseline["predictions_committed_at"] = "2026-10-02T01:00:00Z"
        baseline["outcomes_finalized_at"] = "2026-10-02T09:00:00Z"
        # Every arm still predicts before its OWN recorded outcome. Only a
        # cohort-wide prelabel barrier catches the later candidate predictions.
        check_bad(self.d, "A", "cross-arm label leakage")

    def test_paired_arms_can_predict_at_different_times_before_any_labels(self):
        baseline = next(x for x in self.d["studies"]["A"]["records"]
                        if x["arm"] == "no_change" and x["window"] == "future_1")
        baseline["predictions_committed_at"] = "2026-10-02T01:00:00Z"
        self.assertEqual(gate.verify(self.d)["gates"]["A"]["status"], "shadow_structurally_complete")

    def test_split_out_of_order_physical_effects_refused(self):
        entries = self.d["split_safety"]["effects"]
        entries[0], entries[1] = entries[1], entries[0]
        check_bad(self.d, "split_safety", "phase order")

    def test_split_predecessor_receipt_chain_mismatch_refused(self):
        self.d["split_safety"]["effects"][2]["predecessor_receipt_sha256"] = sha("other-owner")
        check_bad(self.d, "split_safety", "predecessor chain")

    def test_split_cross_scope_owner_receipt_refused(self):
        self.d["split_safety"]["effects"][1]["scope_id"] = "another-scope"
        check_bad(self.d, "split_safety", "binding drift")

    def test_split_mixed_target_generation_refused(self):
        self.d["split_safety"]["effects"][3]["target_generation"] = 9
        check_bad(self.d, "split_safety", "mixed source or target generation")

    def test_split_forged_duplicate_original_receipt_refused(self):
        first = self.d["split_safety"]["effects"][0]["signed_receipt_sha256"]
        self.d["split_safety"]["effects"][1]["signed_receipt_sha256"] = first
        check_bad(self.d, "split_safety", "duplicated original-owner")

    def test_split_wrong_coordinator_step_refused(self):
        self.d["split_safety"]["effects"][3]["ledger_step_index"] = 2
        check_bad(self.d, "split_safety", "ledger step index")

    def test_split_invalid_generation_transition_refused(self):
        self.d["split_safety"]["target_generation"] = 7
        check_bad(self.d, "split_safety", "must advance")

    def test_input_symlink_fails_closed(self):
        import os
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("kernel does not expose O_NOFOLLOW")
        with tempfile.TemporaryDirectory() as td:
            orig = Path(td) / "real.json"
            link = Path(td) / "alias.json"
            out = Path(td) / "report.json"
            orig.write_text(json.dumps(self.d))
            link.symlink_to(orig)
            self.assertEqual(gate.main([str(link), "--out", str(out)]), 2)
            self.assertFalse(json.loads(out.read_text())["physical_split_permitted"])

    def test_input_fifo_does_not_block(self):
        import os
        if not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"):
            self.skipTest("kernel does not support FIFO nonblocking reads")
        with tempfile.TemporaryDirectory() as td:
            fifo = Path(td) / "evidence.fifo"
            out = Path(td) / "report.json"
            os.mkfifo(fifo)
            self.assertEqual(gate.main([str(fifo), "--out", str(out)]), 2)
            self.assertIn("regular file", json.loads(out.read_text())["error"])

    def test_study_local_alpha_without_global_correction_rejected(self):
        self.d["studies"]["A"]["interval_alpha"] = 0.01
        check_bad(self.d, "A", "global A-D familywise")

    def test_all_studies_share_conservative_global_alpha_ceiling(self):
        result = gate.verify(self.d)
        for letter in gate.ARMS:
            study = result["gates"][letter]
            self.assertLessEqual(study["reported_interval_alpha"], study["familywise_alpha_ceiling"])
            self.assertEqual(study["familywise_alpha_ceiling"], 0.05 / (2 * 8))

    def test_full_E_matrix_with_zero_completed_is_not_a_benchmark(self):
        for r in self.d["resources"]["runs"]:
            r["completed"] = 0
            r["failed"] = r["attempted"] - r["rejected"]
            r["native_batch_requests"] = 0
            r["backend_calls"] = 0
        check_bad(self.d, "E", "no physically completed")

    def test_single_E_placement_cannot_claim_measurement_with_zero_completed(self):
        row = self.d["resources"]["runs"][0]
        row["completed"] = 0
        row["failed"] = row["attempted"] - row["rejected"]
        row["native_batch_requests"] = 0
        row["backend_calls"] = 0
        check_bad(self.d, "E", "no physically completed")


    def test_active_concurrency_must_be_physically_observed(self):
        self.d["resources"]["runs"][0]["observed_peak_active_requests"] = 1
        check_bad(self.d, "E", "requested concurrency was not physically observed")

    def test_impossible_inflight_backend_concurrency_rejected(self):
        self.d["resources"]["runs"][0]["observed_peak_inflight_backend_calls"] = 1001
        check_bad(self.d, "E", "impossible physically concurrent backend")

    def test_agent_tools_cannot_bypass_independent_effect_gateway(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "full_codex_agent")
        row["provider_direct_effect_attempts"] = 1
        row["tool_attempts"] = 2
        check_bad(self.d, "F", "outside independent gateway")

    def test_model_only_app_server_cannot_use_codex_agent_planner(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "app_server_provider")
        row["agent_planner_invocations"] = 1
        check_bad(self.d, "F", "non-Agent route invoked")

    def test_full_agent_must_actually_invoke_agent_planner(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "full_codex_agent")
        row["agent_planner_invocations"] = 0
        check_bad(self.d, "F", "no actual planner")

    def test_gateway_effect_accounting_cannot_hide_tool_attempts(self):
        row = self.d["codex"]["runs"][0]
        row["tool_attempts"] = 2
        check_bad(self.d, "F", "gateway tool accounting")

    def test_original_owner_negative_readback_mandatory_for_denied_action(self):
        row = next(r for r in self.d["codex"]["runs"] if r["case"] == "denied")
        row["negative_effect_owner_readback_sha256"] = None
        check_bad(self.d, "F", "SHA256")

    def test_original_effect_owner_must_match_across_routes(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "direct_effect")
        row["original_effect_owner_id"] = "unmatched-owner"
        check_bad(self.d, "F", "different original effect owners")

    def test_gateway_binary_must_match_across_execution_paths(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "full_codex_agent")
        row["effect_gateway_binary_sha256"] = sha("different-gateway")
        check_bad(self.d, "F", "gateway implementation changed")

    def test_claimed_codex_routes_must_have_distinct_executed_path_identities(self):
        for row in self.d["codex"]["runs"]:
            if row["route"] == "app_server_provider":
                row["execution_path_sha256"] = sha("execution-binary/full_codex_agent")
        check_bad(self.d, "F", "identical path identity")

    def test_codex_route_identity_must_remain_fixed_across_task_cases(self):
        row = next(r for r in self.d["codex"]["runs"] if r["route"] == "direct_effect")
        row["execution_path_sha256"] = sha("other-path")
        check_bad(self.d, "F", "identity changed")

    def test_codex_experimental_composition_remains_non_authorizing(self):
        report = gate.verify(self.d)
        self.assertEqual(report["status"], "shadow_structural_review_only")
        self.assertFalse(report["gates"]["E"]["placement_selection_authorized"])
        self.assertFalse(report["gates"]["F"]["codex_extraction_authorized"])
        self.assertFalse(report["production_selection_permitted"])

    def test_cli_missing_real_bundle_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "no-results.json"
            p.write_text(json.dumps({"schema": gate.SCHEMA, "candidate": self.d["candidate"]}))
            self.assertEqual(gate.main([str(p), "--out", str(Path(td) / "report.json")]), 2)

    def test_cli_synthetic_complete_never_authorizes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "fixture.json"
            out = Path(td) / "report.json"
            p.write_text(json.dumps(self.d))
            self.assertEqual(gate.main([str(p), "--out", str(out)]), 0)
            report = json.loads(out.read_text())
            self.assertEqual(report["authority_posture"], "DENY_ALL")
            self.assertFalse(report["production_selection_permitted"])


if __name__ == "__main__":
    unittest.main()
