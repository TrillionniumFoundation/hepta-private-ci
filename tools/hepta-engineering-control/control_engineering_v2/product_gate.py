"""Repository CI product caller for control.engineering.

This module turns already-successful repository qualification into a bounded,
machine-readable engineering-control receipt. It does not merge, deploy,
promote, or release anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from hepta_engineering_control import IntegrationEvidence, decide_integration

from .control_plane import DENIED_AUTHORITIES
from .control_plane import EngineeringStore
from .control_plane import WorkEnvelope
from .control_plane import WorkPackage

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
EXPECTED_REPOSITORY_ID = 1320694176
EXPECTED_WORKFLOW_PREFIX = (
    EXPECTED_REPOSITORY
    + "/.github/workflows/hepta-consolidated-source.yml@"
)
EXPECTED_JOB = "engineering-product-gate"


def _git(repository: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )
    return process.stdout.strip()


def _checked_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None or value == "0" * 40:
        raise ValueError(f"invalid_{label}")
    return value


def build_product_receipt(
    repository: Path,
    *,
    mode: str,
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
    """Bind a qualified Git candidate to the engineering-control product caller."""

    repository = repository.resolve()
    source_sha = _checked_sha(source_sha, "source_sha")
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
    head = _checked_sha(_git(repository, "rev-parse", "HEAD"), "head")
    head_tree = _checked_sha(
        _git(repository, "rev-parse", "HEAD^{tree}"), "head_tree"
    )

    if mode == "source-head":
        if head != source_sha:
            raise ValueError("source_head_mismatch")
        source_tree = head_tree
        parents: tuple[str, ...] = ()
    elif mode == "base-merge":
        if base_sha is None:
            raise ValueError("missing_base_sha")
        base_sha = _checked_sha(base_sha, "base_sha")
        parents = tuple(_git(repository, "show", "-s", "--format=%P", "HEAD").split())
        if parents != (base_sha, source_sha):
            raise ValueError("ordered_merge_parent_mismatch")
        source_tree = _checked_sha(
            _git(repository, "rev-parse", f"{source_sha}^{{tree}}"), "source_tree"
        )
    else:
        raise ValueError("invalid_mode")

    now_ns = time.time_ns()
    objective_digest = hashlib.sha256(
        b"control.engineering.ci-product-gate"
    ).hexdigest()
    contract_digest = hashlib.sha256(
        b"hepta.control-engineering-product-execution.v1"
    ).hexdigest()
    envelope = WorkEnvelope(
        envelope_id=f"ci-{source_sha[:24]}",
        source_commit=source_sha,
        source_tree=source_tree,
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
        "control.engineering.ci-product-gate",
        (),
        ("tools/hepta-engineering-control",),
    )
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-product-") as directory:
        with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
            store.issue_work_envelope(envelope, now_ns=now_ns)
            scheduling = store.schedule_ready_packages(
                envelope.envelope_id,
                (package,),
                (),
                generation_id=f"ci-generation-{head[:24]}",
                now_ns=now_ns,
            )
            frontier = store.assignment_frontier(scheduling.generation_id)
    if scheduling.assigned != ("control.engineering.ci-product-gate",):
        raise RuntimeError("product_scheduler_rejected_own_bounded_package")
    if any(
        (
            scheduling.runtime_authority,
            scheduling.merge_authority,
            scheduling.activation_authority,
            scheduling.promotion_authority,
            scheduling.release_authority,
        )
    ):
        raise RuntimeError("product_scheduler_authority_widened")

    receipt: dict[str, object] = {
        "schema": "hepta.control-engineering-product-execution.v1",
        "mode": mode,
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
        "testedSha": head,
        "testedTree": head_tree,
        "durableGenerationId": scheduling.generation_id,
        "assignmentFrontierDigest": frontier["frontierDigest"],
        "schedulerAssigned": list(scheduling.assigned),
        "eligibleForIndependentReview": False,
        "runtimeAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
        "externalEffectAuthority": False,
    }

    if mode == "source-head":
        return receipt
    evidence = IntegrationEvidence(
        candidate_head=source_sha,
        exact_head=source_sha,
        merge_candidate_head=head,
        base_head=base_sha,
        source_tree=source_tree,
        exact_head_tree=source_tree,
        merge_candidate_tree=head_tree,
        expected_merge_tree=head_tree,
        merge_candidate_parents=parents,
        source_execution_ok=True,
        merge_execution_ok=True,
        source_inventory_ok=True,
        static_verification_ok=True,
        focused_tests_ok=True,
        package_tests_ok=True,
        all_target_check_ok=True,
        strict_lint_ok=True,
        clean_worktree_ok=True,
        authority_delta=False,
    )
    decision = decide_integration(evidence)
    if not decision.eligible_for_independent_review or decision.reasons:
        raise RuntimeError(
            "integration_eligibility_rejected:" + ",".join(decision.reasons)
        )
    if any(
        (
            decision.runtime_authority,
            decision.merge_authority,
            decision.promotion_authority,
            decision.release_authority,
        )
    ):
        raise RuntimeError("integration_decision_authority_widened")

    receipt.update(
        {
            "baseSha": base_sha,
            "mergeParents": list(parents),
            "eligibleForIndependentReview": True,
        }
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--mode", choices=("source-head", "base-merge"), required=True)
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
            mode=args.mode,
            source_sha=args.source_sha,
            repository_full_name=args.repository_full_name,
            repository_id=args.repository_id,
            workflow_ref=args.workflow_ref,
            job_name=args.job_name,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            event_name=args.event_name,
            pull_request_number=args.pull_request_number,
            base_sha=args.base_sha,
        )
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "hepta.control-engineering-product-execution.v1",
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
