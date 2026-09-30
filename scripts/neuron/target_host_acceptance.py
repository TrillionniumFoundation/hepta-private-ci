#!/usr/bin/env python3
"""Validate externally produced neuron.runtime target-host evidence.

The validator authenticates structure and exact-candidate bindings. It does not
attest that a local file came from a trusted runner; the workflow/job identity,
retained logs and independent reviewer remain external trust inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "hepta.neuron.runtime.target-host-acceptance.v1"
MANIFEST_SCHEMA = "hepta.neuron.runtime.target-host-manifest.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_ARTIFACT_DIGESTS = (
    "modelManifestSha256",
    "weightsSha256",
    "tokenizerSha256",
    "preprocessorSha256",
    "quantizationSha256",
    "runtimeSha256",
)
REQUIRED_DURABLE_CUTS = (
    "reservation",
    "dispatchFence",
    "modelObservation",
    "storeCommit",
    "indexCompletion",
    "witnessAcknowledgement",
)
REQUIRED_FAULTS = (
    "enospc",
    "syncFailure",
    "parentDirectorySyncFailure",
    "namespaceReplacement",
    "symlinkHardlinkFifoRace",
    "ownerPanicReconstruction",
    "providerTimeoutUnknown",
    "interruptedReloadPublication",
    "concurrentDrain",
    "longHorizonGrowth",
    "backupRestoreHistory",
)
REQUIRED_LIFECYCLE = (
    "agentdStartup",
    "providerExecution",
    "freshProcessReopen",
    "exactReconciliation",
    "guardedResultUse",
    "quiesce",
    "seal",
    "reloadSuccessor",
)


class EvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def require_string(value: Any, name: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{name} must be non-empty")
    return value


def require_sha256(value: Any, name: str) -> str:
    value = require_string(value, name)
    require(HEX64.fullmatch(value) is not None, f"{name} must be lowercase sha256")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate_receipt(
    receipt: dict[str, Any], expected_source: str, expected_base: str
) -> dict[str, Any]:
    require(HEX40.fullmatch(expected_source) is not None, "invalid expected source SHA")
    require(HEX40.fullmatch(expected_base) is not None, "invalid expected base SHA")
    require(receipt.get("schema") == SCHEMA, "unexpected receipt schema")
    require(receipt.get("sourceSha") == expected_source, "source SHA mismatch")
    require(receipt.get("baseSha") == expected_base, "base SHA mismatch")
    require(receipt.get("sourceMutation") is False, "target run mutated source")
    require(receipt.get("productionActivation") is False, "receipt activated production")
    require(receipt.get("release") is False, "receipt authorized release")

    require_sha256(receipt.get("testedTreeSha256"), "testedTreeSha256")
    require_sha256(receipt.get("binarySha256"), "binarySha256")
    require_string(receipt.get("workflowRunId"), "workflowRunId")
    require(isinstance(receipt.get("workflowRunAttempt"), int), "workflowRunAttempt must be int")
    require(receipt["workflowRunAttempt"] > 0, "workflowRunAttempt must be positive")

    environment = require_mapping(receipt.get("environment"), "environment")
    for key in ("runnerName", "runnerImage", "kernel", "targetTriple", "deviceIdentity"):
        require_string(environment.get(key), f"environment.{key}")

    artifacts = require_mapping(receipt.get("authenticatedArtifacts"), "authenticatedArtifacts")
    for key in REQUIRED_ARTIFACT_DIGESTS:
        require_sha256(artifacts.get(key), f"authenticatedArtifacts.{key}")
    require_string(artifacts.get("selectionAuthority"), "authenticatedArtifacts.selectionAuthority")
    require(artifacts.get("revocationChecked") is True, "artifact revocation was not checked")

    operation = require_mapping(receipt.get("operation"), "operation")
    for key in ("tickId", "inputDigest", "providerOperationId"):
        require_string(operation.get(key), f"operation.{key}")
    require(isinstance(operation.get("generation"), int), "operation.generation must be int")
    require(operation["generation"] > 0, "operation.generation must be positive")

    provider = require_mapping(receipt.get("provider"), "provider")
    require_string(provider.get("backend"), "provider.backend")
    require_sha256(provider.get("receiptSha256"), "provider.receiptSha256")
    require(provider.get("queryOnlyRecovery") is True, "provider recovery was not query-only")
    require(provider.get("physicalEffectCount") == 1, "provider effect count was not exactly one")
    require(provider.get("duplicateEffectCount") == 0, "provider duplicate effect observed")

    cuts = require_mapping(receipt.get("durableCuts"), "durableCuts")
    require(set(cuts) == set(REQUIRED_DURABLE_CUTS), "durable cut set mismatch")
    for cut in REQUIRED_DURABLE_CUTS:
        outcome = require_mapping(cuts[cut], f"durableCuts.{cut}")
        require(outcome.get("status") == "passed", f"durable cut {cut} did not pass")
        require(outcome.get("freshProcessRestart") is True, f"{cut} did not use fresh process")
        require(outcome.get("exactOperationKeyStable") is True, f"{cut} changed operation key")
        require(outcome.get("physicalEffectCount") == 1, f"{cut} effect count mismatch")
        require_sha256(outcome.get("logSha256"), f"durableCuts.{cut}.logSha256")

    lifecycle = require_mapping(receipt.get("lifecycle"), "lifecycle")
    require(set(lifecycle) == set(REQUIRED_LIFECYCLE), "lifecycle step set mismatch")
    for step in REQUIRED_LIFECYCLE:
        require(lifecycle.get(step) is True, f"lifecycle step {step} did not pass")

    faults = require_mapping(receipt.get("faultMatrix"), "faultMatrix")
    require(set(faults) == set(REQUIRED_FAULTS), "fault matrix set mismatch")
    for fault in REQUIRED_FAULTS:
        outcome = require_mapping(faults[fault], f"faultMatrix.{fault}")
        require(outcome.get("status") == "passed", f"fault {fault} did not pass")
        require_sha256(outcome.get("logSha256"), f"faultMatrix.{fault}.logSha256")

    retention = require_mapping(receipt.get("retention"), "retention")
    for key in (
        "successHistoryRetained",
        "failureTombstonesRetained",
        "dispatchHistoryRetained",
        "witnessLineageRetained",
        "historicalQueriesPassed",
        "deletionNonResurrectionPassed",
    ):
        require(retention.get(key) is True, f"retention.{key} did not pass")

    rollback = require_mapping(receipt.get("rollbackBoundary"), "rollbackBoundary")
    require(
        rollback.get("gapId") == "NR-SEC-ROLLBACK-001",
        "rollback gap identity mismatch",
    )
    require(
        rollback.get("disposition") in {"closed_by_independent_anchor", "accepted_exclusion"},
        "rollback gap remains open",
    )
    require_string(rollback.get("evidenceReference"), "rollbackBoundary.evidenceReference")

    independent = require_mapping(receipt.get("independentReview"), "independentReview")
    require_string(independent.get("reviewerIdentity"), "independentReview.reviewerIdentity")
    independent_accepted = independent.get("accepted") is True
    require_sha256(independent.get("reviewSha256"), "independentReview.reviewSha256")

    evidence_hash = hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    return {
        "schema": MANIFEST_SCHEMA,
        "sourceSha": expected_source,
        "baseSha": expected_base,
        "testedTreeSha256": receipt["testedTreeSha256"],
        "binarySha256": receipt["binarySha256"],
        "workflowRunId": receipt["workflowRunId"],
        "workflowRunAttempt": receipt["workflowRunAttempt"],
        "targetTriple": environment["targetTriple"],
        "deviceIdentity": environment["deviceIdentity"],
        "providerBackend": provider["backend"],
        "operation": operation,
        "receiptSha256": evidence_hash,
        "durableCutsPassed": list(REQUIRED_DURABLE_CUTS),
        "faultsPassed": list(REQUIRED_FAULTS),
        "productExecutionProved": True,
        "independentAcceptance": independent_accepted,
        "productionActivation": False,
        "release": False,
    }


def command_validate(args: argparse.Namespace) -> None:
    receipt_path = Path(args.receipt)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require_mapping(receipt, "receipt")
    manifest = validate_receipt(receipt, args.source_sha, args.base_sha)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subcommands = result.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("--receipt", required=True)
    validate.add_argument("--source-sha", required=True)
    validate.add_argument("--base-sha", required=True)
    validate.add_argument("--output", required=True)
    validate.set_defaults(handler=command_validate)
    return result


def main() -> None:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (EvidenceError, json.JSONDecodeError, OSError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
