"""Read retained repository business receipts without executing student code."""

import hashlib

from .data import _require as require, digest


def sha(value):
    """Validate receipt identities without loading numerical model modules."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
        and value != "0" * 64
    )


def semantic_identity(verification):
    """The task and verifier identity that must stay fixed in paired outcomes."""
    return {
        key: verification.get(key)
        for key in (
            "record_id",
            "input_sha256",
            "parameters_sha256",
            "verifier_source_sha256",
        )
    } | {"verifier": list(verification.get("verifier", []))}


def completed_original_calls(verification):
    """A completed original call is not evidence of how many calls were tried."""
    measured = verification.get("result", {}).get("result") or {}
    observations = measured.get("observations")
    if not isinstance(observations, list) or not observations:
        return None
    original = observations[0]
    require(
        isinstance(original, dict) and original.get("control") == "original",
        "original observation required",
    )
    calls = original.get("calls")
    require(isinstance(calls, list), "actual original calls must be a list")
    return len(calls)


def business_evidence(row):
    """Check summaries against actual observations; missing positives stay unknown.

    Hash integrity binds the supplied evidence, not the honesty of an external
    producer. No result from this helper authenticates independent users.
    """
    verification = row["semantic_receipt"]
    payload = {
        key: value
        for key, value in verification.items()
        if key not in ("receipt_sha256", "success")
    }
    require(
        digest(payload)
        == verification.get("receipt_sha256")
        == row.get("semantic_receipt_sha256"),
        "semantic receipt differs",
    )
    require(
        verification.get("schema") == "hepta.cell-experiments.semantic-receipt.v1"
        and list(verification.get("verifier", [])) == ["repo_patch", "1"],
        "repository semantic receipt required",
    )
    require(
        isinstance(verification.get("record_id"), str)
        and verification["record_id"]
        and all(
            sha(verification.get(key))
            for key in (
                "input_sha256",
                "answer_sha256",
                "parameters_sha256",
                "verifier_source_sha256",
            )
        ),
        "semantic identity is incomplete",
    )
    require(
        isinstance(row.get("raw_answer"), str)
        and hashlib.sha256(row["raw_answer"].encode()).hexdigest()
        == verification["answer_sha256"],
        "answer differs from semantic receipt",
    )
    if "semantic_identity" in row:
        require(
            row["semantic_identity"] == semantic_identity(verification),
            "semantic task identity differs",
        )
    result = verification["result"]
    require(
        type(result.get("executed")) is bool, "explicit verifier execution required"
    )
    measured = result.get("result") or {}
    require(isinstance(measured, dict), "invalid business measurements")
    total, rejected = measured.get("control_count"), measured.get("controls_rejected")
    complete_counts = (
        type(total) is int
        and total > 0
        and type(rejected) is int
        and 0 <= rejected <= total
    )
    success = bool(
        result["executed"]
        and type(result.get("exit_code")) is int
        and result["exit_code"] == 0
        and measured.get("original_passed") is True
        and complete_counts
        and rejected == total
    )
    require(
        all(
            type(value) is bool and value == success
            for value in (
                row.get("success"),
                verification.get("success"),
                result.get("success"),
            )
        ),
        "business success is inconsistent",
    )
    observations = measured.get("observations")
    original_passed, controls_complete = None, False
    calls = completed_original_calls(verification)
    if observations:
        require(
            result["executed"] and isinstance(observations, list),
            "observations require verifier execution",
        )
        original_passed = observations[0].get("passed")
        require(
            type(original_passed) is bool
            and measured.get("original_passed") is original_passed,
            "original result disagrees with observations",
        )
        controls = observations[1:]
        require(
            complete_counts and len(controls) == total,
            "control observation inventory differs",
        )
        require(
            all(isinstance(control, dict) for control in controls),
            "invalid control observations",
        )
        names = [control.get("control") for control in controls]
        require(
            all(isinstance(name, str) and name and name != "original" for name in names)
            and len(names) == len(set(names)),
            "distinct control identities required",
        )
        require(
            all(type(control.get("passed")) is bool for control in controls)
            and sum(not control["passed"] for control in controls) == rejected,
            "control result disagrees with observations",
        )
        controls_complete = True
    informative = (
        original_passed is True
        and calls is not None
        and calls > 0
        and controls_complete
    )
    return {
        "business_success": success if not success or informative else None,
        "reported_success": success,
        "format_admitted": True
        if result["executed"]
        else False
        if result.get("reason") == "invalid_test_patch"
        else None,
        "verifier_executed": result["executed"],
        "completed_original_calls": calls,
        "subject_call_attempt_count": None,
        "original_passed": original_passed,
        "control_observations_complete": controls_complete,
        "control_comparison_informative": informative,
        "all_wrong_output_controls_rejected": rejected == total
        if informative
        else None,
        "controls_rejected": rejected if informative else None,
        "control_count": total if informative else None,
    }


def verified_business_row(row):
    """A successful aggregate without complete business evidence remains unknown."""
    return business_evidence(row)["business_success"]
