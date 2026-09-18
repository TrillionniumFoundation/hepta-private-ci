"""Repository product caller for the v2 engineering-control plane.

This caller is deliberately read-only with respect to the repository.  It binds
the exact Git identity, exercises the typed orchestration planner and the durable
SQLite assignment owner, and emits a machine-readable product-execution receipt.
It grants no merge, deployment, activation, promotion, release, or runtime
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

from .control_plane import (
    DENIED_AUTHORITIES,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    semantic_digest,
)
from .orchestration import (
    CiCapacity,
    EngineeringWorkItem,
    ReviewCapacity,
    WorkerProfile,
    plan_engineering_work,
)

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
EXPECTED_REPOSITORY_ID = 1320694176
EXPECTED_JOB = "engineering-product-gate"
EXPECTED_WORKFLOW = ".github/workflows/hepta-consolidated-source.yml"


def _git(repository: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return process.stdout.strip()


def _checked_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None or value == "0" * 40:
        raise ValueError(f"invalid_{label}")
    return value


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
    base_sha: str | None = None,
) -> dict[str, object]:
    """Exercise the v2 product boundary against an exact repository identity."""

    repository = repository.resolve()
    source_sha = _checked_sha(source_sha, "source_sha")
    if repository_full_name != EXPECTED_REPOSITORY:
        raise ValueError("repository_identity_mismatch")
    if type(repository_id) is not int or repository_id != EXPECTED_REPOSITORY_ID:
        raise ValueError("repository_id_mismatch")
    prefix = EXPECTED_REPOSITORY + "/" + EXPECTED_WORKFLOW + "@"
    if not isinstance(workflow_ref, str) or not workflow_ref.startswith(prefix):
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

    head = _checked_sha(_git(repository, "rev-parse", "HEAD"), "head")
    head_tree = _checked_sha(_git(repository, "rev-parse", "HEAD^{tree}"), "head_tree")
    if event_name == "push":
        if head != source_sha:
            raise ValueError("source_head_mismatch")
        ordered_parents: tuple[str, ...] = tuple(
            _git(repository, "show", "-s", "--format=%P", "HEAD").split()
        )
    else:
        if base_sha is None:
            raise ValueError("missing_base_sha")
        base_sha = _checked_sha(base_sha, "base_sha")
        ordered_parents = tuple(
            _git(repository, "show", "-s", "--format=%P", "HEAD").split()
        )
        if ordered_parents != (base_sha, source_sha):
            raise ValueError("ordered_merge_parent_mismatch")

    now_ns = time.time_ns()
    orchestration = plan_engineering_work(
        (
            EngineeringWorkItem(
                package_id="control.engineering.product-caller",
                priority=0,
                predecessors=(),
                write_paths=("tools/hepta-engineering-control",),
                required_skills=("engineering-control",),
                effort_units=1,
                ci_units=1,
                review_roles=("architecture",),
                expected_value=100,
                architecture_debt_reduction=10,
                rollback_cost=1,
            ),
        ),
        (),
        (WorkerProfile("github-actions", ("engineering-control",), 1, 1),),
        (ReviewCapacity("architecture", 1),),
        (CiCapacity("qualified-linux", 1),),
    )
    if orchestration.merge_queue != ("control.engineering.product-caller",):
        raise RuntimeError("orchestration_product_package_not_admitted")

    objective_digest = hashlib.sha256(
        b"control.engineering.repository-product-caller"
    ).hexdigest()
    contract_digest = hashlib.sha256(
        b"hepta.control-engineering-product-caller.v2"
    ).hexdigest()
    envelope = WorkEnvelope(
        envelope_id=f"product-{source_sha[:24]}",
        source_commit=source_sha,
        source_tree=_checked_sha(
            _git(repository, "rev-parse", f"{source_sha}^{{tree}}"),
            "source_tree",
        ),
        objective_digest=objective_digest,
        contract_digest=contract_digest,
        owner="github-actions",
        allowed_paths=("tools/hepta-engineering-control",),
        denied_authorities=tuple(sorted(DENIED_AUTHORITIES)),
        maximum_assignments=1,
        expires_unix_ns=now_ns + 300_000_000_000,
    )
    package = WorkPackage(
        0,
        orchestration.merge_queue[0],
        (),
        ("tools/hepta-engineering-control",),
    )

    with tempfile.TemporaryDirectory(prefix="hepta-engineering-product-") as directory:
        with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
            store.issue_work_envelope(envelope, now_ns=now_ns)
            schedule = store.schedule_ready_packages(
                envelope.envelope_id,
                (package,),
                (),
                generation_id=f"product-generation-{head[:24]}",
                now_ns=now_ns,
            )
            frontier = store.assignment_frontier(schedule.generation_id)

    if schedule.assigned != (package.package_id,):
        raise RuntimeError("durable_scheduler_rejected_product_package")

    receipt: dict[str, object] = {
        "schema": "hepta.control-engineering-product-execution.v2",
        "repository": repository_full_name,
        "repositoryId": repository_id,
        "sourceSha": source_sha,
        "sourceTree": envelope.source_tree,
        "testedSha": head,
        "testedTree": head_tree,
        "orderedParents": list(ordered_parents),
        "workflowRef": workflow_ref,
        "job": job_name,
        "runId": run_id,
        "runAttempt": run_attempt,
        "eventName": event_name,
        "pullRequestNumber": pull_request_number,
        "orchestrationPlanDigest": semantic_digest(asdict(orchestration)),
        "workerAssignment": asdict(orchestration.assignments[0]),
        "integrationOrder": [asdict(row) for row in orchestration.integration_order],
        "mergeQueueProposal": list(orchestration.merge_queue),
        "durableAssignmentGeneration": schedule.generation_id,
        "assignmentFrontierDigest": frontier["frontierDigest"],
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
        "independentAcceptance": False,
    }
    receipt["receiptDigest"] = semantic_digest(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha")
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
            base_sha=args.base_sha,
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
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
