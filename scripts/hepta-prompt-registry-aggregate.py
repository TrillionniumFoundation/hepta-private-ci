#!/usr/bin/env python3
"""Aggregate four exact-run receipts without crossing acceptance boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

LANES = {(profile, lane) for profile in ("core", "product") for lane in ("exact-head", "base-merge")}
COMMON = {
    "clean-before", "harness-tests", "public-api-map", "toolchain", "format",
    "dependency-prime", "source-graph", "all-targets", "lint", "clean-after",
}
REQUIRED = {
    "core": COMMON | {"registry-inventory", "registry", "operational-profiles"},
    "product": COMMON | {"agentd-inventory", "extension-inventory", "optimizer", "extension", "agentd", "pipeline-profile"},
}
HEX40 = re.compile(r"[a-f0-9]{40}")
HEX64 = re.compile(r"[a-f0-9]{64}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def artifact_content_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(entry for entry in directory.rglob("*") if entry.is_file())
    if not files:
        raise ValueError("empty lane artifact")
    for entry in files:
        if entry.is_symlink():
            raise ValueError("lane artifact contains a symlink")
        relative = entry.relative_to(directory).as_posix().encode()
        payload_digest = hashlib.sha256(entry.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(payload_digest)
    return digest.hexdigest()


def single(receipts: dict, field: str):
    values = {json.dumps(receipt.get(field), sort_keys=True) for receipt in receipts.values()}
    if len(values) != 1:
        raise ValueError("four lanes disagree on " + field)
    value = next(iter(receipts.values())).get(field)
    if value is None:
        raise ValueError("four lanes omit " + field)
    return value


def verify_artifacts(directory: Path, receipt: dict) -> None:
    expected = receipt.get("artifactHashes")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("artifact hash manifest missing")
    actual: dict[str, str] = {}
    for path in sorted(entry for entry in directory.rglob("*") if entry.is_file()):
        relative = path.relative_to(directory).as_posix()
        if relative == "receipt.json":
            continue
        if path.is_symlink():
            raise ValueError("lane artifact contains symlink")
        actual[relative] = sha256_bytes(path.read_bytes())
    if actual != expected:
        raise ValueError("artifact hash manifest mismatch")


def verify_attempts(directory: Path, check: dict) -> None:
    attempts = check.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("check attempt history missing")
    if len(attempts) > 1 and check.get("name") != "dependency-prime":
        raise ValueError("only dependency priming may retry")
    for position, attempt in enumerate(attempts, 1):
        if attempt.get("attempt") != position:
            raise ValueError("non-contiguous retry history")
        log_name = attempt.get("log")
        log = directory / str(log_name)
        if not log.is_file() or log.is_symlink() or sha256_bytes(log.read_bytes()) != attempt.get("logSha256"):
            raise ValueError("attempt log missing or digest mismatch")
        if position < len(attempts) and attempt.get("transientNetworkFailure") is not True:
            raise ValueError("retry was not justified by a transport failure")
    if attempts[-1].get("exitCode") != check.get("exitCode"):
        raise ValueError("final attempt and check exit disagree")
    if check.get("firstAttemptExitCode") != attempts[0].get("exitCode"):
        raise ValueError("first attempt summary mismatch")
    if check.get("finalAttemptExitCode") != attempts[-1].get("exitCode"):
        raise ValueError("final attempt summary mismatch")
    if check.get("retried") is not (len(attempts) > 1):
        raise ValueError("retry summary mismatch")


def aggregate(root: Path, source: str, base: str, run: str, attempt: str) -> dict:
    receipts: dict[tuple[str, str], dict] = {}
    receipt_digests: dict[str, str] = {}
    artifact_digests: dict[str, str] = {}
    for receipt_path in sorted(root.glob("*/receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        key = (receipt.get("profile"), receipt.get("lane"))
        if key not in LANES or key in receipts:
            raise ValueError("unknown or duplicate qualification lane")
        if receipt.get("schema") != "hepta.prompt-registry.qualification-receipt.v3":
            raise ValueError("unsupported qualification receipt")
        for name, expected in [
            ("candidateSha", source), ("sourceSha", source), ("baseSha", base),
            ("runId", run), ("runAttempt", attempt),
            ("workflowRunId", run), ("workflowRunAttempt", attempt),
        ]:
            if str(receipt.get(name)) != expected:
                raise ValueError("receipt identity or run attempt mismatch: " + name)
        for name in ("candidateSha", "sourceSha", "baseSha", "testedSha", "testedTree", "sourceTreeHash", "workflowSha"):
            if not HEX40.fullmatch(str(receipt.get(name, ""))):
                raise ValueError("invalid exact identity: " + name)
        for name in (
            "dependencyLockSha256", "cargoLockSha256", "workflowFileSha256",
            "implementationMapSha256", "documentationHash", "sourceManifestSha256",
            "featureProfileSha256", "testSetSha256", "runnerImageIdentitySha256",
            "livePublicApiMapSha256",
        ):
            if not HEX64.fullmatch(str(receipt.get(name, ""))):
                raise ValueError("invalid evidence digest: " + name)
        if receipt["dependencyLockSha256"] != receipt["cargoLockSha256"]:
            raise ValueError("Cargo.lock aliases disagree")
        if canonical_sha(receipt.get("runner")) != receipt["runnerImageIdentitySha256"]:
            raise ValueError("runner image identity digest mismatch")
        if canonical_sha(receipt.get("documentationManifest")) != receipt["documentationHash"]:
            raise ValueError("documentation manifest digest mismatch")
        if canonical_sha(receipt.get("sourceFiles")) != receipt["sourceManifestSha256"]:
            raise ValueError("source manifest digest mismatch")
        if canonical_sha(receipt.get("featureProfile")) != receipt["featureProfileSha256"]:
            raise ValueError("feature profile digest mismatch")
        if receipt.get("workflowRef") in (None, "") or receipt.get("targetTriple") in (None, ""):
            raise ValueError("missing workflow or target identity")
        runner = receipt.get("runner")
        if not isinstance(runner, dict) or runner.get("targetTriple") != receipt["targetTriple"]:
            raise ValueError("invalid runner identity")
        if key[1] == "exact-head":
            if receipt["testedSha"] != source or receipt.get("deterministicMergeSha") is not None:
                raise ValueError("wrong exact-head candidate")
        else:
            if receipt.get("deterministicMergeSha") != receipt["testedSha"]:
                raise ValueError("synthetic merge identity mismatch")
        if receipt.get("allRequiredChecksPassed") is not True:
            raise ValueError("lane did not pass every required check")
        if receipt.get("firstFailure") is not None:
            raise ValueError("passing receipt retained a first failure")
        if any(receipt.get(name) is not False for name in (
            "qualified", "mergeReady", "productionReady", "productActivated", "accepted", "released",
            "kmsHsmQualified", "wormRetentionQualified", "multiNodeQualified",
        )):
            raise ValueError("lane crossed its claim boundary")
        checks = receipt.get("checks", [])
        if len(checks) != len(REQUIRED[key[0]]) or {check.get("name") for check in checks} != REQUIRED[key[0]]:
            raise ValueError("missing or unexpected required checks")
        for check in checks:
            if check.get("state") != "passed" or check.get("exitCode") != 0 or check.get("postconditionFailures") != []:
                raise ValueError("failed, interrupted, blocked or skipped check")
            log = receipt_path.parent / (check["name"] + ".log")
            if not log.is_file() or log.is_symlink() or sha256_bytes(log.read_bytes()) != check.get("logSha256"):
                raise ValueError("raw log missing or digest mismatch")
            verify_attempts(receipt_path.parent, check)
        expected_test_set = canonical_sha([
            {"name": row["name"], "command": row["command"],
             "required": row.get("required", []), "minimumPassed": row.get("minimumPassed", 0),
             "networkPrime": row["name"] == "dependency-prime"}
            for row in checks
        ])
        if expected_test_set != receipt["testSetSha256"]:
            raise ValueError("test-set digest mismatch")
        verify_artifacts(receipt_path.parent, receipt)
        live_path = receipt_path.parent / "live-public-api-map.json"
        live_map = json.loads(live_path.read_text(encoding="utf-8"))
        if sha256_bytes(live_path.read_bytes()) != receipt["livePublicApiMapSha256"]:
            raise ValueError("live map digest mismatch")
        if live_map.get("candidateSha") != receipt["testedSha"] or live_map.get("sourceTreeHash") != receipt["testedTree"]:
            raise ValueError("live map source identity mismatch")
        if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
            raise ValueError("closed-world or legacy purge evidence failed")
        if live_map.get("productionReady") is not False or live_map.get("mergeReady") is not False:
            raise ValueError("live map crossed production claim boundary")
        receipts[key] = receipt
        label = "/".join(key)
        receipt_digests[label] = sha256_bytes(receipt_path.read_bytes())
        artifact_digests[label] = artifact_content_digest(receipt_path.parent)
    if set(receipts) != LANES:
        raise ValueError("all four lanes are mandatory")
    workflow_sha = single(receipts, "workflowSha")
    workflow_ref = single(receipts, "workflowRef")
    workflow_file = single(receipts, "workflowFileSha256")
    lock_digest = single(receipts, "dependencyLockSha256")
    map_digest = single(receipts, "implementationMapSha256")
    docs_digest = single(receipts, "documentationHash")
    for lane in ("exact-head", "base-merge"):
        core, product = (receipts[(profile, lane)] for profile in ("core", "product"))
        if any(core[name] != product[name] for name in (
            "testedSha", "testedTree", "sourceTreeHash", "sourceFiles", "sourceManifestSha256",
            "documentationHash", "implementationMapSha256", "workflowFileSha256",
        )):
            raise ValueError("core and product tested different source or evidence inputs")
    exact = receipts[("core", "exact-head")]
    merged = receipts[("core", "base-merge")]
    return {
        "schema": "hepta.prompt-registry.qualification-summary.v3",
        "candidateSha": source, "sourceSha": source, "sourceTreeHash": exact["testedTree"],
        "baseSha": base, "deterministicMergeSha": merged["testedSha"],
        "deterministicMergeTree": merged["testedTree"],
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "qualificationWorkflow": {"sha": workflow_sha, "ref": workflow_ref, "fileSha256": workflow_file},
        "cargoLockSha256": lock_digest,
        "implementationMapSha256": map_digest,
        "documentationHash": docs_digest,
        "featureProfileSha256": {"/".join(key): value["featureProfileSha256"] for key, value in sorted(receipts.items())},
        "testSetSha256": {"/".join(key): value["testSetSha256"] for key, value in sorted(receipts.items())},
        "livePublicApiMapSha256": {"/".join(key): value["livePublicApiMapSha256"] for key, value in sorted(receipts.items())},
        "runnerImageIdentitySha256": {"/".join(key): value["runnerImageIdentitySha256"] for key, value in sorted(receipts.items())},
        "runnerImages": {"/".join(key): value["runner"] for key, value in sorted(receipts.items())},
        "sourceQualified": True,
        "closedWorldPublicFunctions": True,
        "productExecutionProved": False,
        "mergeReady": False, "productionReady": False,
        "productActivated": False, "accepted": False, "released": False,
        "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
        "receiptSha256": receipt_digests,
        "laneArtifactContentSha256": artifact_digests,
    }


def failure_summary(source: str, base: str, run: str, attempt: str, error: Exception) -> dict[str, Any]:
    return {
        "schema": "hepta.prompt-registry.qualification-summary.v3",
        "candidateSha": source, "sourceSha": source, "baseSha": base,
        "workflowRunId": run, "workflowRunAttempt": attempt,
        "sourceQualified": False, "closedWorldPublicFunctions": False,
        "productExecutionProved": False, "mergeReady": False, "productionReady": False,
        "productActivated": False, "accepted": False, "released": False,
        "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
        "failure": {"type": type(error).__name__, "message": str(error)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = aggregate(args.root, args.source, args.base, args.run, args.attempt)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        result = failure_summary(args.source, args.base, args.run, args.attempt, error)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(1) from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
