#!/usr/bin/env python3
"""Research-only contracts for a shared Stem and per-Cell differentiation.

This module intentionally contains no model loading, weight mutation, model
selection, or production activation.  It is a deterministic protocol layer
for comparing a frozen shared Stem against Cell-local adapters/heads and for
proposing (never applying) a future-snapshot Cell split.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_STEM = "hepta.stem.manifest.v1"
SCHEMA_CELL = "hepta.cell.artifact.v1"
SCHEMA_MATRIX = "hepta.stem.transfer-matrix.v1"
SCHEMA_SPLIT = "hepta.cell.split-proposal.v1"
SCHEMA_READER = "hepta.reader.four-condition-plan.v1"

ARM_ORDER = ("none", "distractor", "withheld", "full")
FREEZE_POLICY = "immutable_current_generation"
RUNTIME_UPDATE_POLICY = "next_snapshot_proposal"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_DISALLOWED_AUTHORITY = {
    "runtime_mutation",
    "capability_minting",
    "production_activation",
    "model_selection",
    "weight_write",
}


class ContractError(ValueError):
    """Raised when a research artifact violates the frozen protocol."""


def canonical_json(value: Any) -> str:
    """Return stable JSON used for content-addressed research artifacts."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _finite_nonnegative(name: str, value: float) -> None:
    _require(isinstance(value, (int, float)) and math.isfinite(float(value)), f"{name} must be finite")
    _require(float(value) >= 0.0, f"{name} must be non-negative")


def _bounded_text(name: str, value: str, limit: int = 128) -> None:
    _require(isinstance(value, str) and 0 < len(value) <= limit, f"{name} has an invalid length")


@dataclass(frozen=True)
class StemManifestV1:
    stem_id: str
    stem_digest: str
    tokenizer_digest: str
    preprocessor_digest: str
    adapter_basis_digest: str
    hidden_width: int
    modality_projectors: tuple[str, ...]
    current_generation: int = 0
    freeze_policy: str = FREEZE_POLICY

    def __post_init__(self) -> None:
        _identifier("stem_id", self.stem_id)
        for name, value in (
            ("stem_digest", self.stem_digest),
            ("tokenizer_digest", self.tokenizer_digest),
            ("preprocessor_digest", self.preprocessor_digest),
            ("adapter_basis_digest", self.adapter_basis_digest),
        ):
            _digest(name, value)
        _require(isinstance(self.hidden_width, int) and 0 < self.hidden_width <= 8192, "hidden_width is out of bounds")
        _require(0 < len(self.modality_projectors) <= 32, "at least one modality projector is required")
        _require(tuple(sorted(set(self.modality_projectors))) == self.modality_projectors, "projectors must be sorted and unique")
        for projector in self.modality_projectors:
            _bounded_text("modality_projector", projector)
        _require(isinstance(self.current_generation, int) and self.current_generation >= 0, "current_generation is invalid")
        _require(self.freeze_policy == FREEZE_POLICY, "the current Stem must be immutable")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema"] = SCHEMA_STEM
        return result


@dataclass(frozen=True)
class CellArtifactV1:
    cell_id: str
    parent_cell_id: str | None
    stem_digest: str
    adapter_basis_digest: str
    adapter_rank: int
    layer_mask: tuple[int, ...]
    head_digest: str
    memory_schema_digest: str
    state_namespace: str
    objective_digest: str
    generation: int = 0
    fallback_cell_id: str | None = None
    current_run_mutation: bool = False
    next_snapshot_only: bool = True
    authority: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier("cell_id", self.cell_id)
        if self.parent_cell_id is not None:
            _identifier("parent_cell_id", self.parent_cell_id)
            _require(self.parent_cell_id != self.cell_id, "a Cell cannot parent itself")
        _digest("stem_digest", self.stem_digest)
        _digest("adapter_basis_digest", self.adapter_basis_digest)
        _digest("head_digest", self.head_digest)
        _digest("memory_schema_digest", self.memory_schema_digest)
        _digest("objective_digest", self.objective_digest)
        _require(isinstance(self.adapter_rank, int) and 0 < self.adapter_rank <= 1024, "adapter_rank is out of bounds")
        _require(tuple(sorted(set(self.layer_mask))) == self.layer_mask, "layer_mask must be sorted and unique")
        _require(all(isinstance(layer, int) and 0 <= layer <= 4096 for layer in self.layer_mask), "layer_mask is invalid")
        _bounded_text("state_namespace", self.state_namespace)
        _require(isinstance(self.generation, int) and self.generation >= 0, "generation is invalid")
        if self.fallback_cell_id is not None:
            _identifier("fallback_cell_id", self.fallback_cell_id)
        _require(not self.current_run_mutation, "runtime mutation is forbidden for a Cell artifact")
        _require(self.next_snapshot_only, "Cell changes can only enter a future snapshot")
        _require(not (_DISALLOWED_AUTHORITY & set(self.authority)), "Cell artifacts cannot mint authority")
        _require(tuple(sorted(set(self.authority))) == self.authority, "authority labels must be sorted and unique")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["schema"] = SCHEMA_CELL
        return result


@dataclass(frozen=True)
class TransferCaseV1:
    task_id: str
    modality: str
    stem_digest: str
    source_digest: str
    quality: float
    flops: float
    memory_bytes: float
    latency_ms: float
    risk: float = 0.0

    def __post_init__(self) -> None:
        _identifier("task_id", self.task_id)
        _bounded_text("modality", self.modality, 64)
        _digest("stem_digest", self.stem_digest)
        _digest("source_digest", self.source_digest)
        _finite_nonnegative("quality", self.quality)
        for name, value in (("flops", self.flops), ("memory_bytes", self.memory_bytes), ("latency_ms", self.latency_ms), ("risk", self.risk)):
            _finite_nonnegative(name, value)


@dataclass(frozen=True)
class TransferMatrixV1:
    matrix_id: str
    stem: StemManifestV1
    cases: tuple[TransferCaseV1, ...]
    matched_budget_digest: str
    source_policy: str = "independent_new_source_required"

    def __post_init__(self) -> None:
        _identifier("matrix_id", self.matrix_id)
        _digest("matched_budget_digest", self.matched_budget_digest)
        _require(self.source_policy == "independent_new_source_required", "transfer evidence must use an independent source")
        _require(len(self.cases) > 0, "a transfer matrix must contain cases")
        for case in self.cases:
            _require(case.stem_digest == self.stem.stem_digest, "every case must use the same frozen Stem")
        _require(len({case.task_id for case in self.cases}) == len(self.cases), "task_id must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_MATRIX,
            "matrix_id": self.matrix_id,
            "stem": self.stem.to_dict(),
            "cases": [asdict(case) for case in self.cases],
            "matched_budget_digest": self.matched_budget_digest,
            "source_policy": self.source_policy,
        }


def utility(case: TransferCaseV1, *, flop_penalty: float = 0.0, memory_penalty: float = 0.0, latency_penalty: float = 0.0, risk_penalty: float = 0.0) -> float:
    for name, value in (("flop_penalty", flop_penalty), ("memory_penalty", memory_penalty), ("latency_penalty", latency_penalty), ("risk_penalty", risk_penalty)):
        _finite_nonnegative(name, value)
    return float(case.quality) - flop_penalty * float(case.flops) - memory_penalty * float(case.memory_bytes) - latency_penalty * float(case.latency_ms) - risk_penalty * float(case.risk)


def pareto_frontier(cases: Iterable[TransferCaseV1]) -> tuple[TransferCaseV1, ...]:
    """Return non-dominated cases by quality, FLOPs, memory, and latency."""

    items = tuple(cases)
    _require(bool(items), "at least one case is required")
    result: list[TransferCaseV1] = []
    for candidate in items:
        dominated = False
        for other in items:
            no_worse = (
                other.quality >= candidate.quality
                and other.flops <= candidate.flops
                and other.memory_bytes <= candidate.memory_bytes
                and other.latency_ms <= candidate.latency_ms
                and other.risk <= candidate.risk
            )
            strictly_better = (
                other.quality > candidate.quality
                or other.flops < candidate.flops
                or other.memory_bytes < candidate.memory_bytes
                or other.latency_ms < candidate.latency_ms
                or other.risk < candidate.risk
            )
            if other is not candidate and no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            result.append(candidate)
    return tuple(sorted(result, key=lambda item: item.task_id))


@dataclass(frozen=True)
class ParameterLedgerV1:
    stem_params: int
    projector_params: int
    resident_cell_params: int
    active_cell_params: int
    state_params: int
    cache_params: int
    logical_cells: int
    active_cells: int

    def __post_init__(self) -> None:
        for name in ("stem_params", "projector_params", "resident_cell_params", "active_cell_params", "state_params", "cache_params", "logical_cells", "active_cells"):
            value = getattr(self, name)
            _require(isinstance(value, int) and value >= 0, f"{name} must be a non-negative integer")
        _require(self.active_cell_params <= self.resident_cell_params, "active Cell parameters exceed resident parameters")
        _require(self.active_cells <= self.logical_cells, "active Cells exceed logical Cells")

    @property
    def logical_params(self) -> int:
        return self.stem_params + self.projector_params + self.resident_cell_params + self.state_params + self.cache_params

    @property
    def active_params(self) -> int:
        return self.stem_params + self.projector_params + self.active_cell_params + self.state_params + self.cache_params

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "logical_params": self.logical_params, "active_params": self.active_params}


@dataclass(frozen=True)
class SplitGateV1:
    future_lcb: float
    baseline_ucb: float
    old_task_degradation: float
    ece: float
    ood_false_acceptance: float
    fallback_coverage: float
    rollback_recovery: float
    deleted_replay: int
    reader_sufficient: bool = True

    def __post_init__(self) -> None:
        _finite_nonnegative("future_lcb", self.future_lcb)
        _finite_nonnegative("baseline_ucb", self.baseline_ucb)
        _finite_nonnegative("old_task_degradation", self.old_task_degradation)
        _finite_nonnegative("ece", self.ece)
        _finite_nonnegative("ood_false_acceptance", self.ood_false_acceptance)
        for name, value in (("fallback_coverage", self.fallback_coverage), ("rollback_recovery", self.rollback_recovery)):
            _finite_nonnegative(name, value)
            _require(float(value) <= 1.0, f"{name} cannot exceed one")
        _require(isinstance(self.deleted_replay, int) and self.deleted_replay >= 0, "deleted_replay is invalid")

    @property
    def passes(self) -> bool:
        return (
            self.reader_sufficient
            and self.future_lcb > self.baseline_ucb
            and self.old_task_degradation <= 0.02
            and self.ece <= 0.03
            and self.ood_false_acceptance < 0.005
            and self.fallback_coverage == 1.0
            and self.rollback_recovery == 1.0
            and self.deleted_replay == 0
        )

    def reasons(self) -> tuple[str, ...]:
        checks = (
            (self.reader_sufficient, "reader_evidence_insufficient"),
            (self.future_lcb > self.baseline_ucb, "future_lcb_not_above_baseline_ucb"),
            (self.old_task_degradation <= 0.02, "old_task_degradation_exceeds_2pct"),
            (self.ece <= 0.03, "ece_exceeds_0.03"),
            (self.ood_false_acceptance < 0.005, "ood_false_acceptance_not_below_0.005"),
            (self.fallback_coverage == 1.0, "fallback_coverage_incomplete"),
            (self.rollback_recovery == 1.0, "rollback_recovery_incomplete"),
            (self.deleted_replay == 0, "deleted_replay_present"),
        )
        return tuple(reason for passed, reason in checks if not passed)


@dataclass(frozen=True)
class SplitProposalV1:
    parent: CellArtifactV1
    child: CellArtifactV1
    gate: SplitGateV1
    disposition: str
    failure_cluster: str
    current_run_mutation: bool = False

    def __post_init__(self) -> None:
        _bounded_text("failure_cluster", self.failure_cluster)
        _require(self.disposition in {"accept_next_snapshot", "hold", "deny", "merge_back"}, "invalid split disposition")
        _require(self.parent.stem_digest == self.child.stem_digest, "parent and child must use the same Stem")
        _require(self.parent.adapter_basis_digest == self.child.adapter_basis_digest, "parent and child must use the same adapter basis")
        _require(self.child.parent_cell_id == self.parent.cell_id, "child parent link is invalid")
        _require(self.child.generation > self.parent.generation, "split must advance the Cell generation")
        _require(not self.current_run_mutation and not self.child.current_run_mutation, "split cannot mutate the current run")
        if self.disposition == "accept_next_snapshot":
            _require(self.gate.passes, "a failed gate cannot be accepted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_SPLIT,
            "parent": self.parent.to_dict(),
            "child": self.child.to_dict(),
            "gate": asdict(self.gate),
            "gate_passes": self.gate.passes,
            "gate_reasons": self.gate.reasons(),
            "disposition": self.disposition,
            "failure_cluster": self.failure_cluster,
            "current_run_mutation": self.current_run_mutation,
        }


def propose_split(parent: CellArtifactV1, *, child_id: str, failure_cluster: str, gate: SplitGateV1) -> SplitProposalV1:
    """Build a zero-delta child proposal; it is never installed by this module."""

    _identifier("child_id", child_id)
    child = CellArtifactV1(
        cell_id=child_id,
        parent_cell_id=parent.cell_id,
        stem_digest=parent.stem_digest,
        adapter_basis_digest=parent.adapter_basis_digest,
        adapter_rank=parent.adapter_rank,
        layer_mask=parent.layer_mask,
        head_digest=parent.head_digest,
        memory_schema_digest=parent.memory_schema_digest,
        state_namespace=f"{parent.state_namespace}.split.{child_id}",
        objective_digest=parent.objective_digest,
        generation=parent.generation + 1,
        fallback_cell_id=parent.cell_id,
    )
    disposition = "accept_next_snapshot" if gate.passes else "hold"
    return SplitProposalV1(parent=parent, child=child, gate=gate, disposition=disposition, failure_cluster=failure_cluster)


def build_four_condition_plan(
    *, task_id: str, question: str, options: Sequence[str], source_evidence: str, distractor_evidence: str, withheld_evidence: str, evaluator_gold: str
) -> dict[str, Any]:
    """Build Reader arms while keeping evaluator-only gold outside model requests."""

    _identifier("task_id", task_id)
    _bounded_text("question", question, 4096)
    _require(options and all(isinstance(option, str) and option for option in options), "options must be non-empty strings")
    _bounded_text("source_evidence", source_evidence, 16384)
    _bounded_text("distractor_evidence", distractor_evidence, 16384)
    _bounded_text("withheld_evidence", withheld_evidence, 16384)
    _bounded_text("evaluator_gold", evaluator_gold, 1024)
    evidence_by_arm = {
        "none": "",
        "distractor": distractor_evidence,
        "withheld": withheld_evidence,
        "full": source_evidence,
    }
    requests = tuple(
        {
            "task_id": task_id,
            "arm": arm,
            "question": question,
            "options": tuple(options),
            "evidence": evidence_by_arm[arm],
            "gold_visible_to_model": False,
        }
        for arm in ARM_ORDER
    )
    return {
        "schema": SCHEMA_READER,
        "task_id": task_id,
        "arms": ARM_ORDER,
        "model_requests": requests,
        "evaluator": {"gold": evaluator_gold, "gold_visible_to_model": False},
    }


def validate_no_model_visible_gold(plan: Mapping[str, Any]) -> None:
    _require(tuple(plan.get("arms", ())) == ARM_ORDER, "Reader arms must be in the four-condition order")
    evaluator = plan.get("evaluator", {})
    _require(isinstance(evaluator, Mapping) and evaluator.get("gold_visible_to_model") is False, "gold must be evaluator-only")
    for request in plan.get("model_requests", ()):
        _require("gold" not in request and "evaluator" not in request, "gold leaked into a model request")
        _require(request.get("gold_visible_to_model") is False, "model request gold visibility must be false")


def manifest_digest(manifest: StemManifestV1) -> str:
    return content_digest(manifest.to_dict())


__all__ = [
    "ARM_ORDER",
    "CellArtifactV1",
    "ContractError",
    "ParameterLedgerV1",
    "SCHEMA_CELL",
    "SCHEMA_MATRIX",
    "SCHEMA_READER",
    "SCHEMA_SPLIT",
    "SCHEMA_STEM",
    "SplitGateV1",
    "SplitProposalV1",
    "StemManifestV1",
    "TransferCaseV1",
    "TransferMatrixV1",
    "build_four_condition_plan",
    "canonical_json",
    "content_digest",
    "manifest_digest",
    "pareto_frontier",
    "propose_split",
    "utility",
    "validate_no_model_visible_gold",
]
