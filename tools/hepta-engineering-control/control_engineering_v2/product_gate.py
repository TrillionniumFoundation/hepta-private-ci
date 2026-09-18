"""Repository product caller for control.engineering v2.

This is a real, bounded caller of the authenticated orchestration implementation.
It is used only after the repository qualification jobs succeed. The receipt proves
product composition and exact source binding; it does not claim independent review,
merge authority, deployment, promotion or release.
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

from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from .orchestration import (
    EngineeringWorkPackage,
    ReviewCapacity,
    WorkerCapacity,
    schedule_engineering_work,
)

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
EXPECTED_REPOSITORY_ID = 1320694176
EXPECTED_WORKFLOW_PREFIX = (
    EXPECTED_REPOSITORY + "/.github/workflows/hepta-consolidated-source.yml@"
)
EXPECTED_JOB = "engineering-product-gate"


class _NoExternalReceiptVerifier:
    def verify(self, value, issuer, signing_identity, signature):
        return False


def _git(repository: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    return process.stdout.strip()


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None or value == "0" * 40:
        raise ValueError("invalid_" + label)
    return value


def _load_work_inventory(repository: Path) -> tuple[dict[str, object], dict[str, object]]:
    path = repository / "docs/delivery/WORK_PACKAGES.json"
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("work_package_inventory_too_large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid_work_package_inventory") from None
    packages = document.get("packages")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 4096:
        raise ValueError("invalid_work_package_inventory")
    ids = [row.get("id") for row in packages if isinstance(row, dict)]
    if len(ids) != len(packages) or any(
        not isinstance(value, str) or not value for value in ids
    ):
        raise ValueError("invalid_work_package_identity")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_work_package_identity")
    if any(
        row.get("authorityDelta") != "none"
        for row in packages
        if isinstance(row, dict)
    ):
        raise ValueError("work_package_authority_delta")
    engineering = [
        row
        for row in packages
        if isinstance(row, dict) and row.get("module") == "control.engineering"
    ]
    ecp = next(
        (row for row in engineering if row.get("id") == "ECP-1-ENGINEERING-CONTROL-PLANE"),
        None,
    )
    if ecp is None or ecp.get("state") != "source_implemented":
        raise ValueError("engineering_control_package_not_source_implemented")
    summary = {
        "schema": document.get("schema"),
        "packageCount": len(packages),
        "inventorySha256": hashlib.sha256(raw).hexdigest(),
        "engineeringPackageIds": tuple(sorted(row["id"] for row in engineering)),
        "engineeringPackageStates": {
            row["id"]: row.get("state") for row in sorted(engineering, key=lambda item: item["id"])
        },
        "ecpDevelopmentAfter": tuple(ecp.get("developmentAfter", ())),
        "ecpAllowedWritePaths": tuple(ecp.get("allowedWritePaths", ())),
        "ecpResourceBudget": ecp.get("resourceBudget", {}),
    }
    return summary, ecp


def build_product_receipt(
    repository: Path,
    *,
    source_sha: str,
    repository_full_name: str,
    repository_id: int,
    workflow_ref: str,
    job_name: str,
    run_id: int,
    run_attempt: int,
    event_name: str,
    pull_request_number: int,
) -> dict[str, object]:
    repository = repository.resolve()
    source_sha = _sha(source_sha, "source_sha")
    if repository_full_name != EXPECTED_REPOSITORY:
        raise ValueError("repository_identity_mismatch")
    if type(repository_id) is not int or repository_id != EXPECTED_REPOSITORY_ID:
        raise ValueError("repository_id_mismatch")
    if not isinstance(workflow_ref, str) or not workflow_ref.startswith(
        EXPECTED_WORKFLOW_PREFIX
    ):
        raise ValueError("workflow_identity_mismatch")
    if job_name != EXPECTED_JOB:
        raise ValueError("job_identity_mismatch")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("invalid_run_id")
    if type(run_attempt) is not int or run_attempt <= 0:
        raise ValueError("invalid_run_attempt")
    if event_name not in {"pull_request", "push"}:
        raise ValueError("invalid_event_name")
    if type(pull_request_number) is not int or pull_request_number < 0:
        raise ValueError("invalid_pull_request_number")
    if (event_name == "pull_request") != (pull_request_number > 0):
        raise ValueError("pull_request_identity_mismatch")

    head = _sha(_git(repository, "rev-parse", "HEAD"), "head")
    if head != source_sha:
        raise ValueError("source_head_mismatch")
    source_tree = _sha(_git(repository, "rev-parse", "HEAD^{tree}"), "source_tree")
    inventory, ecp = _load_work_inventory(repository)
    raw_paths = ecp.get("allowedWritePaths", ())
    if (
        not isinstance(raw_paths, list)
        or not raw_paths
        or any(not isinstance(value, str) for value in raw_paths)
    ):
        raise ValueError("invalid_engineering_write_paths")
    product_root = raw_paths[0].removesuffix("/**").rstrip("/")
    if not product_root:
        raise ValueError("invalid_engineering_write_paths")
    resource_budget = ecp.get("resourceBudget", {})
    if not isinstance(resource_budget, dict):
        raise ValueError("invalid_engineering_resource_budget")
    max_parallel = resource_budget.get("maxParallelAgents")
    max_ci_minutes = resource_budget.get("maxCiMinutes")
    if (
        type(max_parallel) is not int
        or not 1 <= max_parallel <= 128
        or type(max_ci_minutes) is not int
        or not 1 <= max_ci_minutes <= 4096
    ):
        raise ValueError("invalid_engineering_resource_budget")

    objective_digest = hashlib.sha256(
        b"control.engineering.repository-product-caller.v2"
    ).hexdigest()
    contract_digest = hashlib.sha256(
        b"hepta.control-engineering-orchestration.v2"
    ).hexdigest()
    now_ns = 1
    envelope = WorkEnvelope(
        envelope_id="product-" + source_sha[:24],
        source_commit=source_sha,
        source_tree=source_tree,
        objective_digest=objective_digest,
        contract_digest=contract_digest,
        owner="github-actions",
        allowed_paths=(product_root,),
        denied_authorities=tuple(sorted(DENIED_AUTHORITIES)),
        maximum_assignments=1,
        expires_unix_ns=2**63 - 1,
    )
    package = EngineeringWorkPackage(
        priority=int(ecp["priority"]),
        package_id="product-probe:" + str(ecp["id"]),
        predecessors=(),
        write_paths=(product_root,),
        required_skills=("python", "control-engineering"),
        effort_units=1,
        ci_units=max_ci_minutes,
        review_roles=("architecture_reviewer",),
        expected_value_micros=1_000_000,
        architecture_debt_micros=1_000_000,
        rollback_cost_micros=1,
    )
    worker = WorkerCapacity(
        "github-actions-product-caller",
        ("python", "control-engineering"),
        capacity_units=max_parallel,
        maximum_parallel_assignments=max_parallel,
    )
    review = ReviewCapacity("architecture_reviewer", 1)
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-product-") as directory:
        with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
            store.issue_work_envelope(envelope, now_ns=now_ns)
            plan = schedule_engineering_work(
                store,
                envelope,
                (package,),
                (worker,),
                (review,),
                ci_capacity_units=max_ci_minutes,
                completion_receipts=(),
                verifier=_NoExternalReceiptVerifier(),
                generation_id="product-generation-" + source_sha[:24],
                distributed=False,
                now_ns=now_ns,
            )

    if plan.integration_order != (package.package_id,) or len(plan.merge_queue) != 1:
        raise RuntimeError("product_orchestration_rejected_bounded_package")
    if any(
        (
            plan.runtime_authority,
            plan.merge_authority,
            plan.activation_authority,
            plan.promotion_authority,
            plan.release_authority,
            plan.merge_queue[0].merge_authority,
        )
    ):
        raise RuntimeError("product_orchestration_authority_widened")

    return {
        "schema": "hepta.control-engineering-product-execution.v2",
        "ciIdentity": {
            "repository": repository_full_name,
            "repositoryId": repository_id,
            "workflowRef": workflow_ref,
            "job": job_name,
            "runId": run_id,
            "runAttempt": run_attempt,
            "eventName": event_name,
            "pullRequestNumber": pull_request_number,
        },
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "plan": asdict(plan),
        "canonicalWorkPackageInventory": inventory,
        "canonicalPackageBinding": {
            "id": ecp["id"],
            "state": ecp["state"],
            "priority": ecp["priority"],
            "developmentAfter": tuple(ecp.get("developmentAfter", ())),
            "allowedWritePaths": tuple(raw_paths),
            "resourceBudget": resource_budget,
            "authenticatedPredecessorCompletionSupplied": False,
        },
        "namedProductCaller": "control_engineering_v2.product_gate",
        "authenticatedExternalSourceAdmission": False,
        "independentAcceptance": False,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--repository-full-name", required=True)
    parser.add_argument("--repository-id", type=int, required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--pull-request-number", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_product_receipt(
            args.repository,
            source_sha=args.source_sha,
            repository_full_name=args.repository_full_name,
            repository_id=args.repository_id,
            workflow_ref=args.workflow_ref,
            job_name=args.job_name,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            event_name=args.event_name,
            pull_request_number=args.pull_request_number,
        )
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
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
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
