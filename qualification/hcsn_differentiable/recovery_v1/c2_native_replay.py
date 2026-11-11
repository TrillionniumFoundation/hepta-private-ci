"""Structural cross-binding of *exported* native C2 observations (HOLD-only).

This never reads the native supervisor, authenticates a copied observation,
replays a model, or authorizes training/scientific admission. Caller MUST
obtain native status independently; in-band producer claims are insufficient.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Mapping

try:
    from .c2_durable import EvidenceError, identity, read_receipts
except ImportError:
    from c2_durable import EvidenceError, identity, read_receipts

WAIT4_SCOPE = "exact per-PID wait4 whole process including imports and finalization"
SUCCESS_STATE = "succeeded"
MAX_RESULT_BYTES = 16 << 20
MAX_RESOURCE_BYTES = 1 << 20


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate resource JSON key")
        result[key] = value
    return result


def _reject_json_constant(token):
    raise EvidenceError("nonfinite resource JSON constant: " + token)


def _finite_json_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise EvidenceError("nonfinite resource JSON exponent")
    return value


def _strict_resource_bytes(path):
    if path.stat().st_size > MAX_RESOURCE_BYTES:
        raise EvidenceError("resource evidence exceeds byte cap")
    return json.loads(path.read_bytes(), object_pairs_hook=_unique_json_object,
                      parse_constant=_reject_json_constant,
                      parse_float=_finite_json_float)


def _nonnegative_number(value):
    return type(value) in (int, float) and 0 <= value < float("inf")


def _resource(report, job_id):
    if type(report) is not dict or report.get("schema") != "hcsn-c2-resource-v1":
        raise EvidenceError("missing exact resource schema")
    if report.get("native_job_id") != job_id:
        raise EvidenceError("resource-native job binding differs")
    if report.get("child_cpu_scope") != WAIT4_SCOPE:
        raise EvidenceError("resource not an exact wait4 child cost")
    fields = ("child_cpu_seconds", "child_user_cpu_seconds",
              "child_system_cpu_seconds", "whole_process_wall_seconds",
              "attempt_wrapper_wall_seconds", "child_peak_rss_bytes")
    if not all(_nonnegative_number(report.get(k)) for k in fields):
        raise EvidenceError("incomplete or invalid resource bill")
    cpu = report["child_cpu_seconds"]
    parts = report["child_user_cpu_seconds"] + report["child_system_cpu_seconds"]
    if abs(cpu - parts) > max(1e-8, 1e-6 * max(cpu, parts)):
        raise EvidenceError("wait4 child CPU does not reconcile")
    if report["attempt_wrapper_wall_seconds"] + 1e-9 < report["whole_process_wall_seconds"]:
        raise EvidenceError("attempt wrapper shorter than entire child execution")
    if report["child_peak_rss_bytes"] <= 0:
        raise EvidenceError("missing child peak RSS")


def _native_status(status, expected_job_id, expected_success):
    if type(status) is not dict or status.get("job_id") != expected_job_id:
        raise EvidenceError("native status identity mismatch")
    if (status.get("status_authoritative") is not True
            or status.get("terminal_publication_confirmed") is not True
            or status.get("output_complete") is not True
            or status.get("output_durable") is not True):
        raise EvidenceError("native terminal or output not confirmed")
    if status.get("log_truncated") not in (False, {"stderr": False, "stdout": False}):
        raise EvidenceError("native output truncated or unknown")
    if expected_success:
        if status.get("state") != SUCCESS_STATE or type(status.get("exit_code")) is not int or status["exit_code"] != 0:
            raise EvidenceError("producer success contradicts native state/exit")
    elif status.get("state") not in ("failed", "cancelled", "timed_out"):
        raise EvidenceError("producer non-success lacks matching native terminal")


def inspect_exported_observations(receipts_root: Path, *, owner_start_id: str,
                                  expected_attempts: list[str],
                                  native_observations: Mapping[str, dict],
                                  artifacts_root: Path) -> dict:
    """Fail-closed per-attempt structural inventory, never independent attestation.

    Result/resource objects must exist at exact successor paths, be nonempty and
    match receipt digests. Native observations are UNTRUSTED COPIES: passing only
    means structural cross-binding; authentic live native reads remain mandatory.
    All missing/failing attempts stay in the frozen denominator.
    """
    if type(expected_attempts) is not list or not expected_attempts or len(set(expected_attempts)) != len(expected_attempts):
        raise EvidenceError("frozen nonempty unique roster required")
    if type(native_observations) is not dict:
        raise EvidenceError("native observation mapping must be a builtin dict")
    events = read_receipts(receipts_root, owner_start_id=owner_start_id)
    names = set(expected_attempts)
    if any(e["attempt_id"] not in names for e in events):
        raise EvidenceError("receipt contains unrostered attempt")
    terminal = {e["attempt_id"]: e["payload"] for e in events if e["event_type"] == "terminal"}
    rejected = {}
    missing = []
    matched = []
    successful = []
    used_jobs = set()
    root = Path(artifacts_root)
    for attempt in expected_attempts:
        if attempt not in terminal:
            missing.append(attempt)
            continue
        try:
            receipt = terminal[attempt]
            job_id = receipt["native_job_id"]
            if job_id in used_jobs:
                raise EvidenceError("native job reused across attempts")
            used_jobs.add(job_id)
            _native_status(native_observations.get(job_id), job_id,
                           receipt["status"] == "completed")
            dirname = root / attempt
            if dirname.is_symlink() or not dirname.is_dir():
                raise EvidenceError("candidate artifact directory unavailable")
            result = dirname / "result.json"
            resource = dirname / "resource.json"
            if result.stat().st_size > MAX_RESULT_BYTES:
                raise EvidenceError("result evidence exceeds byte cap")
            if resource.stat().st_size > MAX_RESOURCE_BYTES:
                raise EvidenceError("resource evidence exceeds byte cap")
            if identity(result)["sha256"] != receipt["result_sha256"]:
                raise EvidenceError("result bytes differ from receipt")
            if identity(resource)["sha256"] != receipt["resource_sha256"]:
                raise EvidenceError("resource bytes differ from receipt")
            _resource(_strict_resource_bytes(resource), job_id)
            matched.append(attempt)
            if receipt["status"] == "completed":
                successful.append(attempt)
        except (EvidenceError, FileNotFoundError, KeyError, ValueError,
                TypeError, OSError) as exc:
            rejected[attempt] = str(exc)
    return {
        "schema": "hcsn-c2-exported-observation-audit-v1",
        "expected_count": len(expected_attempts),
        "producer_terminal_count": len(terminal),
        "structurally_matched_count": len(matched),
        "structurally_successful_count": len(successful),
        "missing": missing,
        "rejected": rejected,
        "native_observations_are_untrusted_copies": True,
        "independent_live_native_status_verified": False,
        "checkpoint_model_replay_verified": False,
        "heldout_scientific_gain_verified": False,
        "scientific_admission": "HOLD_NO_GO",
    }
