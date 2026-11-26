#!/usr/bin/env python3
"""Validate the runtime.codex machine-readable fault-injection matrix."""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/modules/runtime.codex/FAULT_INJECTION_MATRIX.json"
ID_PATTERN = re.compile(r"RCX-FI-[0-9]{3}\Z")
REQUIRED_BOUNDARIES = {
    "before_local_reservation_append",
    "after_local_reservation_fsync",
    "before_and_after_local_dispatch_fsync",
    "owner_bound_dispatch_request_or_ack_loss",
    "after_owner_dispatched_before_effect_entry",
    "after_abort_pending_fsync_before_owner_abort",
    "owner_abort_request_or_ack_loss",
    "after_owner_abort_before_local_confirm",
    "final_use_token_entry",
    "app_server_socket_write_and_turn_start_ack",
    "after_turn_started_before_native_started_fsync",
    "cancel_intent_append_and_interrupt_ack",
    "terminal_observation_append_and_owner_terminal_ack",
    "thread_unsubscribe_and_client_shutdown",
    "ephemeral_history_unavailable_after_process_loss",
}
REQUIRED_FIELDS = {
    "id",
    "boundary",
    "owner",
    "fault",
    "expectedLocalState",
    "expectedOwnerState",
    "recovery",
    "forbidden",
    "repositoryEvidence",
    "targetHostRequired",
}


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    value = json.loads(MATRIX.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.runtime-codex.fault-injection-matrix.v1":
        fail("unexpected fault matrix schema")
    if value.get("schemaVersion") != 1 or value.get("module") != "runtime.codex":
        fail("fault matrix identity mismatch")
    claim = value.get("claimBoundary")
    if not isinstance(claim, dict) or claim != {
        "repositoryTestsAreSourceEvidence": True,
        "targetHostKillEvidenceRequired": True,
        "realProviderEvidenceRequired": True,
    }:
        fail("fault matrix claim boundary must remain fail-closed")

    boundaries = value.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        fail("fault matrix boundaries must be a non-empty array")

    ids: set[str] = set()
    names: set[str] = set()
    for index, entry in enumerate(boundaries):
        if not isinstance(entry, dict):
            fail(f"boundary {index} is not an object")
        missing = REQUIRED_FIELDS - entry.keys()
        unknown = entry.keys() - (
            REQUIRED_FIELDS | {"realProviderRequired"}
        )
        if missing or unknown:
            fail(
                f"boundary {index} missing={sorted(missing)} unknown={sorted(unknown)}"
            )
        identifier = entry["id"]
        name = entry["boundary"]
        if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
            fail(f"invalid boundary id at index {index}")
        if identifier in ids or name in names:
            fail(f"duplicate fault boundary identity: {identifier}/{name}")
        ids.add(identifier)
        names.add(name)
        for field in [
            "boundary",
            "owner",
            "fault",
            "expectedLocalState",
            "expectedOwnerState",
            "recovery",
        ]:
            text = entry[field]
            if not isinstance(text, str) or not text or len(text) > 512:
                fail(f"invalid {field} for {identifier}")
        forbidden = entry["forbidden"]
        evidence = entry["repositoryEvidence"]
        if (
            not isinstance(forbidden, list)
            or not forbidden
            or not all(isinstance(item, str) and item for item in forbidden)
        ):
            fail(f"invalid forbidden outcomes for {identifier}")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(item, str) and item for item in evidence)
        ):
            fail(f"invalid repository evidence for {identifier}")
        for relative in evidence:
            path = ROOT / relative
            if not path.is_file():
                fail(f"missing repository evidence {relative} for {identifier}")
        if entry["targetHostRequired"] is not True:
            fail(f"{identifier} incorrectly self-certifies target-host evidence")
        if "realProviderRequired" in entry and entry["realProviderRequired"] is not True:
            fail(f"{identifier} has an invalid real-provider gate")

    missing_boundaries = REQUIRED_BOUNDARIES - names
    if missing_boundaries:
        fail(f"fault matrix omitted required boundaries: {sorted(missing_boundaries)}")

    expected_ids = {f"RCX-FI-{index:03d}" for index in range(1, len(ids) + 1)}
    if ids != expected_ids:
        fail("fault matrix IDs must be contiguous and stable")

    print(
        json.dumps(
            {
                "module": "runtime.codex",
                "validatedBoundaries": len(boundaries),
                "targetHostEvidenceRequired": True,
                "realProviderEvidenceRequired": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"runtime.codex fault matrix invalid: {error}", file=sys.stderr)
        raise SystemExit(1)
