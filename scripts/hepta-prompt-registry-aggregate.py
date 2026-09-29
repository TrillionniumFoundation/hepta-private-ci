#!/usr/bin/env python3
"""Aggregate four exact-run receipts. Never activates, accepts, or releases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

LANES = {(profile, lane) for profile in ("core", "product") for lane in ("exact-head", "base-merge")}
COMMON = {"clean-before", "harness-tests", "map", "toolchain", "source-graph", "format", "all-targets", "lint", "clean-after"}
REQUIRED = {
    "core": COMMON | {"registry-inventory", "registry", "operational-profiles"},
    "product": COMMON | {"agentd-inventory", "extension-inventory", "optimizer", "extension", "agentd", "pipeline-profile"},
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
    values = {receipt.get(field) for receipt in receipts.values()}
    if len(values) != 1 or None in values:
        raise ValueError("four lanes disagree on " + field)
    return values.pop()


def aggregate(root: Path, source: str, base: str, run: str, attempt: str) -> dict:
    receipts = {}
    receipt_digests = {}
    artifact_digests = {}
    for receipt_path in sorted(root.glob("*/receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        key = (receipt.get("profile"), receipt.get("lane"))
        if key not in LANES or key in receipts:
            raise ValueError("unknown or duplicate qualification lane")
        if receipt.get("schema") != "hepta.prompt-registry.qualification-receipt.v2":
            raise ValueError("unsupported qualification receipt")
        for name, expected in [("sourceSha", source), ("baseSha", base), ("runId", run), ("runAttempt", attempt)]:
            if str(receipt.get(name)) != expected:
                raise ValueError("receipt identity or run attempt mismatch: " + name)
        for name in ("sourceSha", "baseSha", "testedSha", "testedTree", "workflowSha"):
            if not re.fullmatch(r"[a-f0-9]{40}", receipt.get(name, "")):
                raise ValueError("invalid exact identity: " + name)
        if not re.fullmatch(r"[a-f0-9]{64}", receipt.get("dependencyLockSha256", "")):
            raise ValueError("invalid dependency lock digest")
        if not receipt.get("workflowRef") or not receipt.get("targetTriple"):
            raise ValueError("missing workflow or target identity")
        runner = receipt.get("runner")
        if not isinstance(runner, dict) or runner.get("targetTriple") != receipt["targetTriple"]:
            raise ValueError("invalid runner identity")
        if key[1] == "exact-head" and receipt["testedSha"] != source:
            raise ValueError("wrong exact-head candidate")
        if receipt.get("allRequiredChecksPassed") is not True:
            raise ValueError("lane did not pass every required check")
        if any(receipt.get(name) is not False for name in ("qualified", "productionReady", "productActivated", "accepted", "released")):
            raise ValueError("lane crossed its claim boundary")
        checks = receipt.get("checks", [])
        if len(checks) != len(REQUIRED[key[0]]) or {check.get("name") for check in checks} != REQUIRED[key[0]]:
            raise ValueError("missing or unexpected required checks")
        for check in checks:
            if check.get("state") != "passed" or check.get("exitCode") != 0 or check.get("postconditionFailures") != []:
                raise ValueError("failed, interrupted or skipped check")
            log = receipt_path.parent / (check["name"] + ".log")
            if not log.is_file() or log.is_symlink() or sha256_bytes(log.read_bytes()) != check.get("logSha256"):
                raise ValueError("raw log missing or digest mismatch")
        if not receipt.get("sourceFiles"):
            raise ValueError("source blob manifest missing")
        receipts[key] = receipt
        label = "/".join(key)
        receipt_digests[label] = sha256_bytes(receipt_path.read_bytes())
        artifact_digests[label] = artifact_content_digest(receipt_path.parent)
    if set(receipts) != LANES:
        raise ValueError("all four lanes are mandatory")
    workflow_sha = single(receipts, "workflowSha")
    workflow_ref = single(receipts, "workflowRef")
    lock_digest = single(receipts, "dependencyLockSha256")
    for lane in ("exact-head", "base-merge"):
        core, product = (receipts[(profile, lane)] for profile in ("core", "product"))
        if any(core[name] != product[name] for name in ("testedSha", "testedTree", "sourceFiles")):
            raise ValueError("core and product tested different source")
    exact = receipts[("core", "exact-head")]
    merged = receipts[("core", "base-merge")]
    return {
        "schema": "hepta.prompt-registry.qualification-summary.v2",
        "sourceSha": source,
        "sourceTree": exact["testedTree"],
        "baseSha": base,
        "syntheticMerge": {"sha": merged["testedSha"], "tree": merged["testedTree"]},
        "runId": run,
        "runAttempt": attempt,
        "qualificationWorkflow": {"sha": workflow_sha, "ref": workflow_ref},
        "dependencyLockSha256": lock_digest,
        "runnerTargets": {
            "/".join(key): {"targetTriple": receipt["targetTriple"], "runner": receipt["runner"]}
            for key, receipt in sorted(receipts.items())
        },
        "sourceQualified": True,
        "productActivated": False,
        "accepted": False,
        "released": False,
        "receiptSha256": receipt_digests,
        "laneArtifactContentSha256": artifact_digests,
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
    result = aggregate(args.root, args.source, args.base, args.run, args.attempt)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
