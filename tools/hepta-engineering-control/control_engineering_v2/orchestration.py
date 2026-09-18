"""Authenticated engineering orchestration above the durable Lane G owner.

This layer closes the gap between the low-level path/DAG scheduler and the
Engineering Control Plane contract.  It consumes authenticated completion/source
facts plus explicit worker, CI and review capacity.  Outputs are proposals only:
workers must still acquire fenced path leases and merge/release remain external.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    WorkPackage,
    bounded_tuple,
    checked_id,
    checked_sha256,
    path_sets_overlap,
    semantic_digest,
)
from .evidence import CanonicalSourceReceipt, HmacTrustStore

MAX_WORKERS = 256
MAX_SKILLS = 64
MAX_REVIEW_ROLES = 16
MAX_CAPACITY_UNITS = 1_000_000
MAX_SCORE_ABS = 1 << 62


@dataclass(frozen=True)
class CompletionReceipt:
    package_id: str
    source_commit: str
    source_tree: str
    generation_id: str
    result_digest: str
    issuer: str
    signing_identity: str
    observed_unix_ns: int
    expires_unix_ns: int
    signature: str = ""


@dataclass(frozen=True)
class WorkerProfile:
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
    capacity_units: int = 1
    ci_units: int = 1
    review_roles: tuple[str, ...] = ()
    expected_value_q32: int = 0
    architecture_debt_q32: int = 0
    rollback_cost_q32: int = 0


@dataclass(frozen=True)
class EngineeringCapacity:
    ci_units: int
    review: tuple[ReviewCapacity, ...]


@dataclass(frozen=True)
class EngineeringAssignment:
    package_id: str
    worker_id: str
    score_q32: int
    ci_units: int
    review_roles: tuple[str, ...]


@dataclass(frozen=True)
class MergeQueueProposal:
    position: int
    package_id: str
    state: str
    score_q32: int
    merge_authority: bool = False
    release_authority: bool = False


@dataclass(frozen=True)
class EngineeringPlan:
    generation_id: str
    envelope_id: str
    assignments: tuple[EngineeringAssignment, ...]
    blocked: tuple[tuple[str, str], ...]
    integration_order: tuple[str, ...]
    merge_queue: tuple[MergeQueueProposal, ...]
    base_schedule_digest: str
    completion_frontier_digest: str
    runtime_authority: bool = False
    merge_authority: bool = False
    release_authority: bool = False


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


def _normal_remote(value: str) -> str:
    value = value.strip().removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        return value.removeprefix("git@github.com:")
    for prefix in ("https://github.com/", "http://github.com/"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return value


def issue_repository_work_envelope(
    root: str | Path,
    store: EngineeringStore,
    envelope: WorkEnvelope,
    *,
    expected_repository: str,
    now_ns: int | None = None,
) -> WorkEnvelope:
    """Issue only after directly observing the exact canonical Git object."""
    repository = Path(root).resolve()
    head = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    remote = _normal_remote(_git(repository, "config", "--get", "remote.origin.url"))
    if remote != expected_repository:
        raise EngineeringError("repository_mismatch")
    if head != envelope.source_commit or tree != envelope.source_tree:
        raise EngineeringError("source_identity_mismatch")
    return store.issue_work_envelope(envelope, now_ns=now_ns)


def issue_signed_work_envelope(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    source: CanonicalSourceReceipt,
    trust_store: HmacTrustStore,
    *,
    expected_repository: str,
    expected_document_set_digest: str,
    now_ns: int | None = None,
) -> WorkEnvelope:
    """Remote-service admission path using a signed canonical-source receipt."""
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    checked_sha256(expected_document_set_digest, "document_set_digest")
    if source.repository_full_name != expected_repository:
        raise EngineeringError("repository_mismatch")
    if (
        source.source_commit != envelope.source_commit
        or source.source_tree != envelope.source_tree
        or source.document_set_digest != expected_document_set_digest
    ):
        raise EngineeringError("source_identity_mismatch")
    if source.issuer != "source_authority":
        raise EngineeringError("source_issuer_role")
    if not (
        type(source.observed_unix_ns) is int
        and type(source.expires_unix_ns) is int
        and source.observed_unix_ns <= now < source.expires_unix_ns
    ):
        raise EngineeringError("source_receipt_stale")
    if not trust_store.verify(
        source, source.issuer, source.signing_identity, source.signature
    ):
        raise EngineeringError("source_receipt_signature")
    return store.issue_work_envelope(envelope, now_ns=now)


def _verify_completion(
    receipt: CompletionReceipt,
    envelope: WorkEnvelope,
    trust_store: HmacTrustStore,
    now: int,
) -> None:
    checked_id(receipt.package_id, "package_id")
    checked_id(receipt.generation_id, "generation_id")
    checked_sha256(receipt.result_digest, "result_digest")
    if receipt.source_commit != envelope.source_commit or receipt.source_tree != envelope.source_tree:
        raise EngineeringError("completion_source_mismatch")
    if receipt.issuer not in {"ci_executor", "package_owner"}:
        raise EngineeringError("completion_issuer_role")
    if not (
        type(receipt.observed_unix_ns) is int
        and type(receipt.expires_unix_ns) is int
        and receipt.observed_unix_ns <= now < receipt.expires_unix_ns
    ):
        raise EngineeringError("completion_receipt_stale")
    if not trust_store.verify(
        receipt, receipt.issuer, receipt.signing_identity, receipt.signature
    ):
        raise EngineeringError("completion_receipt_signature")


def _score(package: EngineeringWorkPackage) -> int:
    values = (
        package.expected_value_q32,
        package.architecture_debt_q32,
        package.rollback_cost_q32,
    )
    if any(type(value) is not int or abs(value) > MAX_SCORE_ABS for value in values):
        raise EngineeringError("invalid_package_score")
    return (
        package.expected_value_q32
        - package.architecture_debt_q32
        - package.rollback_cost_q32
    )


def plan_engineering_work(
    store: EngineeringStore,
    envelope: WorkEnvelope,
    packages: Iterable[EngineeringWorkPackage],
    workers: Iterable[WorkerProfile],
    completion_receipts: Iterable[CompletionReceipt],
    trust_store: HmacTrustStore,
    capacity: EngineeringCapacity,
    *,
    generation_id: str,
    now_ns: int | None = None,
) -> EngineeringPlan:
    """Produce a deterministic resource-aware plan from authenticated facts."""
    now = time.time_ns() if now_ns is None else now_ns
    if type(now) is not int or now < 0:
        raise EngineeringError("invalid_time")
    checked_id(generation_id, "generation_id")
    package_values = bounded_tuple(packages, 4096, "package_limit_exceeded")
    worker_values = bounded_tuple(workers, MAX_WORKERS, "worker_limit_exceeded")
    receipt_values = bounded_tuple(
        completion_receipts, 4096, "completed_limit_exceeded"
    )
    if not isinstance(capacity, EngineeringCapacity):
        raise EngineeringError("invalid_engineering_capacity")
    if type(capacity.ci_units) is not int or not 0 <= capacity.ci_units <= MAX_CAPACITY_UNITS:
        raise EngineeringError("invalid_ci_capacity")

    package_ids = [value.package_id for value in package_values]
    if len(package_ids) != len(set(package_ids)):
        raise EngineeringError("duplicate_package_identity")
    worker_ids = [value.worker_id for value in worker_values]
    if len(worker_ids) != len(set(worker_ids)):
        raise EngineeringError("duplicate_worker_identity")

    for worker in worker_values:
        checked_id(worker.worker_id, "worker_id")
        if type(worker.capacity_units) is not int or not 0 <= worker.capacity_units <= MAX_CAPACITY_UNITS:
            raise EngineeringError("invalid_worker_capacity")
        if len(worker.skills) > MAX_SKILLS or len(set(worker.skills)) != len(worker.skills):
            raise EngineeringError("invalid_worker_skills")

    review_remaining: dict[str, int] = {}
    if len(capacity.review) > MAX_REVIEW_ROLES:
        raise EngineeringError("review_role_limit_exceeded")
    for row in capacity.review:
        checked_id(row.role, "review_role")
        if row.role in review_remaining or type(row.slots) is not int or row.slots < 0:
            raise EngineeringError("invalid_review_capacity")
        review_remaining[row.role] = row.slots

    completed: dict[str, CompletionReceipt] = {}
    for receipt in receipt_values:
        if receipt.package_id in completed:
            raise EngineeringError("duplicate_completion_receipt")
        _verify_completion(receipt, envelope, trust_store, now)
        completed[receipt.package_id] = receipt

    base_packages: list[WorkPackage] = []
    already_completed: set[str] = set(completed)
    for package in package_values:
        checked_id(package.package_id, "package_id")
        if (
            type(package.capacity_units) is not int
            or package.capacity_units < 1
            or type(package.ci_units) is not int
            or package.ci_units < 0
            or len(package.required_skills) > MAX_SKILLS
            or len(package.review_roles) > MAX_REVIEW_ROLES
        ):
            raise EngineeringError("invalid_package_capacity")
        if package.package_id not in already_completed:
            base_packages.append(
                WorkPackage(
                    package.priority,
                    package.package_id,
                    package.predecessors,
                    package.write_paths,
                )
            )

    # The durable owner still publishes the exact DAG/path/frontier proposal.
    base = store.schedule_ready_packages(
        envelope.envelope_id,
        tuple(base_packages),
        tuple(completed),
        generation_id=generation_id,
        now_ns=now,
    )
    base_assigned = set(base.assigned)
    blocked: dict[str, str] = dict(base.blocked)
    for identity in sorted(already_completed & set(package_ids)):
        blocked[identity] = "already_completed"
    worker_remaining = {row.worker_id: row.capacity_units for row in worker_values}
    worker_paths: dict[str, list[str]] = {row.worker_id: [] for row in worker_values}
    ci_remaining = capacity.ci_units
    assignments: list[EngineeringAssignment] = []

    by_id = {value.package_id: value for value in package_values}
    ordered = sorted(
        (by_id[identity] for identity in base.assigned),
        key=lambda item: (-_score(item), item.priority, item.package_id),
    )
    for package in ordered:
        score = _score(package)
        eligible_workers = []
        required = set(package.required_skills)
        for worker in worker_values:
            if not required.issubset(set(worker.skills)):
                continue
            if worker_remaining[worker.worker_id] < package.capacity_units:
                continue
            if path_sets_overlap(package.write_paths, tuple(worker_paths[worker.worker_id])):
                continue
            eligible_workers.append(worker)
        if not eligible_workers:
            blocked[package.package_id] = "worker_skill_or_capacity"
            continue
        if ci_remaining < package.ci_units:
            blocked[package.package_id] = "ci_capacity"
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
            blocked[package.package_id] = "review_capacity:" + missing_review
            continue
        worker = sorted(
            eligible_workers,
            key=lambda row: (-worker_remaining[row.worker_id], row.worker_id),
        )[0]
        worker_remaining[worker.worker_id] -= package.capacity_units
        worker_paths[worker.worker_id].extend(package.write_paths)
        ci_remaining -= package.ci_units
        for role in package.review_roles:
            review_remaining[role] -= 1
        assignments.append(
            EngineeringAssignment(
                package.package_id,
                worker.worker_id,
                score,
                package.ci_units,
                tuple(sorted(package.review_roles)),
            )
        )

    assignment_ids = {row.package_id for row in assignments}
    for identity in base_assigned - assignment_ids:
        blocked.setdefault(identity, "advanced_capacity")

    integration_order = tuple(row.package_id for row in assignments)
    merge_queue = tuple(
        MergeQueueProposal(
            index + 1,
            row.package_id,
            "awaiting_candidate_evidence",
            row.score_q32,
        )
        for index, row in enumerate(assignments)
    )
    completion_frontier_digest = semantic_digest(
        [asdict(completed[key]) for key in sorted(completed)]
    )
    return EngineeringPlan(
        generation_id,
        envelope.envelope_id,
        tuple(assignments),
        tuple(sorted(blocked.items())),
        integration_order,
        merge_queue,
        semantic_digest(asdict(base)),
        completion_frontier_digest,
    )
