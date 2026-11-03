"""Explicit unpinned live observation, separate from fixed-identity qualification."""

import math
import re

from owner_boundary import cost_claim_fields, matrix_owner_boundary

MODEL_ALIAS = "qwen38-flash-next-uc"
MODES = ("replay", "live", "observed-live")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")


def identity_contract(mode, evidence, upstream, evidence_file_sha256=None):
    if mode not in MODES or not isinstance(evidence, dict):
        raise ValueError("explicit known run mode and object-shaped model evidence required")
    if mode == "live":
        # Preserve the existing fixed-identity gate. A failure never switches
        # transport or silently enables observed-live.
        if (evidence.get("schema") != "hepta.model-identity.v1"
                or evidence.get("model") != MODEL_ALIAS
                or not evidence.get("response_model") or not evidence.get("provider_revision")
                or not re.fullmatch(r"[0-9a-f]{64}", evidence.get("model_sha256", ""))
                or not re.fullmatch(r"[0-9a-f]{64}", evidence.get("evidence_sha256", ""))):
            raise ValueError("live run requires exact provider/model identity evidence, not an alias")
    if mode == "observed-live" and evidence.get("model") not in (None, MODEL_ALIAS):
        raise ValueError("optional evidence names a different requested model alias")
    fixed = mode == "live"
    return {"schema": "hepta.run-model-identity.v1", "mode": mode,
        "status": "fixed_identity_evidence_supplied" if fixed else "synthetic_replay" if mode == "replay" else "unattested",
        "requested_model_alias": MODEL_ALIAS, "upstream": upstream,
        "expected_response_model": evidence.get("response_model") if fixed else None,
        "provider_revision": evidence.get("provider_revision") if fixed else None,
        "model_sha256": evidence.get("model_sha256") if fixed else None,
        "identity_evidence_sha256": evidence.get("evidence_sha256") if fixed else None,
        "available_config_evidence_file_sha256": evidence_file_sha256,
        "strict_live_qualification_requested": fixed,
        "model_identity_equality_established": False,
        "automatic_identity_downgrade": False,
        "scope": "Observed response fields and task outcomes in this client time window; alias equality does not prove equal weights, provider revision or hidden provider behavior."
            if mode == "observed-live" else "Fixed identity evidence remains subject to every actual response audit." if fixed else "Known response replay; no live model quality claim."}


def transport_mode(mode):
    if mode not in MODES:
        raise ValueError("unknown run mode")
    return "replay" if mode == "replay" else "live"


def require_accounting(mode, complete):
    if mode not in MODES:
        raise ValueError("unknown run mode")
    if not complete and mode != "observed-live":
        raise ValueError("attempt all-attempt accounting is incomplete")
    return "complete" if complete else "partial_unknown"


def observed_costs(rows):
    """All attempted costs divided by independently observed task successes.

    This is a descriptive quotient for this matrix/window. It is not a future
    success estimate, an engine efficiency ratio, or a same-weight-model claim.
    """
    grouped = {}
    for row in rows:
        key = (row["case"], row["lane"])
        grouped.setdefault(key, []).append(row)
    results = []
    for (case, lane), attempts in sorted(grouped.items()):
        successes = sum(row.get("capability_passed", row.get("status") == "passed") is True for row in attempts)
        walls = [row.get("attempt_wall_ms") for row in attempts]
        wall_complete = all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in walls)
        wall_total = sum(walls) if wall_complete else None
        accounts = [row.get("model_accounting", {}) for row in attempts]
        totals = {key: sum(account.get("known_usage_subtotal", {}).get(key, 0) for account in accounts) for key in TOKEN_FIELDS}
        usage_complete = all(account.get("complete") is True and isinstance(account.get("exact_usage_total"), dict) for account in accounts)
        exact = {key: sum(account["exact_usage_total"][key] for account in accounts) for key in TOKEN_FIELDS} if usage_complete else None
        results.append({"case": case, "lane": lane, "attempts": len(attempts),
            **cost_claim_fields(lane),
            "capability_successes": successes, "unsuccessful_tasks": len(attempts) - successes,
            "run_failures": sum(row.get("status") != "passed" for row in attempts),
            "all_attempt_wall_ms": wall_total,
            "all_attempt_wall_ms_per_observed_success": wall_total / successes if successes and wall_total is not None else None,
            "known_usage_subtotal": totals, "exact_usage_total": exact,
            "exact_tokens_per_observed_success": {key: exact[key] / successes for key in TOKEN_FIELDS} if successes and exact else None,
            "unknown_usage_attempts": sum(account.get("unknown_usage_attempts", 0) for account in accounts),
            "incomplete_accounting_task_attempts": sum(account.get("complete") is not True for account in accounts),
            "whole_system_cpu_seconds": None, "provider_gpu_seconds": None, "monetary_cost": None,
            "failed_attempt_costs_included": True, "automatic_retries": 0})
    return {"by_case_and_lane": results,
        "owner_boundary": matrix_owner_boundary(sorted({row["lane"] for row in rows})) if rows else None,
        "cost_scope": "execution-observation", "product_total_cost": None,
        "execution_layer_causal_attribution": False,
        "scope": "Every original attempt for each case/lane, including failures; measured attempt window covers backend startup through shutdown, not preparation or correctness audit. Unknown cost is null, not zero.",
        "fixed_model_identity_claim": False, "future_success_cost_claim": False,
        "p95_or_general_efficiency_claim": False}


def response_model_observations(rows):
    return [{"lane": row["lane"], "case": row["case"], "repeat": row["repeat"],
        "attempt": attempt.get("attempt"), "response_id": attempt.get("response_id"),
        "reported_model": attempt.get("response_model"), "response_status": attempt.get("response_status"),
        "usage_state": attempt.get("usage_state")}
        for row in rows for attempt in row.get("model_accounting", {}).get("attempts", [])]
