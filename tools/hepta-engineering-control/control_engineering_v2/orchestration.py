"""Authenticated product orchestration for Lane G.

This module composes the durable SQLite owner with the richer engineering
scheduling inputs required by docs/DEVELOPMENT.md. It deliberately emits
proposals only: no assignment, merge-queue position, leadership receipt or
completion receipt grants repository write, merge, deployment or release
authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import time
from typing import Iterable, Mapping, Protocol

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    bounded_tuple,
    canonical_paths,
    checked_id,
    checked_sha256,
    path_sets_overlap,
    semantic_digest,
    _validate_envelope,
)
from .evidence import CanonicalSourceReceipt

MAX_WORKERS = 256
MAX_REVIEW_ROLES = 64
MAX_ENGINEERING_PACKAGES = 4096
MAX_COMPLETION_RECEIPTS = 4096
MAX_SKILLS = 64
MAX_REVIEW_REQUIREMENTS = 16
MAX_CI_UNITS = 4096
MAX_CAPACITY_UNITS = 1_000_000


class ReceiptVerifier(Protocol):
    def verify(
        self,
        value: object,
        issuer: str,
        signing_identity: str,
        signature: str,
    ) -> bool: ...


@dataclass(frozen=True)
class CompletionReceipt:
    package_id: str
    source_commit: str
    source_tree: str
    generation_id: str
    evidence_digest: str
    status: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class LeadershipReceipt:
    cluster_id: str
    leader_id: str
    epoch: int
    source_commit: str
    source_tree: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerCapacity:
    worker_id: str
    skills: tuple[str, ...]
    capacity_units: int
    maximum_parallel_assignments: int = 1


@dataclass(frozen=True)
class ReviewCapacity:
    role: str
    slots: int


@dataclass(frozen=True)
class EngineeringWorkPackage:
    priority: int
    package_id: str
    predecessors: tuple[str, ...]
    write_paths: tuple[str, ...]
    required_skills: tuple[str, ...] = ()
    effort_units: int = 1
    ci_units: int = 1
    review_roles: tuple[str, ...] = ()
    expected_value_micros: int = 0
    architecture_debt_micros: int = 0
    rollback_cost_micros: int = 0


@dataclass(frozen=True)
class WorkAssignment:
    package_id: str
    worker_id: str
    effort_units: int
    ci_units: int
    review_roles: tuple[str, ...]
    rank: int


@dataclass(frozen=True)
class MergeQueueProposal:
    package_id: str
    rank: int
    worker_id: str
    review_roles: tuple[str, ...]
    score_digest: str
    merge_authority: bool = False


@dataclass(frozen=True)
class EngineeringPlan:
    generation_id: str
    envelope_id: str
    source_commit: str
    source_tree: str
    assignments: tuple[WorkAssignment, ...]
    blocked: tuple[tuple[str, str], ...]
    integration_order: tuple[str, ...]
    merge_queue: tuple[MergeQueueProposal, ...]
    assignment_frontier_digest: str
    completion_receipts_digest: str
    resource_model_digest: str
    leadership_digest: str | None
    leadership_epoch: int | None
    plan_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _valid_window(observed: int, expires: int, now: int) -> bool:
    return (
        type(observed) is int
        and type(expires) is int
        and observed <= now < expires
        and expires > observed
    )


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
        raise EngineeringError("git_read_failed") from None
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 1_048_576:
        raise EngineeringError("git_read_failed")
    return result.stdout.strip()


def verify_canonical_source_receipt(
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    verifier: ReceiptVerifier,
    *,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> None:
    """Authenticate the exact source before a work envelope is persisted."""
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    repository = Path(root).resolve()
    checked_sha256(source.document_set_digest, "document_set_digest")
    checked_sha256(expected_document_set_digest, "document_set_digest")
    if source.repository_full_name != expected_repository:
        raise EngineeringError("repository_mismatch")
    if source.document_set_digest != expected_document_set_digest:
        raise EngineeringError("document_set_drift")
    if source.issuer != "source_authority":
        raise EngineeringError("source_issuer_role")
    if not _valid_window(source.observed_unix_ns, source.expires_unix_ns, now):
        raise EngineeringError("source_receipt_stale")
    if not verifier.verify(
        source, source.issuer, source.signing_identity, source.signature
    ):
        raise EngineeringError("source_receipt_signature")
    commit = _git(repository, "rev-parse", "--verify", f"{source.source_commit}^{{commit}}")
    tree = _git(repository, "rev-parse", f"{source.source_commit}^{{tree}}")
    if commit != source.source_commit or tree != source.source_tree:
        raise EngineeringError("source_tree_mismatch")
    try:
        remote = _git(repository, "config", "--get", "remote.origin.url")
    except EngineeringError:
        remote = ""
    normalized = remote.strip().removesuffix(".git").removesuffix("/")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if normalized and normalized != expected_repository:
        raise EngineeringError("repository_remote_mismatch")


def issue_authenticated_work_envelope(
    store: EngineeringStore,
    root: str | Path,
    expected_repository: str,
    source: CanonicalSourceReceipt,
    envelope: WorkEnvelope,
    verifier: ReceiptVerifier,
    *,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> WorkEnvelope:
    verify_canonical_source_receipt(
        root,
        expected_repository,
        source,
        verifier,
        expected_document_set_digest=expected_document_set_digest,
        now_ns=now_ns,
    )
    if (
        envelope.source_commit != source.source_commit
        or envelope.source_tree != source.source_tree
    ):
        raise EngineeringError("envelope_source_receipt_mismatch")
    return store.issue_work_envelope(envelope, now_ns=now_ns)


def _validate_completion_receipts(
    receipts: Iterable[CompletionReceipt],
    envelope: WorkEnvelope,
    verifier: ReceiptVerifier,
    *,
    now_ns: int,
) -> tuple[CompletionReceipt, ...]:
    values = bounded_tuple(
        receipts, MAX_COMPLETION_RECEIPTS, "completion_receipt_limit_exceeded"
    )
    seen: set[str] = set()
    result: list[CompletionReceipt] = []
    for value in values:
        if not isinstance(value, CompletionReceipt):
            raise EngineeringError("invalid_completion_receipt")
        checked_id(value.package_id, "package_id")
        checked_id(value.generation_id, "generation_id")
        checked_sha256(value.evidence_digest, "evidence_digest")
        if value.package_id in seen:
            raise EngineeringError("duplicate_completion_receipt")
        seen.add(value.package_id)
        if (
            value.status != "completed"
            or value.source_commit != envelope.source_commit
            or value.source_tree != envelope.source_tree
        ):
            raise EngineeringError("completion_receipt_source_mismatch")
        if value.issuer not in {"ci_executor", "independent_evaluator"}:
            raise EngineeringError("completion_receipt_issuer_role")
        if not _valid_window(value.observed_unix_ns, value.expires_unix_ns, now_ns):
            raise EngineeringError("completion_receipt_stale")
        if not verifier.verify(
            value, value.issuer, value.signing_identity, value.signature
        ):
            raise EngineeringError("completion_receipt_signature")
        result.append(value)
    return tuple(result)


def _validate_leadership(
    value: LeadershipReceipt | None,
    envelope: WorkEnvelope,
    verifier: ReceiptVerifier,
    *,
    distributed: bool,
    now_ns: int,
) -> tuple[str | None, int | None]:
    if not distributed:
        if value is not None:
            raise EngineeringError("unexpected_leadership_receipt")
        return None, None
    if not isinstance(value, LeadershipReceipt):
        raise EngineeringError("leadership_receipt_required")
    checked_id(value.cluster_id, "cluster_id")
    checked_id(value.leader_id, "leader_id")
    if type(value.epoch) is not int or value.epoch < 1:
        raise EngineeringError("invalid_leadership_epoch")
    if (
        value.source_commit != envelope.source_commit
        or value.source_tree != envelope.source_tree
    ):
        raise EngineeringError("leadership_source_mismatch")
    if value.issuer != "external_coordination_authority":
        raise EngineeringError("leadership_issuer_role")
    if not _valid_window(value.observed_unix_ns, value.expires_unix_ns, now_ns):
        raise EngineeringError("leadership_receipt_stale")
    if not verifier.verify(value, value.issuer, value.signing_identity, value.signature):
        raise EngineeringError("leadership_receipt_signature")
    return semantic_digest(asdict(value)), value.epoch


def _checked_skills(values: Iterable[str]) -> tuple[str, ...]:
    values = bounded_tuple(values, MAX_SKILLS, "skill_limit_exceeded")
    if any(not isinstance(value, str) or not value for value in values):
        raise EngineeringError("invalid_skill")
    return tuple(sorted(set(values)))


def _checked_roles(values: Iterable[str]) -> tuple[str, ...]:
    values = bounded_tuple(values, MAX_REVIEW_REQUIREMENTS, "review_role_limit_exceeded")
    if any(not isinstance(value, str) or not value for value in values):
        raise EngineeringError("invalid_review_role")
    return tuple(sorted(set(values)))


def _package_rank(value: EngineeringWorkPackage) -> tuple[int, int, int, int, int, str]:
    # Lower tuple wins. High expected value and debt paydown are preferred; high
    # rollback cost and effort are penalized. All arithmetic is integral.
    return (
        value.priority,
        -value.expected_value_micros,
        -value.architecture_debt_micros,
        value.rollback_cost_micros,
        value.effort_units,
        value.package_id,
    )


def schedule_engineering_work(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    packages: Iterable[EngineeringWorkPackage],
    workers: Iterable[WorkerCapacity],
    review_capacity: Iterable[ReviewCapacity],
    *,
    ci_capacity_units: int,
    completion_receipts: Iterable[CompletionReceipt],
    verifier: ReceiptVerifier,
    generation_id: str,
    leadership: LeadershipReceipt | None = None,
    distributed: bool = False,
    now_ns: int | None = None,
) -> EngineeringPlan:
    """Create a bounded assignment/integration proposal from authenticated facts."""
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    envelope = _validate_envelope(envelope)
    if type(ci_capacity_units) is not int or not 0 <= ci_capacity_units <= MAX_CI_UNITS:
        raise EngineeringError("invalid_ci_capacity")
    checked_id(generation_id, "generation_id")
    package_values = bounded_tuple(
        packages, MAX_ENGINEERING_PACKAGES, "package_limit_exceeded"
    )
    worker_values = bounded_tuple(workers, MAX_WORKERS, "worker_limit_exceeded")
    review_values = bounded_tuple(
        review_capacity, MAX_REVIEW_ROLES, "review_capacity_limit_exceeded"
    )
    if any(not isinstance(value, EngineeringWorkPackage) for value in package_values):
        raise EngineeringError("invalid_engineering_package")
    if any(not isinstance(value, WorkerCapacity) for value in worker_values):
        raise EngineeringError("invalid_worker_capacity")
    if any(not isinstance(value, ReviewCapacity) for value in review_values):
        raise EngineeringError("invalid_review_capacity")

    normalized_packages: list[EngineeringWorkPackage] = []
    package_ids: set[str] = set()
    for value in package_values:
        checked_id(value.package_id, "package_id")
        if value.package_id in package_ids:
            raise EngineeringError("duplicate_package_identity")
        package_ids.add(value.package_id)
        if (
            type(value.priority) is not int
            or type(value.effort_units) is not int
            or not 1 <= value.effort_units <= MAX_CAPACITY_UNITS
            or type(value.ci_units) is not int
            or not 0 <= value.ci_units <= MAX_CI_UNITS
            or any(
                type(number) is not int
                for number in (
                    value.expected_value_micros,
                    value.architecture_debt_micros,
                    value.rollback_cost_micros,
                )
            )
            or min(
                value.expected_value_micros,
                value.architecture_debt_micros,
                value.rollback_cost_micros,
            )
            < 0
        ):
            raise EngineeringError("invalid_engineering_package")
        normalized_packages.append(
            EngineeringWorkPackage(
                value.priority,
                value.package_id,
                tuple(sorted(set(value.predecessors))),
                canonical_paths(value.write_paths),
                _checked_skills(value.required_skills),
                value.effort_units,
                value.ci_units,
                _checked_roles(value.review_roles),
                value.expected_value_micros,
                value.architecture_debt_micros,
                value.rollback_cost_micros,
            )
        )

    worker_state: dict[str, dict[str, object]] = {}
    for worker in worker_values:
        checked_id(worker.worker_id, "worker_id")
        if worker.worker_id in worker_state:
            raise EngineeringError("duplicate_worker_identity")
        if (
            type(worker.capacity_units) is not int
            or not 1 <= worker.capacity_units <= MAX_CAPACITY_UNITS
            or type(worker.maximum_parallel_assignments) is not int
            or not 1 <= worker.maximum_parallel_assignments <= 128
        ):
            raise EngineeringError("invalid_worker_capacity")
        worker_state[worker.worker_id] = {
            "skills": frozenset(_checked_skills(worker.skills)),
            "capacity": worker.capacity_units,
            "used": 0,
            "assignments": 0,
            "parallel": worker.maximum_parallel_assignments,
        }

    review_remaining: dict[str, int] = {}
    for capacity in review_values:
        if (
            not isinstance(capacity.role, str)
            or not capacity.role
            or capacity.role in review_remaining
            or type(capacity.slots) is not int
            or not 0 <= capacity.slots <= 128
        ):
            raise EngineeringError("invalid_review_capacity")
        review_remaining[capacity.role] = capacity.slots

    completed = _validate_completion_receipts(
        completion_receipts, envelope, verifier, now_ns=now
    )
    completed_ids = frozenset(value.package_id for value in completed)
    leadership_digest, leadership_epoch = _validate_leadership(
        leadership,
        envelope,
        verifier,
        distributed=distributed,
        now_ns=now,
    )

    blocked: list[tuple[str, str]] = []
    resource_ready: list[tuple[EngineeringWorkPackage, str]] = []
    ci_remaining = ci_capacity_units
    with store._transaction():
        stored_envelope = store._get_envelope(envelope.envelope_id, now)
        if str(stored_envelope["semantic_digest"]) != semantic_digest(asdict(envelope)):
            raise EngineeringError("envelope_state_mismatch")
        store._expire_leases(now)
        active_rows = store._active_lease_rows(now)
        active_paths = tuple(
            path
            for row in active_rows
            for path in json.loads(bytes(row["paths_json"]).decode("utf-8"))
        )
        selected_paths: list[str] = []
        assignment_limit = int(stored_envelope["maximum_assignments"])

        for package in sorted(normalized_packages, key=_package_rank):
            missing = sorted(set(package.predecessors) - completed_ids)
            if missing:
                blocked.append(
                    (
                        package.package_id,
                        "missing_authenticated_predecessor:" + missing[0],
                    )
                )
                continue
            if path_sets_overlap(package.write_paths, active_paths):
                blocked.append((package.package_id, "active_path_lease"))
                continue
            if path_sets_overlap(package.write_paths, tuple(selected_paths)):
                blocked.append((package.package_id, "batch_path_conflict"))
                continue
            if len(resource_ready) >= assignment_limit:
                blocked.append((package.package_id, "assignment_limit"))
                continue
            if package.ci_units > ci_remaining:
                blocked.append((package.package_id, "ci_capacity"))
                continue
            missing_review = next(
                (
                    role
                    for role in package.review_roles
                    if review_remaining.get(role, 0) <= 0
                ),
                None,
            )
            if missing_review is not None:
                blocked.append(
                    (package.package_id, "review_capacity:" + missing_review)
                )
                continue
            required = set(package.required_skills)
            eligible_workers: list[tuple[int, str]] = []
            for worker_id, state in worker_state.items():
                if not required.issubset(state["skills"]):
                    continue
                if int(state["used"]) + package.effort_units > int(state["capacity"]):
                    continue
                if int(state["assignments"]) >= int(state["parallel"]):
                    continue
                eligible_workers.append((int(state["used"]), worker_id))
            if not eligible_workers:
                blocked.append((package.package_id, "worker_capacity_or_skill"))
                continue
            _, worker_id = min(eligible_workers)
            state = worker_state[worker_id]
            state["used"] = int(state["used"]) + package.effort_units
            state["assignments"] = int(state["assignments"]) + 1
            ci_remaining -= package.ci_units
            for role in package.review_roles:
                review_remaining[role] -= 1
            resource_ready.append((package, worker_id))
            selected_paths.extend(package.write_paths)

        owner_packages = tuple(
            WorkPackage(
                rank,
                package.package_id,
                package.predecessors,
                package.write_paths,
            )
            for rank, (package, _worker_id) in enumerate(resource_ready)
        )
        owner_receipt = store.schedule_ready_packages(
            envelope.envelope_id,
            owner_packages,
            completed_ids,
            generation_id=generation_id,
            now_ns=now,
        )
        owner_assigned = set(owner_receipt.assigned)
        blocked.extend(owner_receipt.blocked)
        selected = [
            (rank, package, worker_id)
            for rank, (package, worker_id) in enumerate(resource_ready)
            if package.package_id in owner_assigned
        ]
        frontier = store.assignment_frontier(generation_id)
    assignments = tuple(
        WorkAssignment(
            package.package_id,
            worker_id,
            package.effort_units,
            package.ci_units,
            package.review_roles,
            rank,
        )
        for rank, package, worker_id in selected
    )
    integration_order = tuple(value.package_id for value in assignments)
    merge_queue = tuple(
        MergeQueueProposal(
            assignment.package_id,
            assignment.rank,
            assignment.worker_id,
            assignment.review_roles,
            semantic_digest(
                {
                    "packageId": assignment.package_id,
                    "rank": assignment.rank,
                    "workerId": assignment.worker_id,
                    "reviewRoles": assignment.review_roles,
                }
            ),
        )
        for assignment in assignments
    )
    completion_digest = semantic_digest([asdict(value) for value in completed])
    resource_digest = semantic_digest(
        {
            "workers": [asdict(value) for value in worker_values],
            "reviewCapacity": [asdict(value) for value in review_values],
            "ciCapacityUnits": ci_capacity_units,
            "packages": [asdict(value) for value in normalized_packages],
        }
    )
    plan_body = {
        "generationId": generation_id,
        "envelopeId": envelope.envelope_id,
        "sourceCommit": envelope.source_commit,
        "sourceTree": envelope.source_tree,
        "assignments": [asdict(value) for value in assignments],
        "blocked": sorted(set(blocked)),
        "integrationOrder": integration_order,
        "mergeQueue": [asdict(value) for value in merge_queue],
        "assignmentFrontierDigest": frontier["frontierDigest"],
        "completionReceiptsDigest": completion_digest,
        "resourceModelDigest": resource_digest,
        "leadershipDigest": leadership_digest,
        "leadershipEpoch": leadership_epoch,
    }
    return EngineeringPlan(
        generation_id,
        envelope.envelope_id,
        envelope.source_commit,
        envelope.source_tree,
        assignments,
        tuple(sorted(set(blocked))),
        integration_order,
        merge_queue,
        str(frontier["frontierDigest"]),
        completion_digest,
        resource_digest,
        leadership_digest,
        leadership_epoch,
        semantic_digest(plan_body),
    )
