#!/usr/bin/env python3
"""Fail-closed, source-only C2 replay admission contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REQUEST = ROOT / "REQUEST.json"


class AdmissionError(ValueError):
    """Raised when a request attempts to admit incomplete replay history."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdmissionError(message)


def load_request(path: Path = REQUEST) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), "request must be a JSON object")
    return raw


def validate_request(request: dict[str, Any]) -> dict[str, Any]:
    _require(request.get("status") == "HOLD_INCOMPLETE_HISTORY", "status must remain HOLD")
    constraints = request.get("constraints")
    _require(isinstance(constraints, dict), "constraints missing")
    _require(constraints.get("stdlib_only") is True, "stdlib-only binding changed")
    _require(constraints.get("synthetic_tests_only") is True, "tests are not synthetic-only")
    for counter in ("model_executions", "torch_executions", "optimizer_calls", "native_jobs", "new_execution_keys"):
        _require(constraints.get(counter) == 0, f"{counter} must remain zero")

    decision = request.get("decision")
    _require(isinstance(decision, dict), "decision missing")
    _require(decision.get("all_closed") is False, "all_closed may not be true")
    _require(decision.get("replay_admitted") is False, "replay may not be admitted")
    _require(decision.get("resource_admitted") is False, "resources may not be admitted")
    _require(decision.get("execution_key") is None, "execution key must remain null")
    _require(decision.get("complete_attempt_history") is False, "attempt history is incomplete")
    _require(decision.get("complete_historical_cost_known") is False, "historical cost is incomplete")
    _require(decision.get("full_fit_replays_completed") == 0, "full replay remains 0/6")
    _require(decision.get("full_fit_replays_required") == 6, "six full fit replays are required")
    _require(decision.get("lifetime_optimizer_calls") is None, "lifetime optimizer calls remain unknown")
    _require(decision.get("lifetime_optimizer_calls_status") == "UNKNOWN", "optimizer status must be UNKNOWN")
    _require(decision.get("original_controller_terminal_status") == "UNKNOWN", "controller must remain UNKNOWN")

    diagnostics = request.get("diagnostics")
    _require(isinstance(diagnostics, dict), "diagnostics missing")
    _require(diagnostics.get("successful_checkpoint_continuations") == 12, "diagnostic continuation count changed")
    _require(diagnostics.get("known_optimizer_calls") == 52, "diagnostic optimizer count changed")
    _require(diagnostics.get("counts_as_full_training_replay") is False, "diagnostics cannot become full replay")

    identity = request.get("source_runtime_model_data")
    _require(isinstance(identity, dict), "identity section missing")
    _require(identity.get("runtime_identity_bytes_git_bound") is False, "runtime bytes are not Git-bound")
    _require(identity.get("model_identity_complete") is False, "model identity is incomplete")
    _require(identity.get("coherent_current_admission_identity_complete") is False, "identity is incomplete")

    fits = request.get("fits")
    _require(isinstance(fits, list) and len(fits) == 6, "exactly six fits are required")
    fit_names = {fit.get("fit") for fit in fits if isinstance(fit, dict)}
    _require(len(fit_names) == 6, "fit names must be unique")
    wall_sum = 0.0
    remainder_sum = 0.0
    active_sum = 0.0
    for fit in fits:
        _require(isinstance(fit, dict), "fit entry must be an object")
        _require(fit.get("cursor") is None, "cursor is absent and must remain null")
        parent = fit.get("parent_sha256")
        _require(isinstance(parent, str) and len(parent) == 64, "parent sha256 missing")
        wall = fit.get("original_whole_process_wall_seconds")
        remainder = fit.get("original_decision_charged_remainder_before_reserve_seconds")
        active = fit.get("original_decision_worker_active_ceiling_after_reserve_seconds")
        _require(all(isinstance(value, (int, float)) and math.isfinite(value) for value in (wall, remainder, active)), "invalid wall value")
        _require(math.isclose(43200.0 - wall, remainder, rel_tol=0.0, abs_tol=5e-12), "charged remainder arithmetic mismatch")
        _require(math.isclose(remainder - 600.0, active, rel_tol=0.0, abs_tol=5e-12), "worker ceiling arithmetic mismatch")
        wall_sum += wall
        remainder_sum += remainder
        active_sum += active

    budget = request.get("budget")
    _require(isinstance(budget, dict), "budget missing")
    _require(budget.get("per_fit_cap_seconds") == 43200, "fit cap changed")
    _require(budget.get("per_fit_exit_reserve_seconds") == 600, "exit reserve changed")
    _require(math.isclose(remainder_sum, budget.get("original_decision_summed_charged_remainder_before_reserve_seconds"), rel_tol=0.0, abs_tol=5e-11), "summed charged remainder mismatch")
    _require(math.isclose(active_sum, budget.get("original_decision_summed_worker_active_ceiling_after_reserve_seconds"), rel_tol=0.0, abs_tol=5e-11), "summed worker ceiling mismatch")
    _require(math.isclose(wall_sum, 86261.1154101817, rel_tol=0.0, abs_tol=5e-11), "original outer-wall sum mismatch")
    for unknown in ("later_attempt_wall_seconds", "per_fit_exit_overhead_seconds", "current_charged_remainder_seconds", "current_worker_active_ceiling_seconds"):
        _require(budget.get(unknown) is None, f"{unknown} must remain null")
    _require(budget.get("current_balance_status") == "UNKNOWN", "current balance must remain UNKNOWN")

    lineage = request.get("frozen_lineage")
    _require(isinstance(lineage, list) and len(lineage) == 6, "six frozen lineage entries required")
    for entry in lineage:
        _require(isinstance(entry, dict), "lineage entry must be an object")
        _require(isinstance(entry.get("commit"), str) and len(entry["commit"]) == 40, "invalid commit")
        _require(isinstance(entry.get("blob"), str) and len(entry["blob"]) == 40, "invalid blob")
        _require(isinstance(entry.get("path"), str) and entry["path"].startswith("qualification/"), "invalid path")

    return {
        "status": "HOLD_INCOMPLETE_HISTORY",
        "replay_admitted": False,
        "resource_admitted": False,
        "execution_key": None,
        "full_fit_replays": "0/6",
        "current_balance": "UNKNOWN",
        "diagnostics_count_as_full_replay": False,
    }


def main() -> int:
    print(json.dumps(validate_request(load_request()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
