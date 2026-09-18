"""Repository product caller for the Engineering Control Plane.

The caller runs only after repository qualification jobs succeed.  It proves that
the actual repository CI composes the v2 durable owner and resource-aware
orchestrator.  It never grants merge, deployment, promotion, release or runtime
authority.
"""

from __future__ import annotations

import argparse
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


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None or value == "0" * 40:
        raise ValueError("invalid_" + label)
    return value


def _canonical_engineering_package(root: Path) -> dict[str, object]:
    """Bind the product caller to the canonical ECP-1 delivery definition."""
    path = root / CANONICAL_WORK_PACKAGE_PATH
    try:
        raw = path.read_bytes()
    except OSError:
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
        "registryDigest": hashlib.sha256(raw).hexdigest(),
        "packageDigest": hashlib.sha256(package_bytes).hexdigest(),
        "state": package["state"],
        "authorityDelta": package["authorityDelta"],
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
