#!/usr/bin/env python3
'''Build one exact-candidate secrets.heptabao readiness receipt.'''
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_hepta_callers import _strip_cfg_test_items, _strip_rust_non_code
from attest_candidate import load_receipt
from build_supply_chain_manifest import files as committed_files, digest_paths as committed_tree_hash, source_digest
PRODUCT_CALLER_SCHEMA = "hepta.secrets-heptabao-product-caller.v2"
PRODUCT_CALLER_CONFIG = ROOT / "docs/modules/secrets.heptabao/PRODUCT_CALLER_CONFIG_V1.json"
PRODUCT_CALLER_FIELDS = {
    "schema",
    "callerId",
    "ownerModule",
    "binaryPackage",
    "binaryTarget",
    "sourcePath",
    "constructorSourcePath",
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
    if type(value["shutdownDrainDeadlineMs"]) is not int or not (
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
    if value["ownerModule"] != "secrets.heptabao":
        raise SystemExit("product caller must belong to secrets.heptabao")

    if not PRODUCT_CALLER_CONFIG.is_file():
        raise SystemExit("product caller configuration does not exist")
    if sha256(PRODUCT_CALLER_CONFIG) != value["configurationDigest"]:
        raise SystemExit("product caller configuration digest does not match exact config source")
    configuration = json.loads(PRODUCT_CALLER_CONFIG.read_text(encoding="utf-8"))
    if configuration.get("binaryTarget") != value["binaryTarget"]:
        raise SystemExit("product caller and configuration binary targets differ")
    deadlines = configuration.get("deadlines")
    if not isinstance(deadlines, dict) or any(
        type(deadlines.get(name)) is not int or not 1 <= deadlines[name] <= 900_000
        for name in ("consumerTimeoutMs", "forwardExecutionLeaseMs", "absoluteOperationDeadlineMs", "shutdownDrainDeadlineMs")
    ) or not (
        deadlines["consumerTimeoutMs"] < deadlines["forwardExecutionLeaseMs"]
        < deadlines["absoluteOperationDeadlineMs"]
        and deadlines["shutdownDrainDeadlineMs"] < deadlines["absoluteOperationDeadlineMs"]
        and deadlines["shutdownDrainDeadlineMs"] == value["shutdownDrainDeadlineMs"]
    ):
        raise SystemExit("product caller deadline contract is not strictly ordered")
    recovery = configuration.get("recoveryWorker")
    if not isinstance(recovery, dict) or recovery.get("claimMode") != "just_in_time":
        raise SystemExit("product caller recovery must use just-in-time claims")

    source_path = Path(value["sourcePath"])
    if source_path.is_absolute() or ".." in source_path.parts:
        raise SystemExit("product caller source path must be repository-relative without traversal")
    source = (ROOT / source_path).resolve()
    try:
        source.relative_to(ROOT.resolve())
    except ValueError as error:
        raise SystemExit("product caller source must remain inside the repository") from error
    if not source.is_file():
        raise SystemExit("product caller source path does not exist")
    cargo_path = ROOT / "codex-rs/hepta-bao-adapter/Cargo.toml"
    cargo = tomllib.loads(cargo_path.read_text(encoding="utf-8"))
    if cargo["package"]["name"] != value["binaryPackage"]:
        raise SystemExit("product caller package is not the adapter Cargo package")
    declared_binary = any(
        item.get("name") == value["binaryTarget"]
        and (cargo_path.parent / item.get("path", "src/main.rs")).resolve() == source
        for item in cargo.get("bin", [])
    )
    auto_binary = cargo["package"].get("autobins", True) and source == (
        cargo_path.parent / "src/bin" / (value["binaryTarget"] + ".rs")
    ).resolve()
    if not declared_binary and not auto_binary:
        raise SystemExit("product caller source is not its declared Cargo binary target")
    source_parts = source.relative_to(ROOT).parts
    if any(part in {"test", "tests", "examples", "qa", "fixtures"} for part in source_parts):
        raise SystemExit("test, example, QA or fixture source cannot be a product caller")
    source_text = source.read_text(encoding="utf-8")
    constructor_path = Path(value["constructorSourcePath"])
    if constructor_path.is_absolute() or ".." in constructor_path.parts:
        raise SystemExit("product caller constructor source must be repository-relative without traversal")
    constructor_source = (ROOT / constructor_path).resolve()
    try:
        constructor_parts = constructor_source.relative_to(ROOT.resolve()).parts
    except ValueError as error:
        raise SystemExit("product caller constructor must remain inside the repository") from error
    if any(part in {"test", "tests", "examples", "qa", "fixtures"} for part in constructor_parts):
        raise SystemExit("test, example, QA or fixture source cannot be a product constructor")
    if not constructor_source.is_file():
        raise SystemExit("product caller constructor source does not exist")
    code = _strip_cfg_test_items(_strip_rust_non_code(constructor_source.read_text(encoding="utf-8")))
    if not re.search(r"\bpub\s+fn\s+" + re.escape(value["constructorSymbol"]) + r"\s*\(", code):
        raise SystemExit("product caller constructor declaration is not present in non-test source")
    if not re.search(r"SqliteBaoProductRuntimeV1\s*::\s*new\s*\(", code):
        raise SystemExit("product caller does not instantiate the SQLite Bao runtime")
    library_code = _strip_cfg_test_items(_strip_rust_non_code(
        (cargo_path.parent / "src/lib.rs").read_text(encoding="utf-8")
    ))
    module_name = constructor_source.stem
    if not re.search(r"\bmod\s+" + re.escape(module_name) + r"\s*;", library_code):
        raise SystemExit("product constructor module is not compiled by the Cargo library")
    symbol = re.escape(value["constructorSymbol"])
    if not re.search(
        r"\bpub\s+use\s+" + re.escape(module_name)
        + r"\s*::\s*(?:" + symbol + r"\s*;|\{[^}]*\b" + symbol + r"\b[^}]*\}\s*;)",
        library_code,
    ):
        raise SystemExit("product constructor is not publicly exported by the Cargo library")
    if value["binaryTarget"] not in source_text:
        raise SystemExit("product caller source does not bind its declared binary target")

    return value, sha256(manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
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
    parser.add_argument("--native-receipt", type=Path)
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
    native_receipt_sha256 = None
    if args.qualified:
        if args.native_receipt is None:
            raise SystemExit("--qualified requires --native-receipt with retained native gate logs")
        native = load_receipt(args.native_receipt, args.candidate_role)
        if native['head'] != head or native['tree'] != tree:
            raise SystemExit("native receipt must bind the exact current candidate commit and tree")
        if native['rustToolchain'] != rust:
            raise SystemExit("native receipt toolchain differs from the current qualification toolchain")
        for field, expected_value in (
            ('workflowRunId', workflow_run_id), ('workflowAttempt', attempt_id), ('workflowSha', workflow_sha),
        ):
            if native.get(field) != expected_value:
                raise SystemExit(f"native receipt differs from current execution identity: {field}")
        for field, selected, environment_key in (
            ('workflowRunId', workflow_run_id, 'GITHUB_RUN_ID'),
            ('workflowAttempt', attempt_id, 'GITHUB_RUN_ATTEMPT'),
            ('workflowSha', workflow_sha, 'GITHUB_WORKFLOW_SHA'),
        ):
            current = os.environ.get(environment_key)
            if current is not None and selected != current:
                raise SystemExit(f"readiness identity differs from current execution environment: {field}")
        if target_triple != detected_target:
            raise SystemExit("native qualification target must match the executed Rust host target")
        if args.candidate_role == 'synthetic-merge':
            parents = run('git', 'show', '-s', '--format=%P', head).split()
            if parents != [args.base_sha, args.source_head_sha]:
                raise SystemExit("synthetic readiness must bind exact base and source parents in order")
        if run('git', 'status', '--porcelain=v1', '--untracked-files=all'):
            raise SystemExit("qualified readiness requires a pristine exact-candidate worktree")
        native_receipt_sha256 = sha256(args.native_receipt)

    migrations = committed_files("codex-rs/hepta-bao-adapter/migrations/*.sql", head)
    schemas = committed_files("codex-rs/hepta-bao-adapter/**/*schema*", head)
    tests = []
    for package in ("hepta-bao-adapter", "hepta-authbus", "hepta-types", "state/sqlite"):
        tests += committed_files(f"codex-rs/{package}/**/*test*.rs", head)
    tests += committed_files("codex-rs/hepta-bao-adapter/qa/test_*.py", head)
    docs = committed_files("docs/modules/secrets.heptabao/**", head)
    docs += committed_files("docs/lane-a-foundation/secrets.heptabao/**", head)
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

    dependency_lock_hash = source_digest(ROOT / "codex-rs/Cargo.lock", head)
    migration_hash = committed_tree_hash(migrations, head)
    schema_hash = committed_tree_hash(schemas, head)
    test_set_hash = committed_tree_hash(tests, head)
    qualification_profile_hash = source_digest(
        ROOT / ".github/workflows/secrets-heptabao-five-closure-qualified.yml", head
    )
    implementation_map_hash = source_digest(implementation, head)
    documentation_hash = committed_tree_hash(docs, head)

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
    product_caller_source_bound = product_caller is not None
    # A repository-owned constructor and binary target prove reviewable caller
    # source, not that a normal process instantiated its dependencies and ran.
    product_composed = False
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
        "productCallerSourceBound": product_caller_source_bound,
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
        "nativeReceiptSha256": native_receipt_sha256,
        "readinessDimensions": readiness,
        "productCallerSourceBound": product_caller_source_bound,
        "productCaller": product_caller,
        "productCallerManifestSha256": product_caller_manifest_sha256,
        "productionQualified": production_qualified,
        "mergeReady": production_qualified,
        "nonclaims": [
            "A green source qualification does not select or activate a production process.",
            "A repository-owned caller manifest proves source binding, not runtime composition or deployment.",
            "Product composition requires exact-candidate evidence that a normal process constructed and ran AuthBus, provider, consumer, metrics, recovery and shutdown wiring.",
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
