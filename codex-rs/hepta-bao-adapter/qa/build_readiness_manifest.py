#!/usr/bin/env python3
'''Build one exact-candidate secrets.heptabao readiness receipt.'''
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PRODUCT_CALLER_SCHEMA = "hepta.secrets-heptabao-product-caller.v1"
PRODUCT_CALLER_FIELDS = {
    "schema",
    "callerId",
    "ownerModule",
    "binaryPackage",
    "binaryTarget",
    "sourcePath",
    "constructorSymbol",
    "databasePathSource",
    "providerConfigurationSource",
    "consumerRegistrySource",
    "trustedTimeSource",
    "settlementEvidenceSource",
    "checkpointService",
    "metricsSink",
    "recoveryWorker",
    "shutdownDrainDeadlineMs",
    "deploymentTopology",
    "configurationDigest",
}


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        relative = path.relative_to(ROOT).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def optional(value: str | None) -> str | None:
    return value if value else None


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_product_caller(path_text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not path_text:
        return None, None
    manifest_path = Path(path_text)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    manifest_path = manifest_path.resolve()
    try:
        manifest_path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise SystemExit("product caller manifest must be inside the repository") from error
    if not manifest_path.is_file():
        raise SystemExit("product caller manifest does not exist")

    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("product caller manifest must be an object")
    if set(value) != PRODUCT_CALLER_FIELDS:
        missing = sorted(PRODUCT_CALLER_FIELDS - set(value))
        extra = sorted(set(value) - PRODUCT_CALLER_FIELDS)
        raise SystemExit(
            f"product caller manifest fields differ: missing={missing}, extra={extra}"
        )
    if value["schema"] != PRODUCT_CALLER_SCHEMA:
        raise SystemExit("unexpected product caller manifest schema")
    for name in PRODUCT_CALLER_FIELDS - {"shutdownDrainDeadlineMs"}:
        if not nonempty_string(value[name]):
            raise SystemExit(f"product caller field {name} must be non-empty")
    if not isinstance(value["shutdownDrainDeadlineMs"], int) or not (
        1 <= value["shutdownDrainDeadlineMs"] <= 300_000
    ):
        raise SystemExit("shutdownDrainDeadlineMs must be between 1 and 300000")
    if len(value["configurationDigest"]) != 64 or any(
        byte not in "0123456789abcdef" for byte in value["configurationDigest"]
    ):
        raise SystemExit("configurationDigest must be lowercase SHA-256 hex")
    if value["deploymentTopology"] not in {
        "single_process_local_filesystem",
        "single_host_multi_process",
    }:
        raise SystemExit("unsupported product caller deployment topology")

    source = ROOT / value["sourcePath"]
    if not source.is_file():
        raise SystemExit("product caller source path does not exist")
    source_parts = source.relative_to(ROOT).parts
    if any(part in {"test", "tests", "examples", "qa", "fixtures"} for part in source_parts):
        raise SystemExit("test, example, QA or fixture source cannot be a product caller")
    source_text = source.read_text(encoding="utf-8")
    if value["constructorSymbol"] not in source_text:
        raise SystemExit("product caller constructor symbol is not present in source")
    if "SqliteBaoProductRuntimeV1" not in source_text:
        raise SystemExit("product caller does not instantiate the SQLite Bao runtime")
    if value["binaryTarget"] not in source_text:
        raise SystemExit("product caller source does not bind its declared binary target")

    return value, sha256(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--candidate-role",
        choices=("source-head", "synthetic-merge"),
        required=True,
    )
    parser.add_argument("--source-head-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--deterministic-merge-sha")
    parser.add_argument("--github-merge-sha")
    parser.add_argument("--workflow-sha")
    parser.add_argument("--final-merge-sha")
    parser.add_argument("--workflow-run-id")
    parser.add_argument("--attempt-id")
    parser.add_argument("--runner-image")
    parser.add_argument("--target-triple")
    parser.add_argument("--qualified", action="store_true")
    parser.add_argument("--product-caller-manifest", default="")
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()

    head = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    rust = run("rustc", "--version", "--verbose")
    detected_target = next(
        (
            line.split(":", 1)[1].strip()
            for line in rust.splitlines()
            if line.startswith("host:")
        ),
        "unknown",
    )
    source_head = args.source_head_sha or (
        head if args.candidate_role == "source-head" else None
    )
    if args.candidate_role == "source-head" and source_head != head:
        raise SystemExit("source-head receipt must bind sourceHeadSha to exact HEAD")
    if args.candidate_role == "synthetic-merge":
        if not args.source_head_sha or not args.base_sha:
            raise SystemExit("synthetic-merge receipt requires source-head and base SHA")
        if args.deterministic_merge_sha != head:
            raise SystemExit("synthetic-merge receipt must bind deterministicMergeSha to exact HEAD")

    workflow_sha = args.workflow_sha or os.getenv("GITHUB_WORKFLOW_SHA") or head
    workflow_run_id = args.workflow_run_id or os.getenv("GITHUB_RUN_ID") or "local"
    attempt_id = args.attempt_id or os.getenv("GITHUB_RUN_ATTEMPT") or "local-1"
    runner_image = (
        args.runner_image
        or os.getenv("ImageOS")
        or os.getenv("RUNNER_IMAGE")
        or platform.platform()
    )
    target_triple = args.target_triple or detected_target

    migrations = list(
        (ROOT / "codex-rs/hepta-bao-adapter/migrations").glob("*.sql")
    )
    schemas = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*schema*"))
    tests = list((ROOT / "codex-rs/hepta-bao-adapter").rglob("*test*.rs"))
    tests += list(
        (ROOT / "codex-rs/hepta-bao-adapter/qa").glob("test_*.py")
    )
    docs = list((ROOT / "docs/modules/secrets.heptabao").rglob("*"))
    docs += list(
        (ROOT / "docs/lane-a-foundation/secrets.heptabao").rglob("*")
    )
    implementation = (
        ROOT / "docs/modules/secrets.heptabao/IMPLEMENTATION_MAP.json"
    )

    artifact_hashes: dict[str, str] = {}
    for item in args.artifact:
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise SystemExit(f"artifact does not exist: {path}")
        if path.name in artifact_hashes:
            raise SystemExit(f"duplicate artifact name: {path.name}")
        artifact_hashes[path.name] = sha256(path)

    identity = {
        "candidateSha": head,
        "testedSha": head,
        "documentedSha": head,
        "artifactSourceSha": head,
        "qualificationSha": head,
    }
    role_identity_closed = (
        source_head == head
        if args.candidate_role == "source-head"
        else args.deterministic_merge_sha == head
    )
    identity_closed = len(set(identity.values())) == 1 and role_identity_closed

    dependency_lock_hash = sha256(ROOT / "codex-rs/Cargo.lock")
    migration_hash = tree_hash(migrations)
    schema_hash = tree_hash(schemas)
    test_set_hash = tree_hash(tests)
    qualification_profile_hash = sha256(
        ROOT / ".github/workflows/secrets-heptabao-five-closure-qualified.yml"
    )
    implementation_map_hash = sha256(implementation)
    documentation_hash = tree_hash(docs)

    qualification_identity = {
        "source_head_sha": optional(source_head),
        "base_sha": optional(args.base_sha),
        "deterministic_merge_sha": optional(args.deterministic_merge_sha),
        "github_merge_sha": optional(args.github_merge_sha),
        "workflow_sha": workflow_sha,
        "final_merge_sha": optional(args.final_merge_sha),
        "workflow_run_id": workflow_run_id,
        "attempt_id": attempt_id,
        "runner_image": runner_image,
        "target_triple": target_triple,
        "cargo_lock_hash": dependency_lock_hash,
        "migration_hash": migration_hash,
        "test_set_hash": test_set_hash,
        "qualification_profile_hash": qualification_profile_hash,
        "implementation_map_hash": implementation_map_hash,
        "documentation_hash": documentation_hash,
        "source_tree_hash": tree,
        "artifact_hashes": artifact_hashes,
    }

    product_caller, product_caller_manifest_sha256 = load_product_caller(
        args.product_caller_manifest
    )
    product_composed = product_caller is not None
    readiness = {
        "sourcePresent": True,
        "sourceImmutable": identity_closed,
        "sourceCompiled": (
            "passed" if args.qualified else "unproved_for_exact_head"
        ),
        "sourceQualified": bool(args.qualified and identity_closed),
        "candidateAttested": bool(
            args.qualified
            and identity_closed
            and args.candidate_role == "synthetic-merge"
        ),
        "storageProfileQualified": False,
        "productComposed": product_composed,
        "targetHostQualified": False,
        "activated": False,
        "operatorAccepted": False,
        "released": False,
    }
    production_qualified = all(
        (
            readiness["sourceQualified"],
            readiness["storageProfileQualified"],
            readiness["productComposed"],
            readiness["targetHostQualified"],
            readiness["operatorAccepted"],
        )
    )

    receipt = {
        "schema": "hepta.secrets-heptabao-readiness.v3",
        "candidateRole": args.candidate_role,
        **identity,
        "qualificationIdentity": qualification_identity,
        "sourceHeadSha": optional(source_head),
        "sourceTreeSha": tree,
        "sourceTreeHash": tree,
        "baseSha": optional(args.base_sha),
        "deterministicMergeSha": optional(args.deterministic_merge_sha),
        "githubMergeSha": optional(args.github_merge_sha),
        "workflowSha": workflow_sha,
        "finalMergeSha": optional(args.final_merge_sha),
        "workflowRunId": workflow_run_id,
        "workflowAttempt": attempt_id,
        "attemptId": attempt_id,
        "runnerImage": runner_image,
        "rustToolchain": rust.splitlines()[0],
        "targetTriple": target_triple,
        "dependencyLockSha256": dependency_lock_hash,
        "cargoLockHash": dependency_lock_hash,
        "migrationSha256": migration_hash,
        "migrationHash": migration_hash,
        "schemaSha256": schema_hash,
        "testSetSha256": test_set_hash,
        "testSetHash": test_set_hash,
        "qualificationProfileSha256": qualification_profile_hash,
        "qualificationProfileHash": qualification_profile_hash,
        "implementationMapSha256": implementation_map_hash,
        "implementationMapHash": implementation_map_hash,
        "documentationSha256": documentation_hash,
        "documentationHash": documentation_hash,
        "artifactHashes": artifact_hashes,
        "buildSurface": "single_complete",
        "identityClosed": identity_closed,
        "readinessDimensions": readiness,
        "productCaller": product_caller,
        "productCallerManifestSha256": product_caller_manifest_sha256,
        "productionQualified": production_qualified,
        "mergeReady": production_qualified,
        "nonclaims": [
            "A green source qualification does not select or activate a production process.",
            "Product composition requires a repository-owned, source-bound caller manifest.",
            "No production qualification is emitted without separately governed storage, target-host and operator gates.",
            "No result from another SHA, workflow run or workflow attempt is accepted.",
            "SQLite source presence is not storage-profile or target-host qualification.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
