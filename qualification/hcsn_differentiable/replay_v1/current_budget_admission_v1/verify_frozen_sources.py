"""Verify exact source, inherited originals, and fail-closed HOLD semantics."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_differentiable.replay_v1.current_budget_admission_v1 import (
    budget_contract,
)


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "qualification/hcsn_differentiable/replay_v1/current_budget_admission_v1"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha1(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    freeze = _json(PACKAGE / "SOURCE_FREEZE.json")
    for relative, expected in freeze["source_sha256"].items():
        if _sha256(ROOT / relative) != expected:
            raise SystemExit("source SHA-256 mismatch: " + relative)
    request = _json(PACKAGE / "REQUEST.json")
    if request["bound_commits"] != freeze["bound_commits"]:
        raise SystemExit("bound commit map mismatch")
    if request["bound_git_blobs"] != freeze["bound_git_blobs"]:
        raise SystemExit("bound blob map mismatch")
    for relative, expected in request["bound_git_blobs"].items():
        if _git_blob_sha1(ROOT / relative) != expected:
            raise SystemExit("bound Git blob mismatch: " + relative)

    state = _json(
        ROOT
        / "qualification/hcsn_c2_original_parent_state_audit_20261114_c06d/RESULT.json"
    )
    boundary = _json(
        ROOT
        / "qualification/hcsn_c2_original_parent_boundary_audit_20261114_c06d/RESULT.json"
    )
    ledger = _json(
        ROOT / "qualification/hcsn_c2_original_budget_ledger_20261114_c06d/LEDGER.json"
    )
    request_rows = {row["fit"]: row for row in request["fits"]}
    for row in state["rows"]:
        target = request_rows[row["fit"]]
        if (
            target["original_parent_sha256"] != row["sha256"]
            or target["original_parent_epoch"] != row["epoch"]
            or target["original_parent_main_updates"] != row["main_updates"]
            or target["cursor_key_present"] != row["cursor_key_present"]
        ):
            raise SystemExit("parent state was not copied exactly: " + row["fit"])
    for row in boundary["fits"]:
        target = request_rows[row["fit"]]
        if (
            target["original_parent_sha256"] != row["last_sha256"]
            or target["original_parent_epoch"] != row["epochs_completed_at_last"]
            or target["original_parent_main_updates"] != row["updates_at_last"]
            or row["resume_supported"] is not False
        ):
            raise SystemExit("parent boundary was not copied exactly: " + row["fit"])
    for row in ledger["fits"]:
        target = request_rows[row["fit"]]
        if (
            target["original_whole_process_wall_seconds"]
            != row["original_whole_process_wall_seconds"]
            or target["original_decision_charged_remainder_before_reserve_seconds"]
            != row["original_decision_non_refunded_charged_remainder_seconds"]
            or target["original_decision_worker_active_ceiling_seconds"]
            != row[
                "original_decision_worker_active_ceiling_before_finalization_seconds"
            ]
        ):
            raise SystemExit("original budget was not copied exactly: " + row["fit"])

    decision = budget_contract.validate_current_budget_admission(request)
    required_blockers = {
        "complete_history_accounted",
        "complete_history_budget_ledger",
        "original_controller_terminal",
        "lifetime_optimizer_calls",
        "historical_attempt_ledger",
        "single_campaign_freeze",
        "current_resource_capture_sha256",
        "allocation_reservation_sha256",
        "source_runtime_model_data_freeze_sha256",
        "successor_cursor_protocol_sha256",
        "execution_key",
    }
    if decision.admitted or not required_blockers.issubset(decision.blockers):
        raise SystemExit("frozen request did not remain fail closed")
    if request["status"] != "HOLD" or request["all_closed"] is not False:
        raise SystemExit("HOLD metadata changed")
    if request["full_replay_completed"] != 0:
        raise SystemExit("full replay count changed")
    if request["lifetime_optimizer_calls_status"] != "UNKNOWN":
        raise SystemExit("optimizer lifetime UNKNOWN was erased")
    if request["original_controller_terminal"] != "UNKNOWN":
        raise SystemExit("controller terminal UNKNOWN was erased")
    if sum(request["execution"].values()) != 0:
        raise SystemExit("source-only contract reports execution")

    tree = ast.parse((PACKAGE / "budget_contract.py").read_text(encoding="utf-8"))
    imported = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported != {"dataclasses", "math", "re"}:
        raise SystemExit("budget contract has an unapproved import")
    forbidden = {
        "Popen",
        "backward",
        "load",
        "open",
        "optimizer",
        "run",
        "system",
        "torch",
    }
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("budget contract exposes a forbidden execution call")
    print("PASS_C2_CURRENT_BUDGET_ADMISSION_HOLD")


if __name__ == "__main__":
    main()
