"""Deterministic high-level engineering orchestration for Lane G.

This layer plans bounded assignments and integration ordering from the richer
inputs required by docs/DEVELOPMENT.md.  It grants no write, review, merge,
activation, promotion, release, deployment, or runtime authority.  Durable
repository-path serialization remains owned by EngineeringStore/path leases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .control_plane import (
    EngineeringError,
    MAX_ASSIGNMENTS,
    bounded_tuple,
    checked_id,
    path_sets_overlap,
)
from .path_policy import canonical_paths


MAX_WORK_ITEMS = 4096
MAX_WORKERS = 512
MAX_SKILLS = 64
MAX_REVIEW_ROLES = 32
MAX_CI_POOLS = 32
MAX_UNITS = 1_000_000
MAX_SCORE_COMPONENT = 1_000_000_000


@dataclass(frozen=True, order=True)
class WorkerProfile:
    worker_id: str
    skills: tuple[str, ...]
    capacity_units: int
    maximum_assignments: int = 1


@dataclass(frozen=True, order=True)
class ReviewCapacity:
    role: str
    slots: int


@dataclass(frozen=True, order=True)
class CiCapacity:
    pool_id: str
    slots: int


@dataclass(frozen=True)
class EngineeringWorkItem:
    package_id: str
    priority: int
    predecessors: tuple[str, ...]
    write_paths: tuple[str, ...]
    required_skills: tuple[str, ...] = ()
    effort_units: int = 1
    ci_units: int = 1
    review_roles: tuple[str, ...] = ()
    expected_value: int = 0
    architecture_debt_reduction: int = 0
    rollback_cost: int = 0


@dataclass(frozen=True)
class AssignmentProposal:
    package_id: str
    worker_id: str
    score: int
    write_paths: tuple[str, ...]


@dataclass(frozen=True)
class IntegrationProposal:
    package_id: str
    integration_rank: int
    ci_pool_id: str
    review_roles: tuple[str, ...]
    score: int


@dataclass(frozen=True)
class EngineeringOrchestrationPlan:
    assignments: tuple[AssignmentProposal, ...]
    blocked: tuple[tuple[str, str], ...]
    integration_order: tuple[IntegrationProposal, ...]
    merge_queue: tuple[str, ...]
    runtime_authority: bool = False
    merge_authority: bool = False
    activation_authority: bool = False
    promotion_authority: bool = False
    release_authority: bool = False


def _bounded_names(values: Iterable[str], limit: int, label: str) -> tuple[str, ...]:
    raw = bounded_tuple(values, limit, f"{label}_limit_exceeded")
    normalized = []
    for value in raw:
        checked_id(value, label)
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise EngineeringError(f"duplicate_{label}")
    return tuple(sorted(normalized))


def _checked_units(value: int, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_UNITS:
        raise EngineeringError(f"invalid_{label}")
    return value


def _checked_score_component(value: int, label: str) -> int:
    if type(value) is not int or abs(value) > MAX_SCORE_COMPONENT:
        raise EngineeringError(f"invalid_{label}")
    return value


def _validate_worker(value: WorkerProfile) -> WorkerProfile:
    if not isinstance(value, WorkerProfile):
        raise EngineeringError("invalid_worker")
    checked_id(value.worker_id, "worker_id")
    skills = _bounded_names(value.skills, MAX_SKILLS, "skill")
    capacity = _checked_units(value.capacity_units, "worker_capacity", minimum=1)
    if (
        type(value.maximum_assignments) is not int
        or not 1 <= value.maximum_assignments <= MAX_ASSIGNMENTS
    ):
        raise EngineeringError("invalid_worker_assignment_limit")
    return WorkerProfile(value.worker_id, skills, capacity, value.maximum_assignments)


def _validate_item(value: EngineeringWorkItem) -> EngineeringWorkItem:
    if not isinstance(value, EngineeringWorkItem):
        raise EngineeringError("invalid_work_item")
    checked_id(value.package_id, "package_id")
    if type(value.priority) is not int:
        raise EngineeringError("invalid_package_priority")
    predecessors = _bounded_names(value.predecessors, 256, "predecessor")
    paths = canonical_paths(value.write_paths)
    skills = _bounded_names(value.required_skills, MAX_SKILLS, "skill")
    roles = _bounded_names(value.review_roles, MAX_REVIEW_ROLES, "review_role")
    return EngineeringWorkItem(
        value.package_id,
        value.priority,
        predecessors,
        paths,
        skills,
        _checked_units(value.effort_units, "effort_units", minimum=1),
        _checked_units(value.ci_units, "ci_units", minimum=1),
        roles,
        _checked_score_component(value.expected_value, "expected_value"),
        _checked_score_component(
            value.architecture_debt_reduction, "architecture_debt_reduction"
        ),
        _checked_score_component(value.rollback_cost, "rollback_cost"),
    )


def _validate_graph(
    items: tuple[EngineeringWorkItem, ...], completed: frozenset[str]
) -> None:
    ids = {item.package_id for item in items}
    pending = {item.package_id: 0 for item in items}
    successors: dict[str, list[str]] = {identity: [] for identity in ids}
    for item in items:
        for predecessor in item.predecessors:
            if predecessor not in ids and predecessor not in completed:
                raise EngineeringError("unknown_predecessor")
            if predecessor in ids:
                pending[item.package_id] += 1
                successors[predecessor].append(item.package_id)
    ready = [identity for identity, count in pending.items() if count == 0]
    visited = 0
    while ready:
        identity = ready.pop()
        visited += 1
        for successor in successors[identity]:
            pending[successor] -= 1
            if pending[successor] == 0:
                ready.append(successor)
    if visited != len(items):
        raise EngineeringError("dependency_cycle")


def _item_score(item: EngineeringWorkItem) -> int:
    # Integer-only deterministic utility. Priority remains a separate stable sort
    # key; positive expected value/debt reduction improve integration precedence,
    # while rollback cost penalizes it.
    return (
        item.expected_value
        + item.architecture_debt_reduction
        - item.rollback_cost
    )


def plan_engineering_work(
    items: Iterable[EngineeringWorkItem],
    completed: Iterable[str],
    workers: Iterable[WorkerProfile],
    review_capacity: Iterable[ReviewCapacity],
    ci_capacity: Iterable[CiCapacity],
    active_paths: Iterable[str] = (),
    *,
    maximum_assignments: int = MAX_ASSIGNMENTS,
) -> EngineeringOrchestrationPlan:
    """Produce bounded worker assignments, integration order, and merge queue.

    The result is a proposal only.  Assigned workers still require durable path
    leases before mutation, and merge/release remain separately governed.
    """

    if (
        type(maximum_assignments) is not int
        or not 1 <= maximum_assignments <= MAX_ASSIGNMENTS
    ):
        raise EngineeringError("invalid_assignment_limit")

    item_values = tuple(
        _validate_item(value)
        for value in bounded_tuple(items, MAX_WORK_ITEMS, "package_limit_exceeded")
    )
    ids = [value.package_id for value in item_values]
    if len(ids) != len(set(ids)):
        raise EngineeringError("duplicate_package_identity")

    completed_set = frozenset(
        checked_id(value, "completed_id")
        for value in bounded_tuple(completed, MAX_WORK_ITEMS, "completed_limit_exceeded")
    )
    _validate_graph(item_values, completed_set)

    worker_values = tuple(
        _validate_worker(value)
        for value in bounded_tuple(workers, MAX_WORKERS, "worker_limit_exceeded")
    )
    if len({value.worker_id for value in worker_values}) != len(worker_values):
        raise EngineeringError("duplicate_worker_id")

    review_rows = tuple(
        bounded_tuple(review_capacity, MAX_REVIEW_ROLES, "review_capacity_limit_exceeded")
    )
    review_remaining: dict[str, int] = {}
    for row in review_rows:
        if not isinstance(row, ReviewCapacity):
            raise EngineeringError("invalid_review_capacity")
        checked_id(row.role, "review_role")
        if row.role in review_remaining:
            raise EngineeringError("duplicate_review_role")
        review_remaining[row.role] = _checked_units(row.slots, "review_slots")

    ci_rows = tuple(
        bounded_tuple(ci_capacity, MAX_CI_POOLS, "ci_capacity_limit_exceeded")
    )
    ci_remaining: dict[str, int] = {}
    for row in ci_rows:
        if not isinstance(row, CiCapacity):
            raise EngineeringError("invalid_ci_capacity")
        checked_id(row.pool_id, "ci_pool_id")
        if row.pool_id in ci_remaining:
            raise EngineeringError("duplicate_ci_pool")
        ci_remaining[row.pool_id] = _checked_units(row.slots, "ci_slots")

    normalized_active_paths = canonical_paths(active_paths)
    worker_units = {worker.worker_id: worker.capacity_units for worker in worker_values}
    worker_assignments = {worker.worker_id: 0 for worker in worker_values}
    selected_paths: list[str] = []
    assignments: list[AssignmentProposal] = []
    integration: list[IntegrationProposal] = []
    blocked: list[tuple[str, str]] = []

    ordered = sorted(
        item_values,
        key=lambda item: (item.priority, -_item_score(item), item.package_id),
    )
    for item in ordered:
        missing = tuple(sorted(set(item.predecessors) - completed_set))
        if missing:
            blocked.append((item.package_id, "missing_predecessor:" + missing[0]))
            continue
        if path_sets_overlap(item.write_paths, normalized_active_paths):
            blocked.append((item.package_id, "active_path_lease"))
            continue
        if path_sets_overlap(item.write_paths, tuple(selected_paths)):
            blocked.append((item.package_id, "batch_path_conflict"))
            continue
        if len(assignments) >= maximum_assignments:
            blocked.append((item.package_id, "assignment_limit"))
            continue

        candidates = []
        required = set(item.required_skills)
        for worker in worker_values:
            if not required.issubset(set(worker.skills)):
                continue
            if worker_units[worker.worker_id] < item.effort_units:
                continue
            if worker_assignments[worker.worker_id] >= worker.maximum_assignments:
                continue
            candidates.append(worker)
        if not candidates:
            blocked.append((item.package_id, "worker_capacity_or_skill"))
            continue
        worker = min(
            candidates,
            key=lambda candidate: (
                worker_assignments[candidate.worker_id],
                -worker_units[candidate.worker_id],
                candidate.worker_id,
            ),
        )

        unavailable_role = next(
            (role for role in item.review_roles if review_remaining.get(role, 0) <= 0),
            None,
        )
        if unavailable_role is not None:
            blocked.append((item.package_id, "review_capacity:" + unavailable_role))
            continue

        ci_pool = next(
            (
                pool_id
                for pool_id in sorted(ci_remaining)
                if ci_remaining[pool_id] >= item.ci_units
            ),
            None,
        )
        if ci_pool is None:
            blocked.append((item.package_id, "ci_capacity"))
            continue

        worker_units[worker.worker_id] -= item.effort_units
        worker_assignments[worker.worker_id] += 1
        for role in item.review_roles:
            review_remaining[role] -= 1
        ci_remaining[ci_pool] -= item.ci_units
        selected_paths.extend(item.write_paths)

        score = _item_score(item)
        assignments.append(
            AssignmentProposal(item.package_id, worker.worker_id, score, item.write_paths)
        )
        integration.append(
            IntegrationProposal(
                item.package_id,
                0,
                ci_pool,
                item.review_roles,
                score,
            )
        )

    integration.sort(
        key=lambda row: (
            next(item.priority for item in item_values if item.package_id == row.package_id),
            -row.score,
            row.package_id,
        )
    )
    ranked = tuple(
        IntegrationProposal(
            row.package_id,
            index + 1,
            row.ci_pool_id,
            row.review_roles,
            row.score,
        )
        for index, row in enumerate(integration)
    )
    return EngineeringOrchestrationPlan(
        tuple(assignments),
        tuple(blocked),
        ranked,
        tuple(row.package_id for row in ranked),
    )
