"""Fail-closed identities for the exact libtest cases behind authority claims.

This parser consumes captured (not --nocapture), uncoloured, single-threaded
libtest pretty output. A successful cargo exit is necessary, never sufficient.
No production, deployment, or independent-acceptance claim is granted here.
"""
from __future__ import annotations

import re
from typing import Any

EXPECTED_TESTS: dict[str, tuple[str, ...]] = {
    "fleet-create-restart-revoke": (
        "authority_port::tests::allocation_issue_consumes_exact_live_kernel_authority_lease",
    ),
    "browser-agentd-final-use-boundary": (
        "browser_servo::tests::final_use_fence_covers_exactly_the_browser_local_dispatch_boundary",
    ),
    "agentd-effect-owner-restart-and-receipt": (
        "automation_effect_host::tests::host_dispatches_exact_wire_payload_once",
    ),
    "external-frontier-snapshot-rollback": (
        "authority_trust_host::tests::restored_local_authority_snapshot_is_rejected_by_external_frontier",
    ),
    "pending-revocation-admission-fence": (
        "final_use::tests::pending_revocation_preserves_the_observed_head_until_commit",
    ),
    "pending-revocation-crash-recovery-matrix": (
        "unix::pending_revocation_survives_restart_and_commits_exactly",
        "unix::recovery_closes_both_frontier_first_crash_windows",
    ),
    "issuer-key-overlap-and-retirement": (
        "final_use::tests::issuer_key_ring_supports_overlap_and_epoch_retirement",
    ),
    "frontier-ahead-local-commit-failure": (
        "final_use::tests::external_final_use_frontier_ahead_after_local_failure_fences_reopen",
    ),
}
_RESULT = re.compile(r"^test ([A-Za-z_][A-Za-z0-9_:]*) \.\.\. (ok|FAILED|ignored(?:,.*)?)$")
_SUMMARY = re.compile(
    r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
    r"(\d+) measured; (\d+) filtered out; finished in .+$"
)


class ExecutionError(ValueError):
    """An expected test did not actually execute and pass exactly once."""


def validate_output(text: str, expected: tuple[str, ...]) -> dict[str, Any]:
    if not expected or len(set(expected)) != len(expected):
        raise ExecutionError("expected test identities must be nonempty and unique")
    observed: dict[str, str] = {}
    totals = [0, 0, 0, 0]
    summaries = 0
    for line in text.splitlines():
        match = _RESULT.fullmatch(line)
        if match:
            name, result = match.groups()
            if name in observed:
                raise ExecutionError(f"duplicate execution: {name}")
            observed[name] = result
            continue
        match = _SUMMARY.fullmatch(line)
        if match:
            status, passed, failed, ignored, measured, _filtered = match.groups()
            if status != "ok":
                raise ExecutionError("test suite reported failure")
            totals = [a + int(b) for a, b in zip(totals, (passed, failed, ignored, measured))]
            summaries += 1
    if not summaries or set(observed) != set(expected):
        raise ExecutionError("missing, renamed, filtered, or unexpected test identity")
    if any(result != "ok" for result in observed.values()):
        raise ExecutionError("a required test failed or was ignored")
    if totals != [len(expected), 0, 0, 0]:
        raise ExecutionError("test summaries disagree with the exact executed identities")
    return {
        "schema": "hepta.kernel-authority-test-execution.v1",
        "expectedTests": list(expected),
        "passedTests": sorted(observed),
        "passedCount": len(expected),
        "failedCount": 0,
        "ignoredCount": 0,
        "measuredCount": 0,
        "suiteSummaries": summaries,
    }


def checked_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """Pin output/capture settings without changing package or test selection."""
    if command[:2] != ("cargo", "test") or "--" not in command:
        raise ExecutionError("a pilot must run an explicit cargo test selection")
    separator = command.index("--")
    cargo = command[:separator]
    harness = tuple(arg for arg in command[separator + 1:] if arg != "--nocapture")
    if any(arg.startswith(("--format", "--color", "--test-threads")) for arg in harness):
        raise ExecutionError("pilot output flags must be owned by the qualification runner")
    return (*cargo, "--", *harness, "--format=pretty", "--color=never", "--test-threads=1")


def validate_receipt(value: Any, expected: tuple[str, ...]) -> bool:
    """Check an execution projection; the caller must separately bind its log."""
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "schema", "expectedTests", "passedTests", "passedCount", "failedCount",
        "ignoredCount", "measuredCount", "suiteSummaries",
    }:
        return False
    if value["schema"] != "hepta.kernel-authority-test-execution.v1":
        return False
    if value["expectedTests"] != list(expected) or value["passedTests"] != sorted(expected):
        return False
    for key, target in (("passedCount", len(expected)), ("failedCount", 0),
                        ("ignoredCount", 0), ("measuredCount", 0)):
        if type(value[key]) is not int or value[key] != target:
            return False
    return type(value["suiteSummaries"]) is int and value["suiteSummaries"] > 0
