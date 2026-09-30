#!/usr/bin/env python3
"""Build one fail-closed readiness manifest from every qualification lane.

The manifest is a consistency record, not production authority. Target-host
power-loss conformance, real-product execution, independent operator acceptance,
activation, promotion and release remain external claims and are always false
unless a separately authenticated authority is introduced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA = "hepta.learning-artifacts.readiness.v1"
RECEIPT_SCHEMA = "hepta.learning-artifacts.qualification.v2"
RUNNER_SCHEMA = "hepta.learning-artifacts-runner-identity.v2"
MAX_FILE = 64 * 1024 * 1024
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
LANES = ("exact-head", "synthetic-merge")
PROFILES = {
    "linux-x86_64-stable": {
        "targetTriple": "x86_64-unknown-linux-gnu",
        "toolchain": "1.95.0",
        "runnerOs": "Linux",
        "runnerArch": "X64",
    },
    "linux-aarch64-stable": {
        "targetTriple": "aarch64-unknown-linux-gnu",
        "toolchain": "1.95.0",
        "runnerOs": "Linux",
        "runnerArch": "ARM64",
    },
    "macos-aarch64-stable": {
        "targetTriple": "aarch64-apple-darwin",
        "toolchain": "1.95.0",
        "runnerOs": "macOS",
        "runnerArch": "ARM64",
    },
    "linux-x86_64-msrv": {
        "targetTriple": "x86_64-unknown-linux-gnu",
        "toolchain": "1.88.0",
        "runnerOs": "Linux",
        "runnerArch": "X64",
    },
}
REQUIRED_GATES = {"closure", "build", "clippy", "format", "inventory", "tests"}
EXTERNAL_FALSE = {
    "targetHostDurabilityConformance": False,
    "realProductExecution": False,
    "independentOperatorAcceptance": False,
    "serviceActivation": False,
    "deploymentPromotion": False,
    "productionRelease": False,
}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def strict_json(data: bytes) -> Any:
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError(f"duplicate JSON field: {key}")
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def read_regular(path: Path, limit: int = MAX_FILE) -> bytes:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
        raise ValueError(f"not a bounded regular file: {path}")
    data = path.read_bytes()
    if len(data) != metadata.st_size:
        raise ValueError(f"file changed while reading: {path}")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(read_regular(path))


def require_sha(value: object, field: str, length: int = 40) -> str:
    pattern = SHA40 if length == 40 else SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    return value


def find_one(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected one {name} beneath {root}, found {len(matches)}")
    return matches[0]


def artifact_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"artifact contains a symlink or special file: {path}")
        relative = path.relative_to(root).as_posix()
        hashes[relative] = sha256_file(path)
    if not hashes:
        raise ValueError(f"empty lane artifact: {root}")
    return hashes


def validate_runner(identity: dict, source: str, base: str, event_sha: str,
                    run_id: str, run_attempt: str) -> tuple[str, str]:
    if identity.get("schema") != RUNNER_SCHEMA:
        raise ValueError("unsupported runner identity schema")
    profile, lane = identity.get("profile"), identity.get("lane")
    if profile not in PROFILES or lane not in LANES:
        raise ValueError("unknown qualification profile or lane")
    expected = PROFILES[profile]
    checks = {
        "sourceSha": source,
        "baseSha": base,
        "githubEventSha": event_sha,
        "workflowRunId": run_id,
        "workflowRunAttempt": run_attempt,
        "expectedArchitecture": expected["targetTriple"],
        "toolchain": expected["toolchain"],
        "runnerOs": expected["runnerOs"],
        "runnerArch": expected["runnerArch"],
    }
    for field, wanted in checks.items():
        if str(identity.get(field)) != wanted:
            raise ValueError(f"runner identity mismatch for {field}")
    for field in ("sourceSha", "baseSha", "githubEventSha", "candidateSha", "candidateTree",
                  "sourceTreeObject", "documentationTreeObject"):
        require_sha(identity.get(field), field)
    for field in ("cargoLockSha256", "workflowSha256", "implementationMapSha256"):
        require_sha(identity.get(field), field, 64)
    rustc = identity.get("rustcVerbose")
    if not isinstance(rustc, str) or f"host: {expected['targetTriple']}" not in rustc:
        raise ValueError("rustc host differs from the qualified target")
    if not identity.get("runnerImage") or not identity.get("runnerImageVersion"):
        raise ValueError("runner image identity is incomplete")
    return profile, lane


def validate_receipt(receipt_path: Path, digest_path: Path, identity: dict,
                     run_id: str, run_attempt: str) -> dict:
    payload = read_regular(receipt_path)
    claimed = read_regular(digest_path, 1024).decode("ascii").strip()
    if claimed != sha256_bytes(payload):
        raise ValueError("qualification receipt digest mismatch")
    receipt = strict_json(payload)
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unsupported qualification receipt")
    if payload != canonical(receipt):
        raise ValueError("qualification receipt is not canonical")
    expected = {
        "sourceCommit": identity["sourceSha"],
        "baseCommit": identity["baseSha"],
        "testedCommit": identity["candidateSha"],
        "testedTree": identity["candidateTree"],
        "lane": identity["lane"],
    }
    for field, wanted in expected.items():
        if receipt.get(field) != wanted:
            raise ValueError(f"qualification receipt mismatch for {field}")
    runner = receipt.get("runner")
    if not isinstance(runner, dict) or str(runner.get("GITHUB_RUN_ID")) != run_id \
            or str(runner.get("GITHUB_RUN_ATTEMPT")) != run_attempt:
        raise ValueError("receipt belongs to another workflow run or attempt")
    gates = receipt.get("gates")
    if not isinstance(gates, dict) or set(gates) != REQUIRED_GATES:
        raise ValueError("required gate set is incomplete or substituted")
    for name, gate in gates.items():
        if not isinstance(gate, dict) or gate.get("status") != "completed" \
                or type(gate.get("exitCode")) is not int or gate["exitCode"] != 0:
            raise ValueError(f"required gate did not pass: {name}")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or type(execution.get("passed")) is not int \
            or execution["passed"] <= 0 or execution.get("skipped") != 0 \
            or execution.get("retries") != 0:
        raise ValueError("test execution is missing, skipped or retried")
    completion = receipt.get("completion")
    trace_complete = isinstance(completion, dict) \
        and completion.get("nativeCandidateQualified") is True \
        and completion.get("requirementTraceabilityComplete") is True \
        and completion.get("moduleComplete") is False
    if receipt.get("qualified") is not True or receipt.get("errors") != []:
        raise ValueError("lane receipt is not qualified")
    boundary = receipt.get("claimBoundary")
    if not isinstance(boundary, dict) or any(value is not False for value in boundary.values()):
        raise ValueError("lane receipt attempts to grant external authority")
    source_objects = receipt.get("sourceObjects")
    if not isinstance(source_objects, dict) or not source_objects:
        raise ValueError("lane receipt does not seal source objects")
    return {
        "traceabilityComplete": trace_complete,
        "testCount": execution["passed"],
        "receiptSha256": sha256_bytes(payload),
        "testedCommit": receipt["testedCommit"],
        "testedTree": receipt["testedTree"],
    }


def build_manifest(root: Path, source: str, base: str, event_sha: str,
                   run_id: str, run_attempt: str, final_merge: str | None,
                   workflow_path: Path, map_path: Path) -> tuple[dict, bool]:
    for value, field in ((source, "source"), (base, "base"), (event_sha, "event sha")):
        require_sha(value, field)
    if final_merge is not None:
        require_sha(final_merge, "final merge")
    expected_pairs = {(profile, lane) for profile in PROFILES for lane in LANES}
    rows, errors = {}, []
    roots = sorted(path.parent.parent for path in root.rglob("runner-identity.json"))
    if len(roots) != len(expected_pairs):
        errors.append(f"expected {len(expected_pairs)} lane bundles, found {len(roots)}")
    for bundle in roots:
        key = bundle.name
        try:
            runner_path = find_one(bundle, "runner-identity.json")
            identity = strict_json(read_regular(runner_path))
            if not isinstance(identity, dict):
                raise ValueError("runner identity is not an object")
            profile, lane = validate_runner(identity, source, base, event_sha, run_id, run_attempt)
            pair = (profile, lane)
            key = f"{profile}/{lane}"
            if pair in rows:
                raise ValueError("duplicate profile/lane bundle")
            receipt_path = find_one(bundle, "qualification.json")
            result = validate_receipt(
                receipt_path,
                find_one(bundle, "qualification.sha256"),
                identity,
                run_id,
                run_attempt,
            )
            inventory_path = find_one(bundle, "inventory.stdout")
            row = {
                "profile": profile,
                "lane": lane,
                "candidateSha": identity["candidateSha"],
                "candidateTree": identity["candidateTree"],
                "targetTriple": identity["expectedArchitecture"],
                "toolchain": identity["toolchain"],
                "rustcVerbose": identity["rustcVerbose"],
                "runnerImage": identity["runnerImage"],
                "runnerImageVersion": identity["runnerImageVersion"],
                "cargoLockSha256": identity["cargoLockSha256"],
                "workflowSha256": identity["workflowSha256"],
                "implementationMapSha256": identity["implementationMapSha256"],
                "documentationTreeObject": identity["documentationTreeObject"],
                "testInventorySha256": sha256_file(inventory_path),
                "artifactHashes": artifact_hashes(bundle),
                **result,
            }
            rows[pair] = row
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            errors.append(f"{key}: {error}")
    missing = sorted(expected_pairs - set(rows))
    if missing:
        errors.append("missing profiles: " + ", ".join(f"{p}/{l}" for p, l in missing))

    exact = [row for (profile, lane), row in rows.items() if lane == "exact-head"]
    synthetic = [row for (profile, lane), row in rows.items() if lane == "synthetic-merge"]
    if exact and any(row["candidateSha"] != source for row in exact):
        errors.append("an exact-head lane did not test the source commit")
    synthetic_shas = {row["candidateSha"] for row in synthetic}
    synthetic_trees = {row["candidateTree"] for row in synthetic}
    if synthetic and (len(synthetic_shas) != 1 or len(synthetic_trees) != 1):
        errors.append("synthetic merge identity differs across runner profiles")
    if any(not row["traceabilityComplete"] for row in rows.values()):
        errors.append("one or more lanes lack complete requirement traceability")

    checkout_workflow = sha256_file(workflow_path)
    checkout_map = sha256_file(map_path)
    exact_rows = [row for row in exact if row["workflowSha256"] == checkout_workflow
                  and row["implementationMapSha256"] == checkout_map]
    if exact and len(exact_rows) != len(exact):
        errors.append("exact-head workflow or implementation-map digest differs from checkout")

    matrix_projection = {
        f"{profile}/{lane}": {
            "candidateSha": row["candidateSha"],
            "candidateTree": row["candidateTree"],
            "targetTriple": row["targetTriple"],
            "toolchain": row["toolchain"],
            "testInventorySha256": row["testInventorySha256"],
        }
        for (profile, lane), row in sorted(rows.items())
    }
    complete = not errors and set(rows) == expected_pairs
    repository_qualified = complete
    merge_ready = repository_qualified
    manifest = {
        "schema": SCHEMA,
        "sourceHeadSha": source,
        "baseSha": base,
        "deterministicMergeSha": next(iter(synthetic_shas)) if len(synthetic_shas) == 1 else None,
        "deterministicMergeTree": next(iter(synthetic_trees)) if len(synthetic_trees) == 1 else None,
        "githubMergeSha": event_sha,
        "finalMergeSha": final_merge,
        "workflowRunId": run_id,
        "workflowRunAttempt": run_attempt,
        "workflowSha256": checkout_workflow,
        "implementationMapSha256": checkout_map,
        "sourceTreeObject": exact[0]["candidateTree"] if exact else None,
        "documentationHash": sha256_bytes(canonical({
            key: value["documentationTreeObject"] for key, value in sorted(
                ((f"{p}/{l}", row) for (p, l), row in rows.items())
            )
        })),
        "testSetHash": sha256_bytes(canonical(matrix_projection)),
        "qualificationProfileHash": sha256_bytes(canonical({
            "profiles": PROFILES,
            "lanes": LANES,
            "requiredGates": sorted(REQUIRED_GATES),
        })),
        "matrix": {f"{p}/{l}": row for (p, l), row in sorted(rows.items())},
        "errors": errors,
        "repositoryCandidateQualified": repository_qualified,
        "mergeReady": merge_ready,
        "productionQualified": False,
        "externalClaims": dict(EXTERNAL_FALSE),
    }
    return manifest, complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--event-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--implementation-map", required=True, type=Path)
    parser.add_argument("--final-merge")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest, complete = build_manifest(
            args.root.resolve(), args.source, args.base, args.event_sha,
            args.run_id, args.run_attempt, args.final_merge,
            args.workflow.resolve(), args.implementation_map.resolve(),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        manifest = {
            "schema": SCHEMA,
            "sourceHeadSha": args.source,
            "baseSha": args.base,
            "githubMergeSha": args.event_sha,
            "finalMergeSha": args.final_merge,
            "workflowRunId": args.run_id,
            "workflowRunAttempt": args.run_attempt,
            "errors": [str(error)],
            "repositoryCandidateQualified": False,
            "mergeReady": False,
            "productionQualified": False,
            "externalClaims": dict(EXTERNAL_FALSE),
        }
        complete = False
    args.out.mkdir(parents=True, exist_ok=False)
    payload = canonical(manifest)
    (args.out / "readiness.json").write_bytes(payload)
    (args.out / "readiness.sha256").write_text(sha256_bytes(payload) + "\n", encoding="ascii")
    print(json.dumps({
        "repositoryCandidateQualified": manifest["repositoryCandidateQualified"],
        "mergeReady": manifest["mergeReady"],
        "productionQualified": manifest["productionQualified"],
        "errors": manifest["errors"],
    }, indent=2))
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
