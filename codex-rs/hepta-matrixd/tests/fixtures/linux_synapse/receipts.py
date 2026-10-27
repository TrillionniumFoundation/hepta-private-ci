"""Fresh exact-test JUnit and original nonce-bound business completion evidence."""

from pathlib import Path
import xml.etree.ElementTree as ET

from .contract import TEST_BINARY_ID, TEST_NAME
from .files import SHA256, describe, read_json


def junit(path):
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    if len(cases) != 1 or cases[0].get("name") != TEST_NAME:
        raise ValueError(
            "Fresh JUnit must contain exactly the original Synapse business test"
        )
    case = cases[0]
    if any(
        case.find(name) is not None
        for name in (
            "failure",
            "error",
            "skipped",
            "flakyFailure",
            "flakyError",
            "rerunFailure",
            "rerunError",
        )
    ):
        raise ValueError(
            "JUnit records a failed, errored or skipped real qualification"
        )
    if case.get("classname") not in {
        TEST_BINARY_ID,
        "codex-hepta-matrixd.real_synapse_e2e",
    }:
        raise ValueError(
            "JUnit does not identify the actual original integration binary"
        )
    for suite in (
        item for item in root.iter() if item.tag in {"testsuite", "testsuites"}
    ):
        for name in ("failures", "errors", "skipped", "disabled"):
            if int(suite.get(name, "0")) != 0:
                raise ValueError("JUnit suite contains unsuccessful cases")
        if int(suite.get("tests", "1")) != 1:
            raise ValueError("JUnit suite count differs from the exact single test")
    return {
        "path": str(path),
        **describe(path),
        "test_name": TEST_NAME,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "retries": 0,
    }


def completion(path, nonce, source_seal, fixture):
    value = read_json(path)
    expected = {
        "schema_version": 2,
        "test_name": TEST_NAME,
        "nonce": nonce,
        "qualification_mode": "linux_exact",
        "candidate_sha": source_seal["qualification_commit"],
        "candidate_tree_sha": source_seal["qualification_tree"],
        "source_clean": True,
        "test_assertions_passed": True,
        "runner_revalidation_required": True,
        "runtime_root_removed": True,
        "credential_capabilities_removed": True,
        "promotable": False,
        "wire_put_attempts": 2,
        "agent_a_provider_requests": 5,
        "agent_b_provider_requests": 3,
        "release_copy_identity_rechecked_at_lifecycle_boundaries": True,
        "release_execve_atomic_binding": False,
        "explicit_product_shutdown_completed": True,
        "all_historical_product_pids_absent": True,
    }
    if {key: value.get(key) for key in expected} != expected:
        raise ValueError(
            "Original business completion/nonce/count/source evidence failed Linux qualification"
        )
    if (fixture / "credentials").exists() or (fixture / "runtime").exists():
        raise ValueError(
            "Read-once credentials or business runtime survived qualification"
        )
    ledger = read_json(fixture / "process-identity-ledger.json")
    if (
        ledger.get("schema_version") != 1
        or ledger.get("active") != []
        or ledger.get("history") != value.get("process_history")
        or not ledger.get("explicit_shutdown_completed")
        or not ledger.get("all_historical_pids_absent")
        or len(ledger["history"]) < 4
    ):
        raise ValueError("Original persisted process identity/shutdown history differs")
    observations = value.get("release_copy_observations", [])
    if (
        len(observations) < 13
        or not value.get("stable_txn_id")
        or not value.get("synapse_event_id")
        or not value.get("expected_put_target")
    ):
        raise ValueError(
            "Original release/transaction/fault-recovery observations are incomplete"
        )
    for observation in observations:
        for plane in ("agentd", "matrixd"):
            identity = observation["identity"][plane]
            if not SHA256.fullmatch(identity["sha256"]) or any(
                identity[key] <= 0 for key in ("device_id", "inode", "size_bytes")
            ):
                raise ValueError(
                    "Release copy observation lacks its actual physical executable identity"
                )
    return {
        "path": str(path),
        **describe(path),
        "test_assertions_passed": True,
        "scope": "native-linux-arm64",
        "release_copy_observations": len(observations),
        "process_history_records": len(ledger["history"]),
        "promotion_allowed": False,
    }
