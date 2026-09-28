#!/usr/bin/env python3
"""Rebind the control.engineering implementation map to exact current Git objects.

This is an explicit source-maintenance migration, not a qualification workflow.
It keeps production/deployment/authority claims false and never consumes its own
output as execution evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def object_id(root: Path, path: str) -> str:
    value = git(root, "rev-parse", f"HEAD:{path}")
    if _SHA1.fullmatch(value) is None:
        raise RuntimeError(f"invalid object id for {path}: {value!r}")
    return value


def operation(
    root: Path,
    *,
    name: str,
    design: str,
    symbol: str,
    source: str,
    tests: tuple[str, ...],
    delegated: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, object]:
    return {
        "operation": name,
        "designOperation": design,
        "nativeSymbol": symbol,
        "sourcePath": source,
        "state": "source_implemented",
        "authority": "none",
        "tests": [{"path": path} for path in tests],
        "sourcePathExists": True,
        "mappingClass": "owner_native",
        "delegatedCallees": [
            {"path": path, "symbol": callee, "role": role}
            for path, callee, role in delegated
        ],
        "sourceBlob": object_id(root, source),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--observed-commit", required=True)
    parser.add_argument("--observed-tree", required=True)
    args = parser.parse_args(argv)

    root = args.repository.resolve()
    path = args.map.resolve()
    if _SHA1.fullmatch(args.observed_commit) is None or _SHA1.fullmatch(
        args.observed_tree
    ) is None:
        raise ValueError("invalid observed identity")
    if git(root, "rev-parse", "HEAD") != args.observed_commit:
        raise RuntimeError("observed commit is not current HEAD")
    if git(root, "rev-parse", "HEAD^{tree}") != args.observed_tree:
        raise RuntimeError("observed tree is not current HEAD tree")

    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "hepta.module-implementation-map.v3"
        or value.get("module") != "control.engineering"
    ):
        raise ValueError("unexpected implementation map")

    value["productionImplementation"] = False
    value["productCallerState"] = (
        "required_pr_dual_lane_and_post_merge_main_defined_execution_pending"
    )
    value["productionWriterState"] = (
        "named_product_owner_composed_external_provider_receipts_pending"
    )
    value["observedAtHead"] = {
        "commit": args.observed_commit,
        "tree": args.observed_tree,
    }
    value["observedSourcePaths"] = ["tools/hepta-engineering-control"]
    value["repositoryControlledGaps"] = [
        "Retain successful source-head and deterministic base-merge required qualification receipts for the exact pull-request head.",
        "Retain a successful exact-SHA product, quality, strong-sandbox and host-profile receipt for the final protected-main merge commit.",
        "Keep merge-commit ancestry for exact_blob implementation-map observations; squash/rebase is not qualified for this change.",
        "Retain independently generated coverage, type-check, lint, API-compatibility, mutation and durability-soak reports for the same exact candidate.",
        "Product and CI reference signatures are qualification fixtures only; they do not prove independent semantic acceptance or production key custody.",
    ]
    value["externalEvidenceGates"] = [
        "non-author independent semantic review acceptance bound to the exact source",
        "real distributed lease/fencing provider and external immutable audit anchor",
        "role-separated HSM/KMS custody for critical signing identities",
        "non-fixture independent completion and integration-terminal observers",
        "authorized target deployment, backup/restore and rollback rehearsal",
        "separately signed operator acceptance and release authority",
    ]
    value["claimBoundary"] = {
        "nativeSourceMappingComplete": True,
        "sourceRootPresent": True,
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "implementedOperationMappingComplete": True,
    }
    value["currentCandidateIdentityAuthority"] = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "authority": (
            "required source-head and deterministic synthetic-merge receipts plus "
            "an exact protected-main post-merge receipt"
        ),
        "embeddedCommit": False,
        "reason": (
            "sourceBase remains integration provenance; exact blobs bind current "
            "operation bytes, merge-commit ancestry preserves the explicit source "
            "observation, and CI receipts bind actual execution identities."
        ),
    }

    definitions = (
        operation(
            root,
            name="validate_receipt_window",
            design="clock_and_receipt_skew_policy",
            symbol="validate_receipt_window",
            source="tools/hepta-engineering-control/control_engineering_v2/clock_policy.py",
            tests=("tools/hepta-engineering-control/test_governance_convergence.py",),
        ),
        operation(
            root,
            name="rotate_worker_registration",
            design="worker_registration_renewal_and_key_rotation",
            symbol="rotate_worker_registration",
            source="tools/hepta-engineering-control/control_engineering_v2/worker_registration_governance.py",
            tests=("tools/hepta-engineering-control/test_governance_convergence.py",),
            delegated=((
                "tools/hepta-engineering-control/control_engineering_v2/evidence.py",
                "SignatureTrustStore.verify",
                "signature_verifier",
            ),),
        ),
        operation(
            root,
            name="build_audit_checkpoint",
            design="incremental_audit_checkpoint",
            symbol="build_audit_checkpoint",
            source="tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py",
            tests=("tools/hepta-engineering-control/test_governance_convergence.py",),
            delegated=((
                "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
                "store_snapshot_digest",
                "complete_owner_snapshot",
            ),),
        ),
        operation(
            root,
            name="evaluate_engineering_capacity",
            design="sqlite_capacity_and_migration_policy",
            symbol="evaluate_engineering_capacity",
            source="tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py",
            tests=("tools/hepta-engineering-control/test_governance_convergence.py",),
        ),
        operation(
            root,
            name="run_durability_soak",
            design="repeated_reopen_wal_and_integrity_qualification",
            symbol="run_durability_soak",
            source="tools/hepta-engineering-control/control_engineering_v2/durability_soak.py",
            tests=("tools/hepta-engineering-control/test_governance_convergence.py",),
        ),
        operation(
            root,
            name="verify_quality_gate",
            design="signed_quality_evidence_gate",
            symbol="verify_quality_gate",
            source="tools/hepta-engineering-control/control_engineering_v2/quality_gate.py",
            tests=("tools/hepta-engineering-control/test_external_release_convergence.py",),
            delegated=((
                "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py",
                "validate_receipt_window",
                "freshness_policy",
            ),),
        ),
        operation(
            root,
            name="invoke_external_provider",
            design="certificate_pinned_external_receipt_transport",
            symbol="ExternalReceiptClient.invoke",
            source="tools/hepta-engineering-control/control_engineering_v2/external_runtime.py",
            tests=("tools/hepta-engineering-control/test_external_release_convergence.py",),
        ),
        operation(
            root,
            name="verify_release_receipts",
            design="exact_main_review_deployment_rollback_operator_gate",
            symbol="verify_release_receipts",
            source="tools/hepta-engineering-control/control_engineering_v2/release_qualification.py",
            tests=("tools/hepta-engineering-control/test_external_release_convergence.py",),
        ),
        operation(
            root,
            name="evaluate_release_qualification",
            design="fail_closed_release_qualification_projection",
            symbol="evaluate_release_qualification",
            source="tools/hepta-engineering-control/control_engineering_v2/release_qualification.py",
            tests=("tools/hepta-engineering-control/test_external_release_convergence.py",),
        ),
        operation(
            root,
            name="build_control_engineering_status",
            design="single_canonical_status_projection",
            symbol="build_status",
            source="tools/hepta-engineering-control/control_engineering_v2/status.py",
            tests=("tools/hepta-engineering-control/test_external_release_convergence.py",),
        ),
        operation(
            root,
            name="run_required_qualification",
            design="required_pr_and_post_merge_exact_candidate_qualification",
            symbol="main",
            source="tools/hepta-engineering-control/required_qualification.py",
            tests=(
                "tools/hepta-engineering-control/test_governance_convergence.py",
                "tools/hepta-engineering-control/test_external_release_convergence.py",
            ),
        ),
        operation(
            root,
            name="run_real_mutation_campaign",
            design="public_api_and_real_mutation_quality_campaign",
            symbol="run_mutation_campaign",
            source="tools/hepta-engineering-control/quality_campaign.py",
            tests=(
                "tools/hepta-engineering-control/test_governance_convergence.py",
                "tools/hepta-engineering-control/test_external_release_convergence.py",
            ),
        ),
    )
    operations = value.get("operations")
    if not isinstance(operations, list):
        raise ValueError("implementation map operations missing")
    by_name = {
        row.get("operation"): row
        for row in operations
        if isinstance(row, dict) and isinstance(row.get("operation"), str)
    }
    for row in definitions:
        by_name[row["operation"]] = row
    value["operations"] = [by_name[name] for name in sorted(by_name)]

    product_callers = value.get("productCallers")
    if not isinstance(product_callers, list):
        product_callers = []
    callers = {
        row.get("sourcePath"): row
        for row in product_callers
        if isinstance(row, dict) and isinstance(row.get("sourcePath"), str)
    }
    callers["tools/hepta-engineering-control/control_engineering_v2/product_runtime.py"] = {
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py",
        "nativeSymbol": "EngineeringControlProduct",
        "state": "named_product_runtime_not_independent_acceptance",
    }
    callers["tools/hepta-engineering-control/control_engineering_v2/product_gate.py"] = {
        "sourcePath": "tools/hepta-engineering-control/control_engineering_v2/product_gate.py",
        "nativeSymbol": "main",
        "state": "required_pr_and_post_merge_qualification_cli_not_merge_authority",
    }
    callers["tools/hepta-engineering-control/required_qualification.py"] = {
        "sourcePath": "tools/hepta-engineering-control/required_qualification.py",
        "nativeSymbol": "main",
        "state": "required_exact_candidate_quality_and_product_caller",
    }
    value["productCallers"] = [callers[name] for name in sorted(callers)]

    permanent_paths = (
        ".github/workflows/blocking-ci.yml",
        "docs/modules/control.engineering/TECHNICAL.md",
        "tools/hepta-engineering-control",
        "tools/hepta-engineering-control/PRODUCTION_CONVERGENCE.md",
        "tools/hepta-engineering-control/QUALITY_API.json",
        "tools/hepta-engineering-control/STATUS.json",
        "tools/hepta-engineering-control/quality-requirements.txt",
        "tools/hepta-engineering-control/quality_campaign.py",
        "tools/hepta-engineering-control/required_qualification.py",
        "tools/hepta-engineering-control/control_engineering_v2/SCHEMA.sql",
        "tools/hepta-engineering-control/control_engineering_v2/audit_checkpoint.py",
        "tools/hepta-engineering-control/control_engineering_v2/candidate.py",
        "tools/hepta-engineering-control/control_engineering_v2/capacity_policy.py",
        "tools/hepta-engineering-control/control_engineering_v2/clock_policy.py",
        "tools/hepta-engineering-control/control_engineering_v2/control_plane.py",
        "tools/hepta-engineering-control/control_engineering_v2/durability_soak.py",
        "tools/hepta-engineering-control/control_engineering_v2/evidence.py",
        "tools/hepta-engineering-control/control_engineering_v2/external_controls.py",
        "tools/hepta-engineering-control/control_engineering_v2/external_runtime.py",
        "tools/hepta-engineering-control/control_engineering_v2/hardening.py",
        "tools/hepta-engineering-control/control_engineering_v2/integration_controller.py",
        "tools/hepta-engineering-control/control_engineering_v2/mutation_testing.py",
        "tools/hepta-engineering-control/control_engineering_v2/orchestration.py",
        "tools/hepta-engineering-control/control_engineering_v2/product_gate.py",
        "tools/hepta-engineering-control/control_engineering_v2/product_runtime.py",
        "tools/hepta-engineering-control/control_engineering_v2/qualification_profile.py",
        "tools/hepta-engineering-control/control_engineering_v2/quality_gate.py",
        "tools/hepta-engineering-control/control_engineering_v2/release_qualification.py",
        "tools/hepta-engineering-control/control_engineering_v2/sandbox_control.py",
        "tools/hepta-engineering-control/control_engineering_v2/seal.py",
        "tools/hepta-engineering-control/control_engineering_v2/status.py",
        "tools/hepta-engineering-control/control_engineering_v2/worker_lifecycle.py",
        "tools/hepta-engineering-control/control_engineering_v2/worker_registration_governance.py",
        "tools/hepta-engineering-control/test_external_release_convergence.py",
        "tools/hepta-engineering-control/test_governance_convergence.py",
    )
    value["sourceObjects"] = [
        {"path": source, "object": object_id(root, source)}
        for source in sorted(permanent_paths)
    ]

    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
