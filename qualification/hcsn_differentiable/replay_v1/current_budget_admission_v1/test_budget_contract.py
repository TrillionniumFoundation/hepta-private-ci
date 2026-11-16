import copy
import json
import unittest
from pathlib import Path

from qualification.hcsn_differentiable.replay_v1.current_budget_admission_v1 import (
    budget_contract,
)


ROOT = Path(__file__).resolve().parent


def _request():
    return json.loads((ROOT / "REQUEST.json").read_text(encoding="utf-8"))


def _synthetically_resolved(record):
    value = copy.deepcopy(record)
    value["complete_history_accounted"] = True
    value["complete_history_budget_ledger"] = True
    value["lifetime_optimizer_calls"] = 123
    value["lifetime_optimizer_calls_status"] = "RESOLVED"
    value["original_controller_terminal"] = "SUCCEEDED"
    value["execution_key"] = "fixture-only-key"
    value["single_campaign_freeze_complete"] = True
    value["current_resource_capture_sha256"] = "a" * 64
    value["allocation_reservation_sha256"] = "b" * 64
    value["source_runtime_model_data_freeze_sha256"] = "c" * 64
    value["successor_cursor_protocol_sha256"] = "d" * 64
    for attempt in value["historical_attempts"]:
        if attempt["status"] == "UNKNOWN":
            attempt["status"] = "RESOLVED_TERMINAL"
        attempt["complete_wall"] = True
        attempt["optimizer_count"] = 0
    for row in value["fits"]:
        row["complete_attempt_history"] = True
        row["later_non_refunded_wall_seconds"] = 0.0
        row["later_non_refunded_wall_status"] = "RESOLVED"
        row["per_fit_exit_overhead_seconds"] = 0.0
        row["per_fit_exit_overhead_status"] = "RESOLVED"
        row["current_remaining_wall_seconds"] = 1.0
        row["current_remaining_wall_status"] = "RESOLVED"
        row["current_worker_active_ceiling_seconds"] = 1.0
        row["current_worker_active_ceiling_status"] = "RESOLVED"
    value["replay_admitted"] = True
    value["resource_admitted"] = True
    return value


class CurrentBudgetAdmissionTests(unittest.TestCase):
    def test_frozen_request_remains_fail_closed(self):
        decision = budget_contract.validate_current_budget_admission(_request())
        self.assertFalse(decision.admitted)
        self.assertIn("complete_history_accounted", decision.blockers)
        self.assertIn("historical_attempt_ledger", decision.blockers)
        self.assertIn("successor_cursor_protocol_sha256", decision.blockers)
        self.assertEqual(decision.model_calls, 0)
        self.assertEqual(decision.optimizer_calls, 0)

    def test_original_start_remainder_cannot_be_used_as_current_balance(self):
        record = _request()
        row = record["fits"][0]
        row["current_remaining_wall_seconds"] = row[
            "original_decision_charged_remainder_before_reserve_seconds"
        ]
        row["current_remaining_wall_status"] = "RESOLVED"
        decision = budget_contract.validate_current_budget_admission(record)
        self.assertFalse(decision.admitted)
        self.assertIn("hcsn-s101-lr0.001:complete_attempt_history", decision.blockers)

    def test_history_gap_forces_rejection_even_with_resource_hashes(self):
        record = _synthetically_resolved(_request())
        record["historical_attempts"][1]["optimizer_count"] = None
        record["replay_admitted"] = False
        record["resource_admitted"] = False
        decision = budget_contract.validate_current_budget_admission(record)
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.blockers, ("historical_attempt_ledger",))

    def test_complete_synthetic_metadata_exercises_positive_boundary(self):
        decision = budget_contract.validate_current_budget_admission(
            _synthetically_resolved(_request())
        )
        self.assertTrue(decision.admitted)
        self.assertEqual(decision.blockers, ())
        self.assertEqual(decision.full_replay_completed, 0)
        self.assertFalse(decision.production_adoption)

    def test_historical_parent_identity_is_immutable(self):
        record = _request()
        record["fits"][0]["original_parent_main_updates"] += 1
        with self.assertRaisesRegex(
            budget_contract.BudgetAdmissionError, "original parent update"
        ):
            budget_contract.validate_current_budget_admission(record)


if __name__ == "__main__":
    unittest.main()
