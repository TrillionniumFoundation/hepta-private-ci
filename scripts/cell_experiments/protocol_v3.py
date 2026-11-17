"""Explicit pre-freeze prompt preparation and gold-free execution feedback.

The v2 semantic verifier and its receipts remain unchanged. Prompt preparation
creates a new development artifact; it never rewrites an ongoing conversation.
"""

import copy
import re

from . import data
from .chat_protocol import inference_messages
from .repo_execution import TEMPLATE

PROTOCOL = "hepta.repository-action-protocol.v3"
LEGACY_ILLUSTRATION = (
    'Return only JSON {"edits":[{"path":"test_contract.py",'
    '"old":"    pass","new":"    assert ..."}]}.'
)
ACTION_CONTRACT = (
    'Return one JSON object with only "edits": a one-element array. Its edit '
    'has exactly "path":"test_contract.py", "old":"    pass", and "new": '
    "an indented Python test body. Use 1-12 assert statements with literal "
    "subject(...) arguments and explicit expected results. JSON-escape quotes "
    'and newlines in "new"; close both objects and the array. Output JSON only. '
    "Each attempt starts from the original template."
)
_INITIAL = {
    "phase": "before_edit",
    "assertion_count": 0,
    "business_contract_covered": False,
    "test_source": TEMPLATE,
}


def require_prepared(record):
    """Reject stale prompt bindings before generation, without altering history."""
    data.validate_record(record, require_outcome=False)
    task = record["task"]
    marker = record.get("action_protocol_v3", {})
    messages = inference_messages(task["input"], task.get("messages"))
    if (
        marker.get("schema") != PROTOCOL
        or marker.get("prepared_input_sha256") != data.digest(task["input"])
        or marker.get("prepared_messages_sha256") != data.digest(messages)
        or (task["verifier"]["name"], task["verifier"]["version"])
        != ("repo_patch", "1")
    ):
        raise ValueError("prepare_record must bind the v3 task before freezing it")
    return messages


def prepare_record(original):
    """Prepare once before freezing; retain provenance, exposure and sample count.

    Existing outcome receipts bind the old input. Keep them only as source
    evidence; call verify_reference explicitly before using this record for SFT.
    This function performs no model generation or reference execution.
    """
    if "action_protocol_v3" in original:
        require_prepared(original)
        return copy.deepcopy(original)
    data.validate_record(original, require_outcome=False)
    record = copy.deepcopy(original)
    task = record["task"]
    messages = inference_messages(task["input"], task.get("messages"))
    if any(message["role"] == "assistant" for message in messages):
        raise ValueError("v3 preparation must precede an active conversation")
    if task["input"].count(LEGACY_ILLUSTRATION) > 1:
        raise ValueError("ambiguous legacy action illustration")
    prompt = task["input"].replace(LEGACY_ILLUSTRATION, ACTION_CONTRACT)
    if prompt == task["input"]:
        prompt += "\n" + ACTION_CONTRACT
    removed = None
    # Only the exact authored before-edit bookkeeping message is removable.
    # Genuine tool observations, including similar but different ones, survive.
    if (
        record["origin_kind"] == "curated_development"
        and len(messages) > 1
        and messages[1]["role"] == "tool"
    ):
        try:
            initial = data._parse(messages[1]["content"])
        except (ValueError, TypeError):
            initial = None
        if data.canonical(initial) == data.canonical(_INITIAL):
            removed = data.digest(messages.pop(1))
    original_messages = original["task"].get(
        "messages", [{"role": "user", "content": original["task"]["input"]}]
    )
    messages[0] = {"role": "user", "content": prompt}
    task.update(input=prompt, messages=messages)
    record["action_protocol_v3"] = {
        "schema": PROTOCOL,
        "source_record_sha256": data.digest(original),
        "source_input_sha256": data.digest(original["task"]["input"]),
        "source_messages_sha256": data.digest(original_messages),
        "source_verified_outcome": record.pop("verified_outcome", None),
        "removed_authored_before_edit_sha256": removed,
        "prepared_input_sha256": data.digest(prompt),
        "prepared_messages_sha256": data.digest(messages),
        "independent_sample_increment": 0,
    }
    require_prepared(record)
    return record


def verify_reference(prepared):
    """Rebind an authored reference, explicitly separate from student outputs."""
    require_prepared(prepared)
    record = copy.deepcopy(prepared)
    receipt = data.verify_answer(record, record["final_answer"])
    if not receipt["success"]:
        raise ValueError("prepared reference failed the original business verifier")
    record["protocol_reference_receipt"] = receipt
    record["verified_outcome"] = {
        "success": True,
        "receipt_sha256": receipt["receipt_sha256"],
        "verifier_name": "repo_patch",
        "verifier_version": "1",
    }
    data.validate_record(record)
    return record


def execution_summary(verification):
    """Derive completed original calls without relabeling attempted calls.

    The frozen worker appends calls only after the subject returns. Therefore
    an empty list cannot establish that no subject invocation was attempted.
    Control-arm calls are never included in subject_call_count.
    """
    result = verification["result"]
    measured = result.get("result") or {}
    observations = measured.get("observations") or []
    original = observations[0] if observations else {}
    if original.get("control") != "original":
        original = {}
    calls = original.get("calls")
    count = len(calls) if isinstance(calls, list) else None
    passed = original.get("passed")
    passed = passed if type(passed) is bool else None
    error = original.get("error")
    error = (
        error
        if isinstance(error, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error)
        else None
    )
    total, rejected = measured.get("control_count"), measured.get("controls_rejected")
    informative = bool(
        passed is True
        and count
        and type(total) is int
        and total > 0
        and type(rejected) is int
        and 0 <= rejected <= total
    )
    return {
        "verification_receipt_sha256": verification["receipt_sha256"],
        "execution_performed": result.get("executed", False),
        "original_passed": passed,
        "original_error_type": error,
        "subject_call_count": count,
        "subject_call_count_scope": "completed_original_calls",
        "subject_call_attempt_count": None,
        "control_comparison_informative": informative,
        "controls_rejected": rejected if informative else None,
        "control_count": total if informative else None,
    }


def feedback(verification):
    """Expose bounded parser/AST errors and test status, never fixture outputs."""
    result = verification["result"]
    summary = execution_summary(verification)
    format_error = None
    if result.get("reason") == "invalid_test_patch":
        raw = " ".join(str(result.get("feedback", "Invalid test edit")).split())
        format_error = raw.encode()[:256].decode(errors="ignore")
        instruction = (
            "Fix the validation error and return a complete replacement JSON edit."
        )
    elif summary["original_passed"] is False:
        instruction = (
            "The original failed. Check the subject arguments and assertions against "
            "the task contract. Control failures are not a meaningful score yet."
        )
    elif verification["success"]:
        instruction = "Business tests passed."
    elif summary["original_passed"] is True:
        instruction = (
            "Add contract assertions that reject the remaining wrong-output controls."
        )
    else:
        instruction = (
            "No original test result was returned. Submit a bounded replacement edit."
        )
    return data.canonical(
        {
            "success": verification["success"],
            "reason": result.get("reason", "semantic_test_result"),
            "format_error": format_error,
            **{
                key: summary[key]
                for key in (
                    "execution_performed",
                    "original_passed",
                    "original_error_type",
                    "control_comparison_informative",
                    "controls_rejected",
                    "control_count",
                )
            },
            "completed_original_calls": summary["subject_call_count"],
            "next_attempt_resets_template": True,
            "instruction": instruction,
        }
    ).decode()
