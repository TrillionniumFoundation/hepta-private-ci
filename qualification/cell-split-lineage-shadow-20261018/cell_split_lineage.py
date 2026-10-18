"""Shadow-only Cell split, differentiation, lineage, and rollback contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from cell_fast_path_actionir import canonical_digest


ZERO = "0" * 64


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value


def _positive(value: int, field: str, upper: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    if upper is not None and value > upper:
        raise ValueError(f"{field} must be <= {upper}")
    return value


def _bounded(value: int, field: str, lower: int, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < lower or value > upper:
        raise ValueError(f"{field} must be an integer in [{lower}, {upper}]")
    return value


@dataclass(frozen=True)
class CellArtifactV1:
    cell_id: str
    parent_cell_id: Optional[str]
    stem_digest: str
    head_digest: str
    adapter_digest: str
    memory_policy_digest: str
    capability_manifest_digest: str
    snapshot_id: str
    generation: int
    split_epoch: int
    modalities: Tuple[str, ...]
    specialization_tag: str
    artifact_digest: str
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        if not self.cell_id or not isinstance(self.cell_id, str):
            raise ValueError("cell_id must be non-empty")
        if self.parent_cell_id == self.cell_id:
            raise ValueError("cell cannot be its own parent")
        if self.parent_cell_id is not None and not self.parent_cell_id:
            raise ValueError("parent_cell_id must be non-empty when present")
        for name in (
            "stem_digest",
            "head_digest",
            "adapter_digest",
            "memory_policy_digest",
            "capability_manifest_digest",
            "artifact_digest",
        ):
            _digest(getattr(self, name), name)
        if not self.snapshot_id or not isinstance(self.snapshot_id, str):
            raise ValueError("snapshot_id must be non-empty")
        _bounded(self.generation, "generation", 0, 2**63 - 1)
        _bounded(self.split_epoch, "split_epoch", 0, 2**63 - 1)
        if not self.modalities or tuple(sorted(set(self.modalities))) != self.modalities:
            raise ValueError("modalities must be a sorted non-empty tuple")
        if any(not isinstance(item, str) or not item for item in self.modalities):
            raise ValueError("modalities must contain non-empty strings")
        if not self.specialization_tag or not isinstance(self.specialization_tag, str):
            raise ValueError("specialization_tag must be non-empty")
        if self.authority != "DENY_ALL":
            raise ValueError("Cell artifacts cannot carry authority")


@dataclass(frozen=True)
class CellChildSpecV1:
    child_cell_id: str
    specialization_tag: str
    adapter_digest: str
    head_digest: str
    capability_manifest_digest: str
    modalities: Tuple[str, ...]
    artifact_digest: str

    def __post_init__(self) -> None:
        if not self.child_cell_id or not isinstance(self.child_cell_id, str):
            raise ValueError("child_cell_id must be non-empty")
        if not self.specialization_tag or not isinstance(self.specialization_tag, str):
            raise ValueError("specialization_tag must be non-empty")
        for name in ("adapter_digest", "head_digest", "capability_manifest_digest", "artifact_digest"):
            _digest(getattr(self, name), name)
        if not self.modalities or tuple(sorted(set(self.modalities))) != self.modalities:
            raise ValueError("modalities must be a sorted non-empty tuple")


@dataclass(frozen=True)
class CellSplitPolicyV1:
    benchmark_digest: str
    min_task_gain_lcb_ppm: int
    max_global_regression_ppm: int
    max_calibration_regression_ppm: int
    min_ood_delta_ppm: int
    max_latency_delta_ns: int
    max_memory_delta_bytes: int
    require_zero_safety_violations: bool = True
    require_rollback_ready: bool = True

    def __post_init__(self) -> None:
        _digest(self.benchmark_digest, "benchmark_digest")
        _bounded(self.min_task_gain_lcb_ppm, "min_task_gain_lcb_ppm", 0, 1_000_000)
        _bounded(self.max_global_regression_ppm, "max_global_regression_ppm", 0, 1_000_000)
        _bounded(self.max_calibration_regression_ppm, "max_calibration_regression_ppm", 0, 1_000_000)
        _bounded(self.min_ood_delta_ppm, "min_ood_delta_ppm", -1_000_000, 1_000_000)
        _bounded(self.max_latency_delta_ns, "max_latency_delta_ns", 0, 2**63 - 1)
        _bounded(self.max_memory_delta_bytes, "max_memory_delta_bytes", 0, 2**63 - 1)


@dataclass(frozen=True)
class CellEvaluationLedgerV1:
    parent_cell_id: str
    child_cell_id: str
    benchmark_digest: str
    task_gain_lcb_ppm: int
    global_regression_ppm: int
    calibration_regression_ppm: int
    ood_delta_ppm: int
    latency_delta_ns: int
    memory_delta_bytes: int
    safety_violations: int
    rollback_ready: bool
    ledger_digest: str

    def __post_init__(self) -> None:
        if not self.parent_cell_id or not self.child_cell_id:
            raise ValueError("parent_cell_id and child_cell_id must be non-empty")
        _digest(self.benchmark_digest, "benchmark_digest")
        _bounded(self.task_gain_lcb_ppm, "task_gain_lcb_ppm", -1_000_000, 1_000_000)
        _bounded(self.global_regression_ppm, "global_regression_ppm", 0, 1_000_000)
        _bounded(self.calibration_regression_ppm, "calibration_regression_ppm", 0, 1_000_000)
        _bounded(self.ood_delta_ppm, "ood_delta_ppm", -1_000_000, 1_000_000)
        _bounded(self.latency_delta_ns, "latency_delta_ns", 0, 2**63 - 1)
        _bounded(self.memory_delta_bytes, "memory_delta_bytes", 0, 2**63 - 1)
        _bounded(self.safety_violations, "safety_violations", 0, 2**31 - 1)
        if not isinstance(self.rollback_ready, bool):
            raise ValueError("rollback_ready must be boolean")
        _digest(self.ledger_digest, "ledger_digest")


@dataclass(frozen=True)
class CellSplitDecisionV1:
    split_id: str
    parent_cell_id: str
    parent_artifact_digest: str
    child_cell_ids: Tuple[str, ...]
    accepted_child_ids: Tuple[str, ...]
    ledger_digests: Tuple[str, ...]
    reason_codes: Tuple[str, ...]
    lineage_digest: str
    authority: str = "DENY_ALL"
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        if not self.split_id or not self.parent_cell_id:
            raise ValueError("split_id and parent_cell_id must be non-empty")
        _digest(self.parent_artifact_digest, "parent_artifact_digest")
        if tuple(sorted(set(self.child_cell_ids))) != self.child_cell_ids:
            raise ValueError("child_cell_ids must be sorted and unique")
        if not self.child_cell_ids:
            raise ValueError("at least one child must be proposed")
        if tuple(sorted(set(self.accepted_child_ids))) != self.accepted_child_ids:
            raise ValueError("accepted_child_ids must be sorted and unique")
        if any(child not in self.child_cell_ids for child in self.accepted_child_ids):
            raise ValueError("accepted child must be proposed")
        if tuple(sorted(set(self.ledger_digests))) != self.ledger_digests:
            raise ValueError("ledger_digests must be sorted and unique")
        for digest in self.ledger_digests:
            _digest(digest, "ledger_digest")
        _digest(self.lineage_digest, "lineage_digest")
        if self.authority != "DENY_ALL" or self.effect_admitted:
            raise ValueError("split decisions cannot carry authority or effects")


@dataclass(frozen=True)
class CellRevocationReceiptV1:
    cell_id: str
    artifact_digest: str
    parent_cell_id: Optional[str]
    generation: int
    reason_digest: str
    revoked: bool
    receipt_digest: str
    authority: str = "DENY_ALL"
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        if not self.cell_id:
            raise ValueError("cell_id must be non-empty")
        _digest(self.artifact_digest, "artifact_digest")
        _bounded(self.generation, "generation", 0, 2**63 - 1)
        _digest(self.reason_digest, "reason_digest")
        if not isinstance(self.revoked, bool) or not self.revoked:
            raise ValueError("revocation receipt must be revoked")
        _digest(self.receipt_digest, "receipt_digest")
        if self.authority != "DENY_ALL" or self.effect_admitted:
            raise ValueError("revocation receipts cannot carry authority or effects")


def _ledger_eligible(ledger: CellEvaluationLedgerV1, policy: CellSplitPolicyV1) -> bool:
    return (
        ledger.benchmark_digest == policy.benchmark_digest
        and ledger.task_gain_lcb_ppm >= policy.min_task_gain_lcb_ppm
        and ledger.global_regression_ppm <= policy.max_global_regression_ppm
        and ledger.calibration_regression_ppm <= policy.max_calibration_regression_ppm
        and ledger.ood_delta_ppm >= policy.min_ood_delta_ppm
        and ledger.latency_delta_ns <= policy.max_latency_delta_ns
        and ledger.memory_delta_bytes <= policy.max_memory_delta_bytes
        and (not policy.require_zero_safety_violations or ledger.safety_violations == 0)
        and (not policy.require_rollback_ready or ledger.rollback_ready)
    )


def decide_cell_split(
    parent: CellArtifactV1,
    split_id: str,
    children: Iterable[CellChildSpecV1],
    ledgers: Iterable[CellEvaluationLedgerV1],
    policy: CellSplitPolicyV1,
) -> CellSplitDecisionV1:
    child_values = tuple(children)
    ledger_values = tuple(ledgers)
    if len(child_values) < 2:
        raise ValueError("CELL_SPLIT_REQUIRES_TWO_CHILDREN")
    if len({child.child_cell_id for child in child_values}) != len(child_values):
        raise ValueError("CELL_CHILD_IDS_MUST_BE_UNIQUE")
    if any(child.child_cell_id == parent.cell_id for child in child_values):
        raise ValueError("CELL_CHILD_CANNOT_REUSE_PARENT_ID")
    child_ids = tuple(sorted(child.child_cell_id for child in child_values))
    by_child = {ledger.child_cell_id: ledger for ledger in ledger_values}
    if len(by_child) != len(ledger_values):
        raise ValueError("CELL_LEDGER_CHILD_IDS_MUST_BE_UNIQUE")
    if any(ledger.parent_cell_id != parent.cell_id for ledger in ledger_values):
        raise ValueError("CELL_LEDGER_PARENT_MISMATCH")
    if set(by_child) != set(child_ids):
        raise ValueError("CELL_LEDGER_SET_MISMATCH")
    accepted = tuple(sorted(child_id for child_id in child_ids if _ledger_eligible(by_child[child_id], policy)))
    reason_codes = ("CHILDREN_MEET_SPLIT_GATE",) if accepted else ("NO_CHILD_MEETS_SPLIT_GATE",)
    ledger_digests = tuple(sorted(ledger.ledger_digest for ledger in ledger_values))
    payload: Mapping[str, object] = {
        "schema": "hepta.cell-split-decision.v1",
        "split_id": split_id,
        "parent_cell_id": parent.cell_id,
        "parent_artifact_digest": parent.artifact_digest,
        "child_cell_ids": child_ids,
        "accepted_child_ids": accepted,
        "ledger_digests": ledger_digests,
        "reason_codes": reason_codes,
        "authority": "DENY_ALL",
        "effect_admitted": False,
    }
    return CellSplitDecisionV1(
        split_id=split_id,
        parent_cell_id=parent.cell_id,
        parent_artifact_digest=parent.artifact_digest,
        child_cell_ids=child_ids,
        accepted_child_ids=accepted,
        ledger_digests=ledger_digests,
        reason_codes=reason_codes,
        lineage_digest=canonical_digest(payload),
    )


def revoke_cell(cell: CellArtifactV1, reason_digest: str) -> CellRevocationReceiptV1:
    _digest(reason_digest, "reason_digest")
    payload: Mapping[str, object] = {
        "schema": "hepta.cell-revocation-receipt.v1",
        "cell_id": cell.cell_id,
        "artifact_digest": cell.artifact_digest,
        "parent_cell_id": cell.parent_cell_id,
        "generation": cell.generation,
        "reason_digest": reason_digest,
        "revoked": True,
        "authority": "DENY_ALL",
        "effect_admitted": False,
    }
    return CellRevocationReceiptV1(
        cell_id=cell.cell_id,
        artifact_digest=cell.artifact_digest,
        parent_cell_id=cell.parent_cell_id,
        generation=cell.generation,
        reason_digest=reason_digest,
        revoked=True,
        receipt_digest=canonical_digest(payload),
    )
