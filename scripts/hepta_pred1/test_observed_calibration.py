"""Synthetic fixtures exercising missingness, action support and scope boundaries."""

from dataclasses import replace
import json
import unittest

from .contracts import Evidence
from .observed_calibration import MAX_OBSERVATIONS, summarize_offline_forecasts
from .observed_evaluation import (
    COST_FIELDS, ObservedDecision, UtilityContract, observed_to_dict,
    paired_adoption_gate, score_observed,
)

CONTRACT = UtilityContract("fixture-work", 0.1, 0.1, 10, 10)
FORECAST = {
    "success_probability": 0.8, "duration_values": [1],
    "duration_probabilities": [1], "cost_values": [2], "cost_probabilities": [1],
}


def decision(index=0, **changes):
    evidence = Evidence(
        observation_status="terminal", outcome=1, time_kind="exact",
        time_lower=1, final_cost=2, observed_at=3, receipt_ref=f"fixture-effect:{index}",
    )
    values = dict(
        sample_id=f"fixture:{index}", task_group=f"group:{index}", split="dev",
        policy_id="fixture-policy", chosen_action="read", executed_action="read",
        execution_ref=f"fixture-exec:{index}", decision_at=1, prediction_at=0.5,
        clock_id="fixture-clock", information_set_digest="a" * 64,
        budget_contract_digest=CONTRACT.digest, prediction=FORECAST, evidence=evidence,
        full_wall_seconds=2, costs={key: 2 if key == "action" else 0 for key in COST_FIELDS},
    )
    values.update(changes)
    return ObservedDecision(**values)


class OfflineCalibrationTests(unittest.TestCase):
    def test_unsupported_and_incomplete_costs_remain_in_denominators(self):
        second = decision(1, full_wall_seconds=None)
        second = replace(second, costs={**second.costs, "training": None})
        report = summarize_offline_forecasts([decision(), second], [FORECAST, None])["overall"]
        self.assertEqual(report["metrics"]["duration_crps"], {"count": 2, "eligible": 1, "missing": 1, "mean": 0.0})
        self.assertEqual(report["unsupported_predictions"], 1)
        self.assertEqual(report["full_wall_missing_count"], 1)
        self.assertEqual(report["cost_ledger_incomplete_count"], 1)
        self.assertEqual(report["missing_cost_item_counts"], {key: int(key == "training") for key in COST_FIELDS})

    def test_unknown_cancel_and_censor_are_not_exact_duration_or_zero_cost(self):
        rows = []
        for index, status in enumerate(("receipt_missing", "awaiting", "cancel_requested", "verified_ongoing")):
            options = dict(observation_status=status, observed_at=3)
            if status == "verified_ongoing":
                options.update(time_kind="right_censored", time_lower=1, nonoccurrence_witness="fixture-witness")
            rows.append(decision(index, evidence=Evidence(**options)))
        interval = replace(decision(4).evidence, time_kind="interval", time_upper=2)
        rows.append(decision(4, evidence=interval))
        report = summarize_offline_forecasts(rows, [FORECAST] * 5)["overall"]
        self.assertEqual(report["time_kind_counts"], {"unobserved": 3, "right_censored": 1, "interval": 1})
        self.assertEqual(report["observation_status_counts"], {s: 1 for s in ("receipt_missing", "awaiting", "cancel_requested", "verified_ongoing", "terminal")})
        self.assertEqual(report["metrics"]["duration_crps"], {"count": 5, "eligible": 0, "missing": 5, "mean": None})
        self.assertEqual(report["metrics"]["cost_crps"]["eligible"], 1)
        self.assertTrue(all(item["coverage"] is None for item in report["quantile_coverage"]["duration"]))

    def test_only_chosen_executed_actions_receive_scores(self):
        rows = [decision(executed_action=None, execution_ref=None), decision(1, executed_action="write")]
        report = summarize_offline_forecasts(rows, [FORECAST] * 2)["overall"]
        self.assertEqual(report["unobserved_chosen_actions"], 2)
        self.assertTrue(all(metric == {"count": 2, "eligible": 0, "missing": 2, "mean": None} for metric in report["metrics"].values()))

    def test_sources_splits_and_actions_do_not_become_owner_benefit(self):
        rows = [decision(), decision(1, source="declared_owner", chosen_action="write", executed_action="write", split="train")]
        report = summarize_offline_forecasts(rows, [FORECAST] * 2)
        self.assertEqual([(g["source"], g["split"], g["chosen_action"], g["count"]) for g in report["groups"]], [("declared_owner", "train", "write", 1), ("fixture", "dev", "read", 1)])
        self.assertEqual(report["overall"]["source_counts"], {"fixture": 1, "declared_owner": 1})
        self.assertFalse(report["native_provenance_authenticated"])
        self.assertFalse(report["causal_policy_value_identified"])
        self.assertIsNone(report["counterfactual_policy_value"])

    def test_reliability_endpoints_and_quantile_coverage(self):
        forecasts = [{**FORECAST, "success_probability": p} for p in (0, 0.1, 1)]
        report = summarize_offline_forecasts([decision(i) for i in range(3)], forecasts)["overall"]
        self.assertEqual([b["count"] for b in report["success_reliability_bins"]], [1, 1, 0, 0, 0, 0, 0, 0, 0, 1])
        self.assertEqual(report["success_reliability_bins"][-1], {"lower": 0.9, "upper": 1.0, "count": 1, "mean_prediction": 1.0, "outcome_rate": 1.0})
        self.assertEqual(report["quantile_coverage"]["duration"], [{"level": q, "count": 3, "eligible": 3, "missing": 0, "mean": 1.0, "coverage": 1.0} for q in (0.1, 0.5, 0.9)])

    def test_mixed_budget_contracts_cannot_share_overall_means(self):
        other = replace(CONTRACT, cost_unit="other-fixture-work")
        rows = [decision(), decision(1, source="declared_owner", budget_contract_digest=other.digest)]
        for forecasts in ([FORECAST, FORECAST], [None, None]):
            with self.subTest(forecasts=forecasts), self.assertRaisesRegex(ValueError, "mixed budget contracts"):
                summarize_offline_forecasts(rows, forecasts)

    def test_better_offline_calibration_never_repairs_actual_utility_eligibility(self):
        row = decision(source="declared_owner")
        row = replace(row, costs={**row.costs, "training": None})
        before = observed_to_dict(row)
        gate = paired_adoption_gate([row], CONTRACT)
        old = summarize_offline_forecasts([row], [{**FORECAST, "success_probability": 0}])
        new = summarize_offline_forecasts([row], [{**FORECAST, "success_probability": 1}])
        self.assertLess(new["overall"]["metrics"]["quality_brier"]["mean"], old["overall"]["metrics"]["quality_brier"]["mean"])
        self.assertEqual(observed_to_dict(row), before)
        self.assertIsNone(score_observed(row, CONTRACT)["actual_net_utility"])
        self.assertEqual(paired_adoption_gate([row], CONTRACT), gate)
        self.assertEqual(new["decision"], "NoUpdate")
        self.assertFalse(new["candidate_eligible"])
        json.dumps(new, allow_nan=False)

    def test_duplicate_mismatch_unbounded_and_invalid_forecasts_fail_closed(self):
        row = decision()
        for rows, predictions in (([], []), ([row], []), ([row, row], [FORECAST] * 2), ([row] * (MAX_OBSERVATIONS + 1), [None] * (MAX_OBSERVATIONS + 1)), (iter([row]), [FORECAST]), ([object()], [FORECAST])):
            with self.subTest(rows=type(rows)), self.assertRaises(ValueError):
                summarize_offline_forecasts(rows, predictions)
        unexecuted = replace(row, executed_action=None, execution_ref=None)
        for malformed in ({**FORECAST, "success_probability": float("nan")}, []):
            with self.assertRaises(ValueError):
                summarize_offline_forecasts([unexecuted], [malformed])
