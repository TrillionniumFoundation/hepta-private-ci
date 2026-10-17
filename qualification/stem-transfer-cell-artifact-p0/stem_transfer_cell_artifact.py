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


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _integer(name: str, value: Any, *, minimum: int = 0, maximum: int | None = None) -> None:
    _require(type(value) is int, f"{name} must be an integer")
    _require(value >= minimum, f"{name} is below its lower bound")
    if maximum is not None:
        _require(value <= maximum, f"{name} is above its upper bound")


def _finite(name: str, value: float) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _finite_nonnegative(name: str, value: float) -> None:
    _finite(name, value)
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
        _integer("hidden_width", self.hidden_width, minimum=1, maximum=8192)
        _require(0 < len(self.modality_projectors) <= 32, "at least one modality projector is required")
        _require(tuple(sorted(set(self.modality_projectors))) == self.modality_projectors, "projectors must be sorted and unique")
        for projector in self.modality_projectors:
            _bounded_text("modality_projector", projector)
        _integer("current_generation", self.current_generation)
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
        _integer("adapter_rank", self.adapter_rank, minimum=1, maximum=1024)
        _require(tuple(sorted(set(self.layer_mask))) == self.layer_mask, "layer_mask must be sorted and unique")
        _require(all(type(layer) is int and 0 <= layer <= 4096 for layer in self.layer_mask), "layer_mask is invalid")
        _bounded_text("state_namespace", self.state_namespace)
        _integer("generation", self.generation)
        if self.fallback_cell_id is not None:
            _identifier("fallback_cell_id", self.fallback_cell_id)
            _require(self.fallback_cell_id != self.cell_id, "a Cell cannot fall back to itself")
        _boolean("current_run_mutation", self.current_run_mutation)
        _boolean("next_snapshot_only", self.next_snapshot_only)
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


@dataclass(frozen=True)
class ModalityEnvelopeV1:
    """Digest-bound feature envelope before it enters the shared Stem."""

    modality: str
    stem_digest: str
    raw_digest: str
    feature_digest: str
    projector_digest: str
    latent_width: int
    slots: int
    temporal_span_ms: float | None = None
    region_count: int = 0
    readonly: bool = True

    def __post_init__(self) -> None:
        _require(self.modality in {"text", "image", "video", "audio"}, "unsupported modality")
        _digest("stem_digest", self.stem_digest)
        for name, value in (("raw_digest", self.raw_digest), ("feature_digest", self.feature_digest), ("projector_digest", self.projector_digest)):
            _digest(name, value)
        _integer("latent_width", self.latent_width, minimum=1, maximum=2048)
        _integer("slots", self.slots, minimum=1, maximum=256)
        _integer("region_count", self.region_count, minimum=0, maximum=4096)
        if self.temporal_span_ms is not None:
            _finite_nonnegative("temporal_span_ms", self.temporal_span_ms)
        if self.modality in {"audio", "video"}:
            _require(self.temporal_span_ms is not None, "temporal modalities require a time span")
        else:
            _require(self.temporal_span_ms is None, "only audio and video envelopes may carry a time span")
        if self.modality != "image":
            _require(self.region_count == 0, "region_count is only valid for image envelopes")
        _boolean("readonly", self.readonly)
        _require(self.readonly, "feature envelopes must be readonly")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": "hepta.modality.envelope.v1"}


@dataclass(frozen=True)
class ResourceCostV1:
    """Fully charged System2 cost; proxy timers or free compute are invalid."""

    encoder_flops: float
    cell_flops: float
    controller_flops: float
    verification_flops: float
    latency_ms: float
    memory_bytes: float
    energy_mj: float

    def __post_init__(self) -> None:
        for name in ("encoder_flops", "cell_flops", "controller_flops", "verification_flops", "latency_ms", "memory_bytes", "energy_mj"):
            _finite_nonnegative(name, getattr(self, name))

    @property
    def total_units(self) -> float:
        # This scalar is an accounting unit for one fixed experiment; it is
        # not a claim that unlike dimensions are physically interchangeable.
        return sum(float(getattr(self, name)) for name in ("encoder_flops", "cell_flops", "controller_flops", "verification_flops", "latency_ms", "memory_bytes", "energy_mj"))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "total_units": self.total_units}


@dataclass(frozen=True)
class System2CandidateV1:
    candidate_id: str
    stem_digest: str
    objective_digest: str
    utility_lcb: float
    utility_ucb: float
    cost: ResourceCostV1
    evidence_digest: str
    feasible: bool = True
    authority: str = "DENY_ALL"
    model_efficacy_measured: bool = False

    def __post_init__(self) -> None:
        _identifier("candidate_id", self.candidate_id)
        _digest("stem_digest", self.stem_digest)
        _digest("objective_digest", self.objective_digest)
        _digest("evidence_digest", self.evidence_digest)
        # Utility may be negative after a fully charged resource cost.  The
        # interval only needs to be finite and ordered; forbidding negative
        # values would silently discard valid high-cost alternatives.
        _finite("utility_lcb", self.utility_lcb)
        _finite("utility_ucb", self.utility_ucb)
        _require(self.utility_lcb <= self.utility_ucb, "utility interval is inverted")
        _require(self.authority == "DENY_ALL", "System2 advisory cannot carry authority")
        _boolean("feasible", self.feasible)
        _boolean("model_efficacy_measured", self.model_efficacy_measured)
        _require(not self.model_efficacy_measured, "this contract cannot certify model efficacy")

    @property
    def net_lcb(self) -> float:
        return self.utility_lcb - self.cost.total_units

    @property
    def net_ucb(self) -> float:
        return self.utility_ucb - self.cost.total_units


@dataclass(frozen=True)
class System2IntervalGateV1:
    candidates: tuple[System2CandidateV1, ...]
    margin: float = 0.0

    def __post_init__(self) -> None:
        _require(len(self.candidates) >= 2, "System2 needs at least two feasible alternatives")
        _finite_nonnegative("margin", self.margin)
        _require(len({candidate.candidate_id for candidate in self.candidates}) == len(self.candidates), "candidate_id must be unique")
        _require(len({candidate.stem_digest for candidate in self.candidates}) == 1, "System2 candidates must share the frozen Stem")
        _require(len({candidate.objective_digest for candidate in self.candidates}) == 1, "System2 candidates must share one fixed objective")

    @property
    def feasible(self) -> tuple[System2CandidateV1, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.feasible)

    def advisory(self) -> dict[str, Any]:
        feasible = self.feasible
        winner: System2CandidateV1 | None = None
        if len(feasible) >= 2:
            for candidate in feasible:
                if all(candidate.net_lcb > other.net_ucb + self.margin for other in feasible if other is not candidate):
                    winner = candidate
                    break
        return {
            "schema": "hepta.ndu.system2.interval-gate.v1",
            "candidate_id": winner.candidate_id if winner else None,
            "decision": "ADVISORY_SELECT" if winner else "NO_GO",
            "evaluator_authority": "DENY_ALL",
            "model_efficacy_measured": False,
            "reason": "unique_interval_dominance" if winner else "interval_overlap_or_missing_feasible_alternative",
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
            _integer(name, value)
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
        _integer("deleted_replay", self.deleted_replay)
        _boolean("reader_sufficient", self.reader_sufficient)

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
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(not self.current_run_mutation and not self.child.current_run_mutation, "split cannot mutate the current run")
        _require(self.child.fallback_cell_id == self.parent.cell_id, "split child must fall back to its parent")
        _require(self.child.state_namespace != self.parent.state_namespace, "split child needs an isolated state namespace")
        _require(self.child.adapter_rank == self.parent.adapter_rank, "split proposal must be zero-delta for adapter rank")
        _require(self.child.layer_mask == self.parent.layer_mask, "split proposal must be zero-delta for layer mask")
        _require(self.child.head_digest == self.parent.head_digest, "split proposal must be zero-delta for head weights")
        _require(self.child.memory_schema_digest == self.parent.memory_schema_digest, "split proposal must preserve memory schema")
        _require(self.child.objective_digest == self.parent.objective_digest, "split proposal must preserve objective")
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
    _require(isinstance(plan, Mapping), "Reader plan must be a mapping")
    _require(plan.get("schema") == SCHEMA_READER, "Reader plan schema is invalid")
    _identifier("task_id", plan.get("task_id"))
    _require(tuple(plan.get("arms", ())) == ARM_ORDER, "Reader arms must be in the four-condition order")
    evaluator = plan.get("evaluator", {})
    _require(isinstance(evaluator, Mapping), "Reader evaluator metadata is invalid")
    _require(set(evaluator) == {"gold", "gold_visible_to_model"}, "Reader evaluator metadata has undeclared fields")
    _bounded_text("evaluator_gold", evaluator.get("gold"), 1024)
    _require(type(evaluator.get("gold_visible_to_model")) is bool and evaluator.get("gold_visible_to_model") is False, "gold must be evaluator-only")
    requests = plan.get("model_requests")
    _require(isinstance(requests, (tuple, list)) and len(requests) == len(ARM_ORDER), "Reader plan must contain exactly four model requests")
    seen_arms: set[str] = set()
    for request in requests:
        _require(isinstance(request, Mapping), "each model request must be a mapping")
        _require(set(request) == {"task_id", "arm", "question", "options", "evidence", "gold_visible_to_model"}, "model request has undeclared fields")
        _require("gold" not in request and "evaluator" not in request, "gold leaked into a model request")
        _require(request.get("task_id") == plan.get("task_id"), "model request task_id does not match the plan")
        _require(request.get("arm") in ARM_ORDER and request.get("arm") not in seen_arms, "model request arm is invalid or duplicated")
        seen_arms.add(request.get("arm"))
        _bounded_text("question", request.get("question"), 4096)
        options = request.get("options")
        _require(isinstance(options, (tuple, list)) and options and all(isinstance(option, str) and option for option in options), "model request options are invalid")
        _require(isinstance(request.get("evidence"), str) and len(request.get("evidence")) <= 16384, "model request evidence is invalid")
        _require(type(request.get("gold_visible_to_model")) is bool and request.get("gold_visible_to_model") is False, "model request gold visibility must be false")
    _require(seen_arms == set(ARM_ORDER), "Reader plan must cover every arm exactly once")


def manifest_digest(manifest: StemManifestV1) -> str:
    return content_digest(manifest.to_dict())


__all__ = [
    "ARM_ORDER",
    "CellArtifactV1",
    "ContractError",
    "ModalityEnvelopeV1",
    "ParameterLedgerV1",
    "ResourceCostV1",
    "SCHEMA_CELL",
    "SCHEMA_MATRIX",
    "SCHEMA_READER",
    "SCHEMA_SPLIT",
    "SCHEMA_STEM",
    "SplitGateV1",
    "SplitProposalV1",
    "StemManifestV1",
    "System2CandidateV1",
    "System2IntervalGateV1",
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
