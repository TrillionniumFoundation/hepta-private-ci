"""Stable, bounded feedback for new runs; raw verifier records stay unchanged."""

from .. import data
from ..protocol_v3 import execution_summary

SCHEMA = "hepta.stable-repository-feedback.v1"
_ERRORS = {
    "expected edits object": "EXPECTED_EDITS_OBJECT",
    "one test-file edit required": "ONE_TEST_EDIT_REQUIRED",
    "invalid bounded test edit": "INVALID_TEST_EDIT",
    "test AST exceeds bound": "TEST_AST_LIMIT",
    "test must contain only one to twelve assertions": "ASSERTIONS_ONLY",
    "only reviewed subject calls are allowed": "SUBJECT_CALLS_ONLY",
    "literal positional subject arguments required": "LITERAL_ARGUMENTS_REQUIRED",
    "unsupported assertion comparison": "UNSUPPORTED_COMPARISON",
    "tests must call the actual subject": "SUBJECT_CALL_REQUIRED",
    "assertion literal exceeds bound": "LITERAL_SIZE_LIMIT",
    "assertion literal nesting exceeds bound": "LITERAL_DEPTH_LIMIT",
    "assertion numeric literal exceeds bound": "LITERAL_MAGNITUDE_LIMIT",
    "assertion collection exceeds bound": "LITERAL_COLLECTION_LIMIT",
}


def feedback(verification):
    """Expose only fixed error codes and observed counts, never raw exceptions."""
    if type(verification.get("success")) is not bool:
        raise ValueError("a measured verification result is required")
    result = verification["result"]
    summary = execution_summary(verification)
    reason = result.get("reason")
    if reason not in {
        "invalid_test_patch", "test_timeout", "business_tests_passed", "business_tests_failed"
    }:
        reason = "semantic_test_result"
    code = None
    if reason == "invalid_test_patch":
        raw = result.get("feedback", "")
        raw = raw if isinstance(raw, str) else ""
        code = _ERRORS.get(raw, "INVALID_TEST_PATCH")
        if raw.startswith("malformed node or string"):
            code = "NON_LITERAL_EXPRESSION"
        instruction = "Return a complete bounded JSON edit with literal arguments and assertions."
    elif summary["original_passed"] is False:
        instruction = "Check subject arguments and assertions against the visible task contract."
    elif verification["success"]:
        instruction = "Business tests passed."
    elif summary["original_passed"] is True:
        instruction = "Add assertions rejecting the remaining wrong-output controls."
    else:
        instruction = "No original result was returned; submit a bounded replacement edit."
    return data.canonical({
        "schema": SCHEMA, "success": verification["success"], "reason": reason,
        "error_code": code,
        **{key: summary[key] for key in (
            "execution_performed", "original_passed", "original_error_type",
            "control_comparison_informative", "controls_rejected", "control_count",
        )},
        "completed_original_calls": summary["subject_call_count"],
        "next_attempt_resets_template": True, "instruction": instruction,
    }).decode()
