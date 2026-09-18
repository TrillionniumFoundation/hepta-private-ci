"""Repository product caller for the Engineering Control Plane.

The caller runs only after repository qualification jobs succeed.  It proves that
the actual repository CI composes the v2 durable owner and resource-aware
orchestrator.  It never grants merge, deployment, promotion, release or runtime
authority.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from .evidence import HmacTrustStore
from .orchestration import (
    EngineeringCapacity,
    EngineeringWorkPackage,
    ReviewCapacity,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
EXPECTED_REPOSITORY_ID = 1320694176
EXPECTED_JOB = "engineering-product-gate"
EXPECTED_WORKFLOW_SUFFIX = "/.github/workflows/hepta-consolidated-source.yml"
CANONICAL_WORK_PACKAGE_PATH = Path("docs/delivery/WORK_PACKAGES.json")
CANONICAL_ENGINEERING_PACKAGE = "ECP-1-ENGINEERING-CONTROL-PLANE"
MAX_CANONICAL_REGISTRY_BYTES = 4 * 1024 * 1024


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("git_read_failed") from None
    if result.returncode != 0:
        raise ValueError("git_read_failed")
    return result.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("git_read_failed") from None
    if (
        result.returncode != 0
        or len(result.stdout) > MAX_CANONICAL_REGISTRY_BYTES
        or len(result.stderr) > 1_048_576
    ):
        raise ValueError("git_read_failed")
    return result.stdout


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None or value == "0" * 40:
        raise ValueError("invalid_" + label)
    return value


def _canonical_engineering_package(root: Path) -> dict[str, object]:
    """Bind the product caller to the exact HEAD blob for canonical ECP-1."""
    relative = CANONICAL_WORK_PACKAGE_PATH.as_posix()
    try:
        blob_oid = _sha(
            _git(root, "rev-parse", f"HEAD:{relative}"),
            "canonical_work_package_blob",
        )
        raw = _git_bytes(root, "cat-file", "blob", blob_oid)
    except ValueError:
        raise ValueError("canonical_work_package_registry_unavailable") from None
    if not raw or len(raw) > MAX_CANONICAL_REGISTRY_BYTES:
        raise ValueError("canonical_work_package_registry_invalid")
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("canonical_work_package_registry_invalid") from None
    if (
        not isinstance(registry, dict)
        or registry.get("documentClass") != "canonical_registry"
        or not isinstance(registry.get("schema"), str)
        or not isinstance(registry.get("schemaVersion"), int)
        or not isinstance(registry.get("packages"), list)
    ):
        raise ValueError("canonical_work_package_registry_invalid")
    matches = [
        row
        for row in registry["packages"]
        if isinstance(row, dict) and row.get("id") == CANONICAL_ENGINEERING_PACKAGE
    ]
    if len(matches) != 1:
        raise ValueError("canonical_engineering_package_identity")
    package = matches[0]
    if (
        package.get("module") != "control.engineering"
        or package.get("state") != "source_implemented"
        or package.get("authorityDelta") != "none"
        or package.get("owner") != "developer-productivity"
        or package.get("deputy") != "architecture"
        or package.get("sourceMutationAllowed") is not True
        or package.get("allowedWritePaths")
        != ["tools/hepta-engineering-control/**"]
        or package.get("developmentAfter")
        != ["DOC-2-DEFAULT-BRANCH-SELECTION"]
        or package.get("activationAfter")
        != ["DOC-2-DEFAULT-BRANCH-SELECTION"]
    ):
        raise ValueError("canonical_engineering_package_binding")
    package_bytes = json.dumps(
        package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "path": CANONICAL_WORK_PACKAGE_PATH.as_posix(),
        "schema": registry["schema"],
        "schemaVersion": registry["schemaVersion"],
        "packageId": CANONICAL_ENGINEERING_PACKAGE,
        "blobOid": blob_oid,
        "registryDigest": hashlib.sha256(raw).hexdigest(),
        "packageDigest": hashlib.sha256(package_bytes).hexdigest(),
        "state": package["state"],
        "authorityDelta": package["authorityDelta"],
        "owner": package["owner"],
        "deputy": package["deputy"],
        "sourceMutationAllowed": package["sourceMutationAllowed"],
        "allowedWritePaths": package["allowedWritePaths"],
        "developmentAfter": package["developmentAfter"],
        "activationAfter": package["activationAfter"],
    }


def build_product_receipt(
    repository: str | Path,
    *,
    repository_full_name: str,
    repository_id: int,
    workflow_ref: str,
    job_name: str,
    run_id: int,
    run_attempt: int,
    source_sha: str,
    base_sha: str | None,
    event_name: str,
    lane: str,
    pull_request_number: int,
) -> dict[str, object]:
    root = Path(repository).resolve()
    source_sha = _sha(source_sha, "source_sha")
    if repository_full_name != EXPECTED_REPOSITORY:
        raise ValueError("repository_identity_mismatch")
    if type(repository_id) is not int or repository_id != EXPECTED_REPOSITORY_ID:
        raise ValueError("repository_id_mismatch")
    if (
        not isinstance(workflow_ref, str)
        or EXPECTED_WORKFLOW_SUFFIX not in workflow_ref
    ):
        raise ValueError("workflow_identity_mismatch")
    if job_name != EXPECTED_JOB:
        raise ValueError("job_identity_mismatch")
    if type(run_id) is not int or run_id <= 0 or type(run_attempt) is not int or run_attempt <= 0:
        raise ValueError("run_identity_invalid")
    if event_name not in {"pull_request", "push"}:
        raise ValueError("event_identity_invalid")
    if lane not in {"source-head", "base-merge"}:
        raise ValueError("execution_lane_invalid")
    if lane == "base-merge" and event_name != "pull_request":
        raise ValueError("execution_lane_event_mismatch")
    if type(pull_request_number) is not int or pull_request_number < 0:
        raise ValueError("pull_request_identity_invalid")
    if (event_name == "pull_request") != (pull_request_number > 0):
        raise ValueError("pull_request_identity_mismatch")

    tested_sha = _sha(_git(root, "rev-parse", "HEAD"), "tested_sha")
    tested_tree = _sha(_git(root, "rev-parse", "HEAD^{tree}"), "tested_tree")
    source_tree = _sha(_git(root, "rev-parse", f"{source_sha}^{{tree}}"), "source_tree")
    parents = tuple(_git(root, "show", "-s", "--format=%P", "HEAD").split())

    if lane == "source-head":
        if tested_sha != source_sha:
            raise ValueError("source_head_mismatch")
        mode = "source-head"
    else:
        if base_sha is None:
            raise ValueError("missing_base_sha")
        base_sha = _sha(base_sha, "base_sha")
        if parents != (base_sha, source_sha):
            raise ValueError("ordered_merge_parent_mismatch")
        if tested_sha in {base_sha, source_sha}:
            raise ValueError("synthetic_merge_not_distinct")
        mode = "base-merge"

    canonical_package = _canonical_engineering_package(root)
    now = time.time_ns()
    envelope = WorkEnvelope(
        envelope_id=f"product-{tested_sha[:24]}",
        source_commit=tested_sha,
        source_tree=tested_tree,
        objective_digest=hashlib.sha256(
            b"control.engineering.repository-product-caller"
        ).hexdigest(),
        contract_digest=str(canonical_package["packageDigest"]),
        owner="github-actions",
        allowed_paths=("tools/hepta-engineering-control",),
        denied_authorities=tuple(sorted(DENIED_AUTHORITIES)),
        maximum_assignments=1,
        expires_unix_ns=now + 300_000_000_000,
    )
    package = EngineeringWorkPackage(
        priority=0,
        package_id="control.engineering.repository-product-gate",
        predecessors=(),
        write_paths=("tools/hepta-engineering-control",),
        required_skills=("engineering-control",),
        capacity_units=1,
        ci_units=1,
        review_roles=("architecture",),
        expected_value_q32=1,
        architecture_debt_q32=0,
        rollback_cost_q32=0,
    )
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-product-") as directory:
        with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
            issue_repository_work_envelope(
                root,
                store,
                envelope,
                expected_repository=EXPECTED_REPOSITORY,
                now_ns=now,
            )
            plan = plan_engineering_work(
                store,
                envelope,
                (package,),
                (
                    WorkerProfile(
                        "github-actions-product-caller",
                        ("engineering-control",),
                        1,
                        ("tools/hepta-engineering-control",),
                    ),
                ),
                (),
                HmacTrustStore({}),
                EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
                generation_id=f"product-generation-{tested_sha[:20]}",
                now_ns=now,
            )
            anchor = store.audit_anchor()

    if tuple(row.package_id for row in plan.assignments) != (
        "control.engineering.repository-product-gate",
    ):
        raise RuntimeError("product_assignment_not_composed")
    if any((plan.runtime_authority, plan.merge_authority, plan.release_authority)):
        raise RuntimeError("product_caller_authority_delta")

    receipt = {
        "schema": "hepta.control-engineering-product-execution.v2",
        "mode": mode,
        "ciIdentity": {
            "repository": repository_full_name,
            "repositoryId": repository_id,
            "workflowRef": workflow_ref,
            "job": job_name,
            "runId": run_id,
            "runAttempt": run_attempt,
            "eventName": event_name,
            "executionLane": lane,
            "pullRequestNumber": pull_request_number,
        },
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "testedSha": tested_sha,
        "testedTree": tested_tree,
        "orderedParents": list(parents),
        "canonicalWorkPackage": canonical_package,
        "plan": asdict(plan),
        "auditAnchor": anchor,
        "productCallerComposed": True,
        "productTestsUpstreamRequired": True,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
    }
    receipt["receiptDigest"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipt


def _verify_product_receipt(
    value: Mapping[str, object],
    *,
    expected_lane: str,
) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("product_receipt_shape")
    if (
        value.get("schema") != "hepta.control-engineering-product-execution.v2"
        or value.get("mode") != expected_lane
        or value.get("productCallerComposed") is not True
        or value.get("productTestsUpstreamRequired") is not True
    ):
        raise ValueError("product_receipt_identity")
    for authority in (
        "runtimeAuthority",
        "mergeAuthority",
        "activationAuthority",
        "promotionAuthority",
        "releaseAuthority",
        "externalEffectAuthority",
    ):
        if value.get(authority) is not False:
            raise ValueError("product_receipt_authority_delta")
    digest = value.get("receiptDigest")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("product_receipt_digest")
    unsigned = dict(value)
    unsigned.pop("receiptDigest", None)
    expected_digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if digest != expected_digest:
        raise ValueError("product_receipt_digest_mismatch")

    identity = value.get("ciIdentity")
    if not isinstance(identity, Mapping):
        raise ValueError("product_receipt_ci_identity")
    if identity.get("executionLane") != expected_lane:
        raise ValueError("product_receipt_lane_mismatch")
    canonical = value.get("canonicalWorkPackage")
    if not isinstance(canonical, Mapping):
        raise ValueError("product_receipt_canonical_binding")
    if (
        canonical.get("path") != CANONICAL_WORK_PACKAGE_PATH.as_posix()
        or canonical.get("packageId") != CANONICAL_ENGINEERING_PACKAGE
        or canonical.get("state") != "source_implemented"
        or canonical.get("authorityDelta") != "none"
        or canonical.get("owner") != "developer-productivity"
        or canonical.get("deputy") != "architecture"
        or canonical.get("sourceMutationAllowed") is not True
        or canonical.get("allowedWritePaths")
        != ["tools/hepta-engineering-control/**"]
        or canonical.get("developmentAfter")
        != ["DOC-2-DEFAULT-BRANCH-SELECTION"]
        or canonical.get("activationAfter")
        != ["DOC-2-DEFAULT-BRANCH-SELECTION"]
    ):
        raise ValueError("product_receipt_canonical_binding")
    blob_oid = canonical.get("blobOid")
    if (
        not isinstance(blob_oid, str)
        or _SHA1.fullmatch(blob_oid) is None
        or blob_oid == "0" * 40
    ):
        raise ValueError("product_receipt_canonical_blob")
    for key in ("registryDigest", "packageDigest"):
        item = canonical.get(key)
        if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
            raise ValueError("product_receipt_canonical_digest")

    plan = value.get("plan")
    if not isinstance(plan, Mapping):
        raise ValueError("product_receipt_plan")
    assignments = plan.get("assignments")
    if (
        not isinstance(assignments, list)
        or len(assignments) != 1
        or not isinstance(assignments[0], Mapping)
        or assignments[0].get("package_id")
        != "control.engineering.repository-product-gate"
    ):
        raise ValueError("product_receipt_plan")
    for authority in ("runtime_authority", "merge_authority", "release_authority"):
        if plan.get(authority) is not False:
            raise ValueError("product_receipt_plan_authority_delta")
    return digest


def verify_product_receipt_pair(
    source_head: Mapping[str, object],
    base_merge: Mapping[str, object],
    *,
    expected_repository: str,
    expected_repository_id: int,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_source_sha: str,
    expected_base_sha: str,
    expected_pull_request_number: int,
) -> dict[str, object]:
    """Verify the two independently executed PR product-caller lanes."""
    expected_source_sha = _sha(expected_source_sha, "source_sha")
    expected_base_sha = _sha(expected_base_sha, "base_sha")
    source_digest = _verify_product_receipt(
        source_head,
        expected_lane="source-head",
    )
    merge_digest = _verify_product_receipt(
        base_merge,
        expected_lane="base-merge",
    )

    source_identity = source_head["ciIdentity"]
    merge_identity = base_merge["ciIdentity"]
    if not isinstance(source_identity, Mapping) or not isinstance(
        merge_identity, Mapping
    ):
        raise ValueError("product_receipt_pair_ci_identity")
    for identity in (source_identity, merge_identity):
        if (
            identity.get("repository") != expected_repository
            or identity.get("repositoryId") != expected_repository_id
            or identity.get("runId") != expected_run_id
            or identity.get("runAttempt") != expected_run_attempt
            or identity.get("eventName") != "pull_request"
            or identity.get("pullRequestNumber") != expected_pull_request_number
            or identity.get("job") != EXPECTED_JOB
        ):
            raise ValueError("product_receipt_pair_ci_identity")
        workflow_ref = identity.get("workflowRef")
        if (
            not isinstance(workflow_ref, str)
            or EXPECTED_WORKFLOW_SUFFIX not in workflow_ref
        ):
            raise ValueError("product_receipt_pair_workflow_identity")

    if (
        source_head.get("sourceSha") != expected_source_sha
        or base_merge.get("sourceSha") != expected_source_sha
        or source_head.get("testedSha") != expected_source_sha
    ):
        raise ValueError("product_receipt_pair_source_identity")
    source_tree = source_head.get("sourceTree")
    if (
        not isinstance(source_tree, str)
        or _SHA1.fullmatch(source_tree) is None
        or source_head.get("testedTree") != source_tree
        or base_merge.get("sourceTree") != source_tree
    ):
        raise ValueError("product_receipt_pair_source_tree")
    merge_sha = base_merge.get("testedSha")
    merge_tree = base_merge.get("testedTree")
    if (
        not isinstance(merge_sha, str)
        or _SHA1.fullmatch(merge_sha) is None
        or merge_sha in {expected_base_sha, expected_source_sha}
        or not isinstance(merge_tree, str)
        or _SHA1.fullmatch(merge_tree) is None
        or base_merge.get("orderedParents")
        != [expected_base_sha, expected_source_sha]
    ):
        raise ValueError("product_receipt_pair_merge_identity")

    source_canonical = source_head["canonicalWorkPackage"]
    merge_canonical = base_merge["canonicalWorkPackage"]
    if not isinstance(source_canonical, Mapping) or not isinstance(
        merge_canonical, Mapping
    ):
        raise ValueError("product_receipt_pair_canonical_drift")
    for key in ("blobOid", "registryDigest", "packageDigest"):
        if source_canonical.get(key) != merge_canonical.get(key):
            raise ValueError("product_receipt_pair_canonical_drift")

    pair = {
        "schema": "hepta.control-engineering-product-receipt-pair.v1",
        "repository": expected_repository,
        "repositoryId": expected_repository_id,
        "runId": expected_run_id,
        "runAttempt": expected_run_attempt,
        "pullRequestNumber": expected_pull_request_number,
        "sourceSha": expected_source_sha,
        "sourceTree": source_tree,
        "baseSha": expected_base_sha,
        "mergeSha": merge_sha,
        "mergeTree": merge_tree,
        "sourceProductReceiptDigest": source_digest,
        "mergeProductReceiptDigest": merge_digest,
        "canonicalWorkPackageBlobOid": source_canonical["blobOid"],
        "canonicalWorkPackageDigest": source_canonical["packageDigest"],
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "releaseAuthority": False,
    }
    expected_readiness_digest = hashlib.sha256(
        json.dumps(
            {
                "baseMerge": merge_digest,
                "sourceHead": source_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pair["readinessReceiptSetDigest"] = expected_readiness_digest
    pair["pairDigest"] = semantic_pair_digest = hashlib.sha256(
        json.dumps(pair, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if semantic_pair_digest == expected_readiness_digest:
        raise ValueError("product_receipt_pair_domain_collision")
    return pair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-full-name", required=True)
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--lane", required=True, choices=("source-head", "base-merge"))
    parser.add_argument("--pull-request-number", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = build_product_receipt(
            args.repository,
            repository_full_name=args.repository_full_name,
            repository_id=args.repository_id,
            workflow_ref=args.workflow_ref,
            job_name=args.job_name,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            source_sha=args.source_sha,
            base_sha=args.base_sha,
            event_name=args.event_name,
            lane=args.lane,
            pull_request_number=args.pull_request_number,
        )
    except (RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "hepta.control-engineering-product-execution.v2",
                    "status": "rejected",
                    "error": str(error),
                    "authorityGranted": False,
                },
                sort_keys=True,
            )
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
