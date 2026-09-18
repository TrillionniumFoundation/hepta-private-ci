"""Authenticated engineering orchestration for the production-facing Lane G path.

The low-level EngineeringStore remains the durable owner of envelopes, leases and
assignment generations. This module adds the richer deterministic planning inputs
required by docs/DEVELOPMENT.md without granting worker, merge, activation,
promotion or release authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Iterable, Mapping
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    bounded_tuple,
    canonical_json,
    canonical_paths,
    checked_id,
    path_is_within,
    path_sets_overlap,
    semantic_digest,
)
from .evidence import (
    CanonicalSourceReceipt,
    HmacTrustStore,
    WorkCompletionReceipt,
    verify_canonical_source_receipt,
    verify_work_completion_receipts,
)

MAX_WORKERS = 256
MAX_REVIEW_ROLES = 32
MAX_CI_UNITS = 64
MAX_SKILLS = 64


@dataclass(frozen=True)
class WorkerCapacity:
    worker_id: str
    skills: tuple[str, ...]
    capacity_units: int
    allowed_paths: tuple[str, ...]


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
    worker_capacity_units: int = 1
    ci_capacity_units: int = 1
    review_roles: tuple[str, ...] = ()
    expected_value_micros: int = 0
    architecture_debt_reduction_micros: int = 0
    rollback_cost_micros: int = 0
    integration_group: str = "default"


@dataclass(frozen=True)
class EngineeringAssignment:
    package_id: str
    worker_id: str
    write_paths: tuple[str, ...]
    score_micros: int
    worker_capacity_units: int
    ci_capacity_units: int
    review_roles: tuple[str, ...]


@dataclass(frozen=True)
class MergeQueueProposal:
    package_id: str
    position: int
    integration_group: str
    required_review_roles: tuple[str, ...]
    ci_capacity_units: int
    merge_authority: bool = False


@dataclass(frozen=True)
class OrchestrationPlan:
    generation_id: str
    source_commit: str
    source_tree: str
    assignments: tuple[EngineeringAssignment, ...]
    blocked: tuple[tuple[str, str], ...]
    integration_order: tuple[str, ...]
    merge_queue: tuple[MergeQueueProposal, ...]
    runtime_authority: bool = False
    worker_write_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _skills(values: Iterable[str]) -> tuple[str, ...]:
    items = bounded_tuple(values, MAX_SKILLS, "skill_limit_exceeded")
    if any(not isinstance(item, str) or not item or len(item.encode("utf-8")) > 128 for item in items):
        raise EngineeringError("invalid_skill")
    return tuple(sorted(set(items)))


def _worker(value: WorkerCapacity) -> WorkerCapacity:
    if not isinstance(value, WorkerCapacity):
        raise EngineeringError("invalid_worker_capacity")
    checked_id(value.worker_id, "worker_id")
    if type(value.capacity_units) is not int or not 1 <= value.capacity_units <= 4096:
        raise EngineeringError("invalid_worker_capacity")
    paths = canonical_paths(value.allowed_paths)
    if not paths:
        raise EngineeringError("empty_worker_scope")
    return WorkerCapacity(value.worker_id, _skills(value.skills), value.capacity_units, paths)


def _package(value: EngineeringWorkPackage) -> EngineeringWorkPackage:
    if not isinstance(value, EngineeringWorkPackage):
        raise EngineeringError("invalid_package")
    checked_id(value.package_id, "package_id")
    checked_id(value.integration_group, "integration_group")
    if type(value.priority) is not int:
        raise EngineeringError("invalid_package_priority")
    predecessors = bounded_tuple(value.predecessors, 256, "predecessor_limit_exceeded")
    if any(not isinstance(item, str) for item in predecessors):
        raise EngineeringError("invalid_predecessor")
    predecessors = tuple(sorted({checked_id(item, "predecessor") for item in predecessors}))
    paths = canonical_paths(value.write_paths)
    skills = _skills(value.required_skills)
    roles = bounded_tuple(value.review_roles, MAX_REVIEW_ROLES, "review_role_limit_exceeded")
    if any(not isinstance(role, str) or not role for role in roles):
        raise EngineeringError("invalid_review_role")
    roles = tuple(sorted(set(roles)))
    for amount, label, maximum in (
        (value.worker_capacity_units, "worker_capacity_units", 4096),
        (value.ci_capacity_units, "ci_capacity_units", MAX_CI_UNITS),
    ):
        if type(amount) is not int or not 1 <= amount <= maximum:
            raise EngineeringError("invalid_" + label)
    for amount, label in (
        (value.expected_value_micros, "expected_value"),
        (value.architecture_debt_reduction_micros, "architecture_debt"),
        (value.rollback_cost_micros, "rollback_cost"),
    ):
        if type(amount) is not int or abs(amount) > 10**15:
            raise EngineeringError("invalid_" + label)
    return EngineeringWorkPackage(
        value.priority,
        value.package_id,
        predecessors,
        paths,
        skills,
        value.worker_capacity_units,
        value.ci_capacity_units,
        roles,
        value.expected_value_micros,
        value.architecture_debt_reduction_micros,
        value.rollback_cost_micros,
        value.integration_group,
    )


def issue_verified_work_envelope(
    store: EngineeringStore,
    repository: str | Path,
    envelope: WorkEnvelope,
    source_receipt: CanonicalSourceReceipt,
    trust_store: HmacTrustStore,
    *,
    expected_repository: str,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> WorkEnvelope:
    """Issue an envelope only after authenticating its exact canonical source."""
    now = time.time_ns() if now_ns is None else now_ns
    verified = verify_canonical_source_receipt(
        repository,
        expected_repository,
        source_receipt,
        trust_store,
        expected_document_set_digest=expected_document_set_digest,
        now_ns=now,
    )
    if envelope.source_commit != verified.source_commit or envelope.source_tree != verified.source_tree:
        raise EngineeringError("envelope_source_receipt_mismatch")
    return store.issue_work_envelope(envelope, now_ns=now)


def plan_engineering_work(
    envelope: WorkEnvelope,
    packages: Iterable[EngineeringWorkPackage],
    workers: Iterable[WorkerCapacity],
    completion_receipts: Iterable[WorkCompletionReceipt],
    trust_store: HmacTrustStore,
    *,
    generation_id: str,
    active_lease_paths: Iterable[str] = (),
    review_capacity: Iterable[ReviewCapacity] = (),
    ci_capacity_units: int,
    now_ns: int | None = None,
) -> OrchestrationPlan:
    """Plan bounded assignments, integration order and merge-queue proposals.

    Completion is never accepted as a caller-provided string set: every predecessor
    completion must be authenticated and bound to the same source generation.
    """
    checked_id(generation_id, "generation_id")
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    if type(ci_capacity_units) is not int or not 0 <= ci_capacity_units <= MAX_CI_UNITS:
        raise EngineeringError("invalid_ci_capacity")

    package_values = tuple(_package(item) for item in bounded_tuple(packages, 4096, "package_limit_exceeded"))
    if len({item.package_id for item in package_values}) != len(package_values):
        raise EngineeringError("duplicate_package_identity")
    worker_values = tuple(_worker(item) for item in bounded_tuple(workers, MAX_WORKERS, "worker_limit_exceeded"))
    if len({item.worker_id for item in worker_values}) != len(worker_values):
        raise EngineeringError("duplicate_worker_identity")
    if not worker_values and package_values:
        raise EngineeringError("worker_capacity_unavailable")

    receipt_values = bounded_tuple(completion_receipts, 4096, "completed_limit_exceeded")
    completed = verify_work_completion_receipts(
        list(receipt_values),
        trust_store,
        generation_id=None,
        source_commit=envelope.source_commit,
        source_tree=envelope.source_tree,
        now_ns=now,
    )
    raw_active_paths = tuple(active_lease_paths)
    active_paths = canonical_paths(raw_active_paths) if raw_active_paths else ()

    role_slots: dict[str, int] = {}
    for item in bounded_tuple(review_capacity, MAX_REVIEW_ROLES, "review_role_limit_exceeded"):
        if not isinstance(item, ReviewCapacity) or not item.role or type(item.slots) is not int or item.slots < 0:
            raise EngineeringError("invalid_review_capacity")
        if item.role in role_slots:
            raise EngineeringError("duplicate_review_role")
        role_slots[item.role] = item.slots

    remaining_worker = {item.worker_id: item.capacity_units for item in worker_values}
    remaining_ci = ci_capacity_units
    selected_paths: list[str] = []
    assignments: list[EngineeringAssignment] = []
    blocked: list[tuple[str, str]] = []

    package_ids = {item.package_id for item in package_values}
    for package in package_values:
        for predecessor in package.predecessors:
            if predecessor not in package_ids and predecessor not in completed:
                raise EngineeringError("unknown_predecessor")

    # Match the durable owner: a cycle is a malformed DAG, not merely a batch
    # in which every package happens to be blocked on another package.
    pending = {item.package_id: 0 for item in package_values}
    successors: dict[str, list[str]] = {identity: [] for identity in package_ids}
    for package in package_values:
        for predecessor in package.predecessors:
            if predecessor in package_ids:
                pending[package.package_id] += 1
                successors[predecessor].append(package.package_id)
    ready = [identity for identity, count in pending.items() if count == 0]
    visited = 0
    while ready:
        identity = ready.pop()
        visited += 1
        for successor in successors[identity]:
            pending[successor] -= 1
            if pending[successor] == 0:
                ready.append(successor)
    if visited != len(package_values):
        raise EngineeringError("dependency_cycle")

    def score(item: EngineeringWorkPackage) -> int:
        return (
            item.expected_value_micros
            + item.architecture_debt_reduction_micros
            - item.rollback_cost_micros
        )

    for package in sorted(package_values, key=lambda item: (item.priority, -score(item), item.package_id)):
        missing = tuple(sorted(set(package.predecessors) - completed))
        if missing:
            blocked.append((package.package_id, "missing_predecessor:" + missing[0]))
            continue
        if any(not path_is_within(path, envelope.allowed_paths) for path in package.write_paths):
            blocked.append((package.package_id, "path_outside_envelope"))
            continue
        if path_sets_overlap(package.write_paths, active_paths):
            blocked.append((package.package_id, "active_path_lease"))
            continue
        if path_sets_overlap(package.write_paths, tuple(selected_paths)):
            blocked.append((package.package_id, "batch_path_conflict"))
            continue
        if package.ci_capacity_units > remaining_ci:
            blocked.append((package.package_id, "ci_capacity"))
            continue
        unavailable_role = next((role for role in package.review_roles if role_slots.get(role, 0) < 1), None)
        if unavailable_role is not None:
            blocked.append((package.package_id, "review_capacity:" + unavailable_role))
            continue
        candidates = [
            worker
            for worker in worker_values
            if set(package.required_skills).issubset(worker.skills)
            and remaining_worker[worker.worker_id] >= package.worker_capacity_units
            and all(path_is_within(path, worker.allowed_paths) for path in package.write_paths)
        ]
        if not candidates:
            blocked.append((package.package_id, "worker_skill_or_capacity"))
            continue
        worker = sorted(
            candidates,
            key=lambda item: (
                remaining_worker[item.worker_id] - package.worker_capacity_units,
                item.worker_id,
            ),
        )[0]
        remaining_worker[worker.worker_id] -= package.worker_capacity_units
        remaining_ci -= package.ci_capacity_units
        for role in package.review_roles:
            role_slots[role] -= 1
        selected_paths.extend(package.write_paths)
        assignments.append(
            EngineeringAssignment(
                package.package_id,
                worker.worker_id,
                package.write_paths,
                score(package),
                package.worker_capacity_units,
                package.ci_capacity_units,
                package.review_roles,
            )
        )

    integration_order = tuple(item.package_id for item in assignments)
    package_by_id = {item.package_id: item for item in package_values}
    merge_queue = tuple(
        MergeQueueProposal(
            package_id,
            position,
            package_by_id[package_id].integration_group,
            package_by_id[package_id].review_roles,
            package_by_id[package_id].ci_capacity_units,
        )
        for position, package_id in enumerate(integration_order, start=1)
    )
    return OrchestrationPlan(
        generation_id,
        envelope.source_commit,
        envelope.source_tree,
        tuple(assignments),
        tuple(blocked),
        integration_order,
        merge_queue,
    )


def _plan_payload(plan: OrchestrationPlan) -> dict[str, object]:
    return {
        "generationId": plan.generation_id,
        "sourceCommit": plan.source_commit,
        "sourceTree": plan.source_tree,
        "assignments": [asdict(item) for item in plan.assignments],
        "blocked": plan.blocked,
        "integrationOrder": plan.integration_order,
        "mergeQueue": [asdict(item) for item in plan.merge_queue],
        "authority": {
            "runtime": plan.runtime_authority,
            "workerWrite": plan.worker_write_authority,
            "merge": plan.merge_authority,
            "activation": plan.activation_authority,
            "promotion": plan.promotion_authority,
            "release": plan.release_authority,
        },
    }


def orchestration_generation(
    store: EngineeringStore,
    generation_id: str,
) -> dict[str, object]:
    """Read the immutable rich work-assignment projection for one generation."""
    checked_id(generation_id, "generation_id")
    row = store.connection.execute(
        "SELECT semantic_digest,plan_json,created_unix_ns "
        "FROM orchestration_generations WHERE generation_id=?",
        (generation_id,),
    ).fetchone()
    if row is None:
        raise EngineeringError("unknown_orchestration_generation")
    import json

    try:
        payload = json.loads(bytes(row["plan_json"]).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        raise EngineeringError("orchestration_generation_corrupt") from None
    if semantic_digest(payload) != str(row["semantic_digest"]):
        raise EngineeringError("orchestration_generation_corrupt")
    return {
        "generationId": generation_id,
        "semanticDigest": str(row["semantic_digest"]),
        "plan": payload,
        "createdUnixNs": int(row["created_unix_ns"]),
    }


def persist_orchestration_generation(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    plan: OrchestrationPlan,
    packages: Iterable[EngineeringWorkPackage],
    completion_receipts: Iterable[WorkCompletionReceipt],
    trust_store: HmacTrustStore,
    *,
    now_ns: int | None = None,
):
    """Atomically persist the package projection and the complete orchestration plan."""
    now = store._now(now_ns)
    if not isinstance(plan, OrchestrationPlan):
        raise EngineeringError("invalid_orchestration_plan")
    if (
        plan.source_commit != envelope.source_commit
        or plan.source_tree != envelope.source_tree
    ):
        raise EngineeringError("orchestration_source_mismatch")
    if any(
        (
            plan.runtime_authority,
            plan.worker_write_authority,
            plan.merge_authority,
            plan.activation_authority,
            plan.promotion_authority,
            plan.release_authority,
        )
    ):
        raise EngineeringError("orchestration_authority_delta")

    completed = verify_work_completion_receipts(
        list(completion_receipts),
        trust_store,
        generation_id=None,
        source_commit=envelope.source_commit,
        source_tree=envelope.source_tree,
        now_ns=now,
    )
    by_id = {item.package_id: _package(item) for item in packages}
    if len(by_id) > 4096:
        raise EngineeringError("package_limit_exceeded")
    try:
        selected = tuple(
            WorkPackage(
                by_id[assignment.package_id].priority,
                assignment.package_id,
                by_id[assignment.package_id].predecessors,
                assignment.write_paths,
            )
            for assignment in plan.assignments
        )
    except KeyError:
        raise EngineeringError("orchestration_package_missing") from None

    payload = _plan_payload(plan)
    digest = semantic_digest(payload)
    with store._transaction():
        receipt = store.schedule_ready_packages(
            envelope.envelope_id,
            selected,
            completed,
            generation_id=plan.generation_id,
            now_ns=now,
        )
        if receipt.assigned != plan.integration_order:
            raise EngineeringError("orchestration_persistence_mismatch")
        existing = store.connection.execute(
            "SELECT semantic_digest FROM orchestration_generations WHERE generation_id=?",
            (plan.generation_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["semantic_digest"]) != digest:
                raise EngineeringError("orchestration_generation_conflict")
            return receipt
        store.connection.execute(
            "INSERT INTO orchestration_generations("
            "generation_id,semantic_digest,plan_json,created_unix_ns"
            ") VALUES(?,?,?,?)",
            (plan.generation_id, digest, canonical_json(payload), now),
        )
        store._append_audit(
            "orchestration_generation_published",
            {
                "generationId": plan.generation_id,
                "semanticDigest": digest,
                "assignmentCount": len(plan.assignments),
                "mergeQueueCount": len(plan.merge_queue),
            },
            now,
        )
    return receipt

