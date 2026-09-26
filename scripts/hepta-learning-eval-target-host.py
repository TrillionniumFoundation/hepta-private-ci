#!/usr/bin/env python3
"""Verify externally issued target-host evidence for learning.eval.

The verifier checks structure, candidate identity, time ordering, evidence
completeness and actor separation. It never creates evidence and never upgrades a
claim from repository source or CI facts alone.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HEX32 = re.compile(r"[0-9a-f]{64}")
SHA1 = re.compile(r"[0-9a-f]{40}")


class EvidenceError(ValueError):
    pass


def load(path: Path) -> dict[str, Any]:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise EvidenceError("evidence manifest must be an object")
    return value


def digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or HEX32.fullmatch(value) is None or value == "0" * 64:
        raise EvidenceError(f"{name} must be a nonzero lowercase SHA-256 digest")
    return value


def identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise EvidenceError(f"{name} must be a bounded nonempty identity")
    return value


def boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise EvidenceError(f"{name} must be boolean")
    return value


def positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise EvidenceError(f"{name} must be a positive integer")
    return value


def array(value: Any, name: str, minimum: int = 1) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise EvidenceError(f"{name} must contain at least {minimum} entries")
    return value


def object_(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{name} must be an object")
    return value


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def validate_candidate(candidate: dict[str, Any], require_current: bool) -> None:
    sha = candidate.get("commit")
    tree = candidate.get("tree")
    if not isinstance(sha, str) or SHA1.fullmatch(sha) is None:
        raise EvidenceError("candidate.commit must be a literal SHA-1")
    if not isinstance(tree, str) or SHA1.fullmatch(tree) is None:
        raise EvidenceError("candidate.tree must be a literal SHA-1")
    digest(candidate.get("cargoLockDigest"), "candidate.cargoLockDigest")
    digest(candidate.get("productionContractDigest"), "candidate.productionContractDigest")
    digest(candidate.get("currentStatusDigest"), "candidate.currentStatusDigest")
    if require_current:
        if git("rev-parse", "HEAD") != sha or git("rev-parse", "HEAD^{tree}") != tree:
            raise EvidenceError("manifest is not bound to the current candidate")


def validate_windows(longitudinal: dict[str, Any]) -> None:
    windows = array(longitudinal.get("windows"), "longitudinal.windows", 2)
    seen_ids: set[str] = set()
    seen_cuts: set[str] = set()
    ordered: list[tuple[int, int]] = []
    for index, raw in enumerate(windows):
        row = object_(raw, f"longitudinal.windows[{index}]")
        window_id = identity(row.get("windowId"), f"windows[{index}].windowId")
        if window_id in seen_ids:
            raise EvidenceError("duplicate future-window identity")
        seen_ids.add(window_id)
        start = positive_int(row.get("startMicros"), f"windows[{index}].startMicros")
        end = positive_int(row.get("endMicros"), f"windows[{index}].endMicros")
        observed = positive_int(row.get("observedAtMicros"), f"windows[{index}].observedAtMicros")
        if not start < end <= observed:
            raise EvidenceError("future-window time ordering is invalid")
        positive_int(row.get("observedCount"), f"windows[{index}].observedCount")
        source_cut = digest(row.get("sourceCutDigest"), f"windows[{index}].sourceCutDigest")
        digest(row.get("outcomeEvidenceDigest"), f"windows[{index}].outcomeEvidenceDigest")
        digest(row.get("observerAttestationDigest"), f"windows[{index}].observerAttestationDigest")
        if source_cut in seen_cuts:
            raise EvidenceError("future windows must bind distinct source cuts")
        seen_cuts.add(source_cut)
        ordered.append((start, end))
    ordered.sort()
    for left, right in zip(ordered, ordered[1:]):
        if left[1] > right[0]:
            raise EvidenceError("future windows overlap")

    snapshots = array(longitudinal.get("snapshotIds"), "longitudinal.snapshotIds", 3)
    if len(set(snapshots)) != len(snapshots) or any(
        not isinstance(value, str) or not value for value in snapshots
    ):
        raise EvidenceError("snapshot identities must be distinct nonempty strings")
    for field in (
        "retentionEvidenceDigest",
        "changePointEvidenceDigest",
        "powerAnalysisDigest",
        "subgroupPrivacyReviewDigest",
        "unlearningEvidenceDigest",
        "backupNonResurrectionDigest",
    ):
        digest(longitudinal.get(field), f"longitudinal.{field}")


def validate_manifest(value: dict[str, Any], require_current: bool) -> dict[str, Any]:
    if value.get("schema") != "hepta.learning-eval.target-host-evidence.v1":
        raise EvidenceError("unexpected target-host evidence schema")
    validate_candidate(object_(value.get("candidate"), "candidate"), require_current)

    host = object_(value.get("host"), "host")
    for field in (
        "hostProfileDigest",
        "osKernelDigest",
        "filesystemProfileDigest",
        "clockProfileDigest",
        "resourceMeasurementDigest",
    ):
        digest(host.get(field), f"host.{field}")
    identity(host.get("hostId"), "host.hostId")

    trust = object_(value.get("trust"), "trust")
    for field in (
        "distributionDigest",
        "revocationSnapshotDigest",
        "authorityEpochDigest",
    ):
        digest(trust.get(field), f"trust.{field}")

    storage = object_(value.get("storage"), "storage")
    for field in (
        "holdoutNamespaceDigest",
        "holdoutAnchorStoreDigest",
        "publicationStoreDigest",
        "attemptJournalDigest",
        "faultInjectionReportDigest",
        "storageProfileDigest",
    ):
        digest(storage.get(field), f"storage.{field}")
    required_storage = (
        "linearizableCasQualified",
        "fsyncQualified",
        "anchorIndependent",
        "acceptedUnknownReconciled",
        "staleWriterRejected",
        "rollbackRestoreRejected",
        "crashRecoveryQualified",
    )
    storage_flags = {field: boolean(storage.get(field), f"storage.{field}") for field in required_storage}
    cross_host = boolean(storage.get("crossHostQualified"), "storage.crossHostQualified")
    if cross_host:
        digest(storage.get("crossHostQualificationDigest"), "storage.crossHostQualificationDigest")

    longitudinal = object_(value.get("longitudinal"), "longitudinal")
    validate_windows(longitudinal)

    acceptance = object_(value.get("acceptance"), "acceptance")
    roles = {
        field: identity(acceptance.get(field), f"acceptance.{field}")
        for field in (
            "generatorPrincipal",
            "evaluatorPrincipal",
            "observerPrincipal",
            "semanticReviewerPrincipal",
            "operatorPrincipal",
            "selectorPrincipal",
            "releasePrincipal",
        )
    }
    if len(set(roles.values())) != len(roles):
        raise EvidenceError("external evidence roles must be pairwise distinct")
    for field in (
        "semanticAcceptanceDigest",
        "operatorAcceptanceDigest",
        "canaryEvidenceDigest",
        "selectionDecisionDigest",
        "promotionDecisionDigest",
        "releaseAuthorizationDigest",
    ):
        digest(acceptance.get(field), f"acceptance.{field}")

    claims = object_(value.get("claims"), "claims")
    target_host = boolean(claims.get("targetHostQualified"), "claims.targetHostQualified")
    independent = boolean(claims.get("independentAcceptance"), "claims.independentAcceptance")
    production = boolean(claims.get("productionQualified"), "claims.productionQualified")
    activation = boolean(claims.get("activationAuthorized"), "claims.activationAuthorized")
    release = boolean(claims.get("releaseAuthorized"), "claims.releaseAuthorized")

    if target_host and (not all(storage_flags.values()) or not cross_host):
        raise EvidenceError("target-host claim exceeds storage qualification")
    if independent and not target_host:
        raise EvidenceError("independent acceptance requires target-host qualification")
    if production and not (target_host and independent):
        raise EvidenceError("production qualification requires target-host and independent acceptance")
    if activation and not production:
        raise EvidenceError("activation authorization requires production qualification")
    if release and not (production and activation):
        raise EvidenceError("release authorization requires production qualification and activation")

    return {
        "schema": "hepta.learning-eval.target-host-verification.v1",
        "candidateCommit": value["candidate"]["commit"],
        "targetHostQualified": target_host,
        "independentAcceptance": independent,
        "productionQualified": production,
        "activationAuthorized": activation,
        "releaseAuthorized": release,
    }


def self_test() -> None:
    bad = {
        "schema": "hepta.learning-eval.target-host-evidence.v1",
        "candidate": {},
    }
    try:
        validate_manifest(bad, False)
    except EvidenceError:
        pass
    else:
        raise SystemExit("target-host verifier self-test accepted incomplete evidence")
    print(json.dumps({"status": "ok", "test": "reject_incomplete_evidence"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--require-current-candidate", action="store_true")
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return
    try:
        result = validate_manifest(load(args.manifest), args.require_current_candidate)
    except (EvidenceError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
