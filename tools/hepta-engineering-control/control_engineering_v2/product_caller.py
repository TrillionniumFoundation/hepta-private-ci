"""Named repository product caller for the v2 engineering control plane.

This caller is deliberately read-only with respect to GitHub. It proves that the
repository CI composes authenticated source issuance, rich orchestration,
durable assignment projection and exact integration-evidence verification through
control_engineering_v2. It never imports the legacy boolean-only integration API
and never merges, deploys, promotes or releases.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from .control_plane import DENIED_AUTHORITIES, EngineeringStore, WorkEnvelope
from .evidence import (
    CanonicalSourceReceipt,
    EvaluatorIndependenceReceipt,
    ExecutionReceipt,
    HmacTrustStore,
    verify_integration_evidence,
)
from .orchestration import (
    EngineeringWorkPackage,
    ReviewCapacity,
    WorkerCapacity,
    issue_verified_work_envelope,
    orchestration_generation,
    persist_orchestration_generation,
    plan_engineering_work,
)

EXPECTED_REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
EXPECTED_REPOSITORY_ID = 1320694176
PRODUCT_CALLER_ID = "github-actions:control-engineering-v2-product-gate"
EXPECTED_JOB = "engineering-product-gate-v2"


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


def _sha1(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or value == "0" * 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError("invalid_" + label)
    return value


def _document_set_digest(repository: Path, commit: str) -> str:
    """Digest the registered document bytes from one exact Git commit."""
    digest = hashlib.sha256()
    paths = (
        "docs/DEVELOPMENT.md",
        "docs/modules/control.engineering/TECHNICAL.md",
        "docs/modules/control.engineering/IMPLEMENTATION.md",
        "docs/modules/control.engineering/IMPLEMENTATION_BINDING.md",
        "docs/modules/control.engineering/COMPONENTS.json",
        "docs/modules/control.engineering/TRACEABILITY.json",
    )
    for relative in paths:
        process = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        if process.returncode != 0:
            raise ValueError("document_set_git_read_failed")
        data = process.stdout
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _reference_trust_store() -> HmacTrustStore:
    # These deterministic keys are only for repository product-path execution.
    # Production/deployment readiness still requires an external key-custody receipt.
    return HmacTrustStore(
        {
            ("source_authority", "ci-source-reference"): b"hepta-ci-source-reference-v1",
            ("ci_executor", "ci-execution-reference"): b"hepta-ci-execution-reference-v1",
            ("independent_evaluator", "ci-evaluator-reference"): b"hepta-ci-evaluator-reference-v1",
        }
    )


def _signed(store: HmacTrustStore, value, issuer: str, identity: str):
    return replace(value, signature=store.sign(value, issuer, identity))


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
    repository = repository.resolve()
    source_sha = _sha1(source_sha, "source_sha")
    if repository_full_name != EXPECTED_REPOSITORY:
        raise ValueError("repository_identity_mismatch")
    if repository_id != EXPECTED_REPOSITORY_ID:
        raise ValueError("repository_id_mismatch")
    if job_name != EXPECTED_JOB:
        raise ValueError("job_identity_mismatch")
    if not workflow_ref or EXPECTED_REPOSITORY not in workflow_ref:
        raise ValueError("workflow_identity_mismatch")
    if type(run_id) is not int or run_id <= 0 or type(run_attempt) is not int or run_attempt <= 0:
        raise ValueError("invalid_run_identity")
    if event_name not in {"pull_request", "push"}:
        raise ValueError("invalid_event_name")
    if (event_name == "pull_request") != (pull_request_number > 0):
        raise ValueError("pull_request_identity_mismatch")

    head = _sha1(_git(repository, "rev-parse", "HEAD"), "head")
    head_tree = _sha1(_git(repository, "rev-parse", "HEAD^{tree}"), "head_tree")
    source_tree = _sha1(
        _git(repository, "rev-parse", f"{source_sha}^{{tree}}"), "source_tree"
    )
    if mode == "source-head" and head != source_sha:
        raise ValueError("source_head_mismatch")
    if mode not in {"source-head", "synthetic-merge"}:
        raise ValueError("invalid_mode")

    now = time.time_ns()
    expires = now + 300_000_000_000
    trust = _reference_trust_store()
    document_digest = _document_set_digest(repository, source_sha)
    source_receipt = CanonicalSourceReceipt(
        repository_full_name,
        source_sha,
        source_tree,
        document_digest,
        "source_authority",
        "ci-source-reference",
        now,
        expires,
    )
    source_receipt = _signed(
        trust, source_receipt, source_receipt.issuer, source_receipt.signing_identity
    )

    envelope = WorkEnvelope(
        envelope_id=f"product-{source_sha[:24]}",
        source_commit=source_sha,
        source_tree=source_tree,
        objective_digest=hashlib.sha256(b"engineering-product-composition-v2").hexdigest(),
        contract_digest=hashlib.sha256(b"hepta.control-engineering-v2-product-caller").hexdigest(),
        owner=PRODUCT_CALLER_ID,
        allowed_paths=("tools/hepta-engineering-control",),
        denied_authorities=tuple(sorted(DENIED_AUTHORITIES)),
        maximum_assignments=1,
        expires_unix_ns=expires,
    )
    package = EngineeringWorkPackage(
        priority=0,
        package_id="control.engineering.product-composition",
        predecessors=(),
        write_paths=("tools/hepta-engineering-control",),
        required_skills=("engineering-control",),
        worker_capacity_units=1,
        ci_capacity_units=1,
        review_roles=("architecture_reviewer",),
        expected_value_micros=1_000_000,
        architecture_debt_reduction_micros=1_000_000,
        rollback_cost_micros=100_000,
        integration_group="lane-g",
    )
    workers = (
        WorkerCapacity(
            "github-actions-engineering-worker",
            ("engineering-control",),
            1,
            ("tools/hepta-engineering-control",),
        ),
    )
    generation_id = f"product-generation-{head[:24]}"
    with tempfile.TemporaryDirectory(prefix="hepta-engineering-product-v2-") as directory:
        with EngineeringStore(Path(directory) / "engineering.sqlite3") as store:
            issue_verified_work_envelope(
                store,
                repository,
                envelope,
                source_receipt,
                trust,
                expected_repository=EXPECTED_REPOSITORY,
                expected_document_set_digest=document_digest,
                now_ns=now,
            )
            plan = plan_engineering_work(
                envelope,
                (package,),
                workers,
                (),
                trust,
                generation_id=generation_id,
                review_capacity=(ReviewCapacity("architecture_reviewer", 1),),
                ci_capacity_units=1,
                now_ns=now,
            )
            persisted = persist_orchestration_generation(
                store,
                envelope,
                plan,
                (package,),
                (),
                trust,
                now_ns=now,
            )
            frontier = store.assignment_frontier(generation_id)
            durable_plan = orchestration_generation(store, generation_id)

    if persisted.assigned != ("control.engineering.product-composition",):
        raise RuntimeError("product_assignment_not_persisted")
    if plan.integration_order != persisted.assigned or len(plan.merge_queue) != 1:
        raise RuntimeError("product_orchestration_mismatch")

    receipt: dict[str, object] = {
        "schema": "hepta.control-engineering-product-execution.v2",
        "productCaller": PRODUCT_CALLER_ID,
        "mode": mode,
        "sourceSha": source_sha,
        "sourceTree": source_tree,
        "testedSha": head,
        "testedTree": head_tree,
        "documentSetDigest": document_digest,
        "sourceReceiptVerified": True,
        "authenticatedCompletionBoundary": True,
        "multidimensionalOrchestration": True,
        "durableGenerationId": generation_id,
        "assignmentFrontierDigest": frontier["frontierDigest"],
        "orchestrationGenerationDigest": durable_plan["semanticDigest"],
        "assignments": [asdict(item) for item in plan.assignments],
        "integrationOrder": list(plan.integration_order),
        "mergeQueueProposal": [asdict(item) for item in plan.merge_queue],
        "eligibleForIndependentReview": False,
        "referenceSigningOnly": True,
        "externalKeyCustody": False,
        "runtimeAuthority": False,
        "workerWriteAuthority": False,
        "mergeAuthority": False,
        "activationAuthority": False,
        "promotionAuthority": False,
        "releaseAuthority": False,
    }

    if mode == "synthetic-merge":
        if base_sha is None:
            raise ValueError("missing_base_sha")
        base_sha = _sha1(base_sha, "base_sha")
        parents = tuple(_git(repository, "show", "-s", "--format=%P", "HEAD").split())
        if parents != (base_sha, source_sha):
            raise ValueError("ordered_merge_parent_mismatch")
        checks_digest = hashlib.sha256(b"control-engineering-product-v2").hexdigest()
        source_execution = ExecutionReceipt(
            "product-source-execution",
            "exact_source",
            source_sha,
            source_tree,
            tuple(_git(repository, "show", "-s", "--format=%P", source_sha).split()),
            checks_digest,
            True,
            "ci_executor",
            "ci-execution-reference",
            now,
            expires,
        )
        source_execution = _signed(
            trust,
            source_execution,
            source_execution.issuer,
            source_execution.signing_identity,
        )
        merge_execution = ExecutionReceipt(
            "product-merge-execution",
            "synthetic_merge",
            head,
            head_tree,
            parents,
            checks_digest,
            True,
            "ci_executor",
            "ci-execution-reference",
            now,
            expires,
        )
        merge_execution = _signed(
            trust,
            merge_execution,
            merge_execution.issuer,
            merge_execution.signing_identity,
        )
        independence = EvaluatorIndependenceReceipt(
            PRODUCT_CALLER_ID,
            "ci-execution-reference",
            "independent_evaluator",
            "ci-evaluator-reference",
            now,
            expires,
        )
        independence = _signed(
            trust,
            independence,
            independence.evaluator_principal,
            independence.evaluator_signing_identity,
        )
        evidence = verify_integration_evidence(
            repository,
            EXPECTED_REPOSITORY,
            source_receipt,
            source_execution,
            merge_execution,
            independence,
            trust,
            expected_document_set_digest=document_digest,
            now_ns=now,
        )
        if not evidence.eligible_for_independent_review or evidence.reasons:
            raise RuntimeError("integration_evidence_rejected:" + ",".join(evidence.reasons))
        receipt.update(
            {
                "baseSha": base_sha,
                "mergeParents": list(parents),
                "eligibleForIndependentReview": True,
                "integrationEvidenceDigest": evidence.evidence_digest,
            }
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--mode", choices=("source-head", "synthetic-merge"), required=True)
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
        print(json.dumps({"status": "rejected", "error": str(error), "authorityGranted": False}, sort_keys=True))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
