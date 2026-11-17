"""Accounting and paired-outcome regression tests; no model execution."""

import copy
import unittest

from .circuit_readiness_v3 import bound_panel
from .data import digest
from .source_metrics_v3 import (
    adoption_metrics,
    resource_ledger,
    retention_metrics,
    source_growth_metrics,
    upstream_cost_events,
)
from .test_circuit_readiness_v3 import MODELS, measured_material, readiness


class SourceMetricsTests(unittest.TestCase):
    def test_bound_execution_counts_do_not_turn_failed_calls_into_experience(self):
        data = measured_material([[False] * 3 for _ in MODELS], failed_original=True)
        receipt = readiness(data)["receipt"]
        result = source_growth_metrics(data[1], readiness=receipt)
        setting = next(
            row for row in result["settings"] if row["status"] == "READY_FOR_DIAGNOSTIC"
        )
        self.assertEqual(setting["recorded_verifier_execution_clusters"], 3)
        self.assertEqual(setting["recorded_completed_subject_call_clusters"], 0)
        self.assertEqual(setting["recorded_business_success_clusters"], 0)
        self.assertIsNone(setting["actual_executed_experience_clusters"])
        self.assertIsNone(setting["statistical_effective_sample_size"])

    def test_source_replays_do_not_supply_four_source_groups(self):
        _, rows, _ = measured_material()
        rows[1]["observation_digest"] = rows[0]["observation_digest"]
        result = source_growth_metrics(rows, unit_field="source_id")
        self.assertEqual(result["available_groups"], 2)
        self.assertEqual(
            sum(
                setting["status"] == "READY_FOR_DIAGNOSTIC"
                for setting in result["settings"]
            ),
            2,
        )
        self.assertEqual(
            sum(setting["status"] == "BLOCKED" for setting in result["settings"]), 6
        )
        self.assertIsNone(result["user_population_size"])
        self.assertTrue(
            all(
                setting["adoption_rate"] is None and setting["forgetting"] is None
                for setting in result["settings"]
            )
        )

    def test_missing_execution_meters_do_not_become_zero_source_experience(self):
        data = measured_material()
        for evaluation in data[2]:
            for row in evaluation["rows"]:
                step = row["steps"][0]
                verification = step["verification"]
                del verification["result"]["result"]["observations"]
                verification["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in verification.items()
                        if key not in ("success", "receipt_sha256")
                    }
                )
                del step["execution_summary"]
                step["receipt_sha256"] = digest(
                    {
                        key: value
                        for key, value in step.items()
                        if key != "receipt_sha256"
                    }
                )
        result = source_growth_metrics(data[1], readiness=readiness(data)["receipt"])
        setting = next(
            row for row in result["settings"] if row["status"] == "READY_FOR_DIAGNOSTIC"
        )
        self.assertIsNone(setting["recorded_completed_subject_call_clusters"])
        self.assertIsNone(setting["recorded_business_success_clusters"])
        self.assertEqual(
            setting["recorded_completed_subject_call_clusters_unknown_clusters"], 3
        )
        self.assertIsNone(
            setting[
                "recorded_completed_subject_call_clusters_observed_positive_subtotal"
            ]
        )

    def test_shared_evaluations_are_counted_once_and_missing_costs_stay_unknown(self):
        records, _, evaluations = measured_material()
        _, upstream, _ = bound_panel(records, evaluations, MODELS, digest(records))
        events = upstream_cost_events([{"upstream_evaluations": upstream}] * 7)
        result = resource_ledger(events)
        self.assertEqual(result["unique_execution_receipts"], 3)
        self.assertEqual(result["duplicate_references"], 18)
        metrics = result["components"]["model_inference"]["metrics"]
        self.assertEqual(metrics["model_calls"]["recorded_sum"], 9)
        self.assertIsNone(metrics["energy_joules"]["recorded_sum"])
        self.assertIsNone(result["full_system_cost"])
        self.assertIsNone(
            result["components"]["recovery"]["metrics"]["cpu_seconds"]["recorded_sum"]
        )
        bad = copy.deepcopy(events[0])
        bad["cost"]["model_calls"] += 1
        with self.assertRaisesRegex(ValueError, "conflicting cost"):
            resource_ledger([events[0], bad])

    def test_unfinished_decisions_and_wrong_used_model_cannot_look_adopted(self):
        _, _, evaluations = measured_material()
        step = evaluations[0]["rows"][0]["steps"][0]
        report = {
            "schema": "hepta.e6.result.v1",
            "evidence_binding": "d" * 64,
            "status": "NO_UPDATE",
            "model_decision": "NO_UPDATE",
            "selected_model_digest": MODELS[0],
            "C": [
                {
                    "task_id": "c0",
                    "prediction": copy.deepcopy(step["output"]),
                    "outcome": step["verification"],
                }
            ],
            "cold": {
                "pid": 11,
                "ppid": 12,
                "selected_model_digest": MODELS[0],
                "prediction": copy.deepcopy(step["output"]),
            },
        }
        result = adoption_metrics([report, copy.deepcopy(report)])
        self.assertEqual(result["opportunity_count"], 1)
        self.assertEqual(result["experiment_adopt_decision_rate"], 0)
        self.assertEqual(result["same_candidate_use_count"], 0)
        self.assertIsNone(result["native_adoption_rate"])
        unfinished = copy.deepcopy(report)
        unfinished["status"] = "INCOMPLETE"
        self.assertIsNone(
            adoption_metrics([unfinished])["experiment_adopt_decision_rate"]
        )
        bad_cold = copy.deepcopy(report)
        bad_cold["cold"]["prediction"]["answer"] = "different retained behavior"
        with self.assertRaisesRegex(ValueError, "cold prediction differs"):
            adoption_metrics([bad_cold])
        report["C"][0]["prediction"]["loaded_model_digest"] = MODELS[1]
        with self.assertRaisesRegex(ValueError, "different selected model"):
            adoption_metrics([report])

    def test_zero_prior_success_does_not_prove_absence_of_forgetting(self):
        records, _, evaluations = measured_material([[False] * 3 for _ in MODELS])
        bound, _, _ = bound_panel(records, evaluations, MODELS, digest(records))
        before = {
            "panel_role": "retention",
            "panel_digest": digest(records),
            "model_digest": MODELS[0],
            "rows": list(bound[0].values()),
        }
        after = {**before, "model_digest": MODELS[1], "rows": list(bound[1].values())}
        result = retention_metrics(
            before,
            after,
            expected_before_digest=digest(before),
            expected_after_digest=digest(after),
            expected_panel_digest=digest(records),
        )
        self.assertEqual(result["previously_successful_tasks"], 0)
        self.assertEqual(result["task_success_rate_change"], 0)
        self.assertIsNone(result["regression_rate_among_previously_successful"])

    def test_retention_preserves_domain_regressions_even_when_mean_is_unchanged(self):
        records, _, evaluations = measured_material()
        bound, _, _ = bound_panel(records, evaluations, MODELS, digest(records))
        before = {
            "panel_role": "retention",
            "panel_digest": digest(records),
            "model_digest": MODELS[0],
            "rows": list(bound[0].values()),
        }
        after = {**before, "model_digest": MODELS[1], "rows": list(bound[1].values())}
        result = retention_metrics(
            before,
            after,
            expected_before_digest=digest(before),
            expected_after_digest=digest(after),
            expected_panel_digest=digest(records),
        )
        self.assertEqual(result["task_success_rate_change"], 0)
        self.assertEqual(result["regression_rate_among_previously_successful"], 1)
        self.assertEqual(result["lost_tasks"], ["task-0"])
        self.assertEqual(result["gained_tasks"], ["task-1"])
        after["panel_role"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "predeclared retention"):
            retention_metrics(
                before,
                after,
                expected_before_digest=digest(before),
                expected_after_digest=digest(after),
                expected_panel_digest=digest(records),
            )


if __name__ == "__main__":
    unittest.main()
