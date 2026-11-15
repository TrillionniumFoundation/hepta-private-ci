"""Fail closed unless the complete C2 replay history and resources are bound."""

import math
import re
from dataclasses import dataclass


SCHEMA = "hcsn-c2-current-budget-admission-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
EXPECTED_FITS = {
    "hcsn-s101-lr0.001": (46, 552, "e0c8c946aa8010bfcf4df5b9e155235d2fb6b12a9832e4eaa5db3d9afb154d78"),
    "hcsn-s101-lr0.003": (47, 564, "bea446e64571e7cd424411036eff207bb6839af4495a7b60cf0f9df81181ba05"),
    "hcsn-s211-lr0.001": (46, 552, "cdbca6e633c6aba5f72f08f259ab08b1c5c2c5745d1dbd2f323a78df876e1e79"),
    "hcsn-s211-lr0.003": (47, 564, "b7d162101f18628fcfcabb21e9609499d62c8a26ad6d53b9c375ed2e0439d2f4"),
    "hcsn-s307-lr0.001": (46, 552, "17d6ad363d82ba31b006d0a4f55ca9c63453fa2c9c34f7370f022e2ff66a4f5c"),
    "hcsn-s307-lr0.003": (46, 552, "736ee7d7afe911a3cf5bb7f7ad97babff4dfb74e28a46ec9c148579160a5075c"),
}
TOP_FIELDS = {
    "schema",
    "identity",
    "base_commit",
    "base_pull_request",
    "status",
    "all_closed",
    "complete_history_accounted",
    "complete_history_budget_ledger",
    "full_replay_completed",
    "full_replay_denominator",
    "known_completed_diagnostic_optimizer_calls",
    "lifetime_optimizer_calls",
    "lifetime_optimizer_calls_status",
    "original_controller_terminal",
    "original_training_resume_supported",
    "execution_key",
    "replay_admitted",
    "resource_admitted",
    "production_adoption",
    "single_campaign_freeze_complete",
    "current_resource_capture_sha256",
    "allocation_reservation_sha256",
    "source_runtime_model_data_freeze_sha256",
    "successor_cursor_protocol_sha256",
    "historical_negative_and_unknown_preserved",
    "execution",
    "bound_commits",
    "bound_git_blobs",
    "historical_attempts",
    "fits",
}
FIT_FIELDS = {
    "fit",
    "original_parent_sha256",
    "original_parent_epoch",
    "original_parent_main_updates",
    "cursor_key_present",
    "original_whole_process_wall_seconds",
    "original_decision_charged_remainder_before_reserve_seconds",
    "finalization_reserve_seconds",
    "original_decision_worker_active_ceiling_seconds",
    "later_non_refunded_wall_seconds",
    "later_non_refunded_wall_status",
    "per_fit_exit_overhead_seconds",
    "per_fit_exit_overhead_status",
    "current_remaining_wall_seconds",
    "current_remaining_wall_status",
    "current_worker_active_ceiling_seconds",
    "current_worker_active_ceiling_status",
    "complete_attempt_history",
}
ATTEMPT_FIELDS = {
    "identity",
    "status",
    "budget_scope",
    "complete_wall",
    "optimizer_count",
}


class BudgetAdmissionError(ValueError):
    """Raised when the admission record is malformed or rewrites originals."""


@dataclass(frozen=True)
class BudgetAdmissionDecision:
    admitted: bool
    blockers: tuple
    model_calls: int = 0
    torch_calls: int = 0
    optimizer_calls: int = 0
    native_training_calls: int = 0
    new_idempotency_keys: int = 0
    full_replay_completed: int = 0
    production_adoption: bool = False


def _require(condition, message):
    if not condition:
        raise BudgetAdmissionError(message)


def _resolved_nonnegative(value, status):
    return status == "RESOLVED" and isinstance(value, (int, float)) and value >= 0


def _sha256(value):
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def validate_current_budget_admission(record):
    """Validate exact originals and return a fail-closed admission decision."""

    _require(isinstance(record, dict) and set(record) == TOP_FIELDS, "top-level field set mismatch")
    _require(record["schema"] == SCHEMA, "schema mismatch")
    _require(record["base_commit"] == "3665799158a8ca44e14ecad6f92d382905dfbbb3", "base commit mismatch")
    _require(record["base_pull_request"] == 6315, "base pull request mismatch")
    _require(record["full_replay_denominator"] == 6, "replay denominator changed")
    _require(record["known_completed_diagnostic_optimizer_calls"] == 52, "diagnostic call count changed")
    _require(record["historical_negative_and_unknown_preserved"] is True, "historical result erased")
    _require(record["original_training_resume_supported"] is False, "historical resume support was rewritten")
    _require(record["production_adoption"] is False, "contract cannot adopt production")
    _require(record["all_closed"] is False, "contract cannot self-close")
    _require(all(value == 0 for value in record["execution"].values()), "source-only contract reports execution")
    _require(set(record["bound_commits"]) == {"parent_recovery", "parent_state", "parent_boundary", "original_start_budget"}, "bound commit set mismatch")
    _require(all(GIT_SHA_RE.fullmatch(value) for value in record["bound_commits"].values()), "invalid bound commit")
    _require(len(record["bound_git_blobs"]) == 11, "bound original set mismatch")
    _require(all(GIT_SHA_RE.fullmatch(value) for value in record["bound_git_blobs"].values()), "invalid bound blob")

    attempts = record["historical_attempts"]
    _require(isinstance(attempts, list) and attempts, "historical attempt ledger missing")
    for attempt in attempts:
        _require(isinstance(attempt, dict) and set(attempt) == ATTEMPT_FIELDS, "attempt field set mismatch")
        _require(isinstance(attempt["identity"], str) and attempt["identity"], "attempt identity missing")
        _require(isinstance(attempt["budget_scope"], str) and attempt["budget_scope"], "attempt budget scope missing")

    fits = record["fits"]
    _require(isinstance(fits, list) and len(fits) == 6, "fit ledger must contain six rows")
    _require({row.get("fit") for row in fits} == set(EXPECTED_FITS), "fit identity set mismatch")
    original_walls = []
    original_remainders = []
    original_ceilings = []
    blockers = []
    for row in fits:
        _require(isinstance(row, dict) and set(row) == FIT_FIELDS, "fit field set mismatch")
        epoch, updates, parent_sha256 = EXPECTED_FITS[row["fit"]]
        _require(row["original_parent_epoch"] == epoch, "original parent epoch changed")
        _require(row["original_parent_main_updates"] == updates, "original parent update count changed")
        _require(row["original_parent_sha256"] == parent_sha256, "original parent bytes changed")
        _require(row["cursor_key_present"] is False, "missing historical cursor was rewritten")
        wall = row["original_whole_process_wall_seconds"]
        remainder = row["original_decision_charged_remainder_before_reserve_seconds"]
        reserve = row["finalization_reserve_seconds"]
        ceiling = row["original_decision_worker_active_ceiling_seconds"]
        _require(43200.0 - wall == remainder, "original charged remainder arithmetic mismatch")
        _require(reserve == 600.0 and remainder - reserve == ceiling, "original reserve arithmetic mismatch")
        original_walls.append(wall)
        original_remainders.append(remainder)
        original_ceilings.append(ceiling)
        if not row["complete_attempt_history"]:
            blockers.append(row["fit"] + ":complete_attempt_history")
        for value_name, status_name in (
            ("later_non_refunded_wall_seconds", "later_non_refunded_wall_status"),
            ("per_fit_exit_overhead_seconds", "per_fit_exit_overhead_status"),
            ("current_remaining_wall_seconds", "current_remaining_wall_status"),
            ("current_worker_active_ceiling_seconds", "current_worker_active_ceiling_status"),
        ):
            if not _resolved_nonnegative(row[value_name], row[status_name]):
                blockers.append(row["fit"] + ":" + value_name)
    _require(math.fsum(original_walls) == 86261.1154101817, "original wall sum changed")
    _require(math.fsum(original_remainders) == 172938.8845898183, "original charged remainder sum changed")
    _require(math.fsum(original_ceilings) == 169338.8845898183, "original worker ceiling sum changed")

    if not record["complete_history_accounted"]:
        blockers.append("complete_history_accounted")
    if not record["complete_history_budget_ledger"]:
        blockers.append("complete_history_budget_ledger")
    if record["original_controller_terminal"] != "SUCCEEDED":
        blockers.append("original_controller_terminal")
    if record["lifetime_optimizer_calls_status"] != "RESOLVED" or not isinstance(record["lifetime_optimizer_calls"], int):
        blockers.append("lifetime_optimizer_calls")
    if any(
        attempt["status"] == "UNKNOWN"
        or not attempt["complete_wall"]
        or not isinstance(attempt["optimizer_count"], int)
        for attempt in attempts
    ):
        blockers.append("historical_attempt_ledger")
    if not record["single_campaign_freeze_complete"]:
        blockers.append("single_campaign_freeze")
    for name in (
        "current_resource_capture_sha256",
        "allocation_reservation_sha256",
        "source_runtime_model_data_freeze_sha256",
        "successor_cursor_protocol_sha256",
    ):
        if not _sha256(record[name]):
            blockers.append(name)
    if not isinstance(record["execution_key"], str) or not record["execution_key"]:
        blockers.append("execution_key")
    admitted = not blockers
    _require(record["replay_admitted"] is admitted, "replay admission flag disagrees with evidence")
    _require(record["resource_admitted"] is admitted, "resource admission flag disagrees with evidence")
    return BudgetAdmissionDecision(admitted=admitted, blockers=tuple(blockers))
