"""Research-only matched-budget qualification for candidate shared Stems.

This module is a receipt and gate protocol. It does not load checkpoints,
execute models, select a production model, mutate a Stem, or grant authority.
A candidate is admissible for this matrix only when its receipt contains a real
forward execution on an independent source-disjoint evaluation set. Synthetic
smoke and historical replay remain visible as diagnostics but cannot pass the
qualification gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable


SCHEMA_CANDIDATE = "hepta.stem.candidate.v1"
SCHEMA_WORKLOAD = "hepta.stem.workload-profile.v1"
SCHEMA_BUDGET = "hepta.stem.matched-budget.v1"
SCHEMA_COST = "hepta.stem.cost-profile.v1"
SCHEMA_RECEIPT = "hepta.stem.qualification-receipt.v1"
SCHEMA_GATE = "hepta.stem.qualification-gate.v1"
SCHEMA_MATRIX = "hepta.stem.candidate-qualification.v1"

EVIDENCE_CLASSES = frozenset({"REAL_SHADOW", "SYNTHETIC_SMOKE", "HISTORICAL_REPLAY"})
_SOURCE_POLICY = "independent_source_disjoint_required"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class CandidateQualificationError(ValueError):
    """Raised when a candidate Stem qualification artifact is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateQualificationError(message)


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _integer(name: str, value: Any, *, minimum: int = 0, maximum: int | None = None) -> None:
    _require(type(value) is int, f"{name} must be an integer")
    _require(value >= minimum, f"{name} is below its lower bound")
    if maximum is not None:
        _require(value <= maximum, f"{name} is above its upper bound")


def _finite(name: str, value: float, *, minimum: float = 0.0, maximum: float | None = None) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")
    _require(float(value) >= minimum, f"{name} is below its lower bound")
    if maximum is not None:
        _require(float(value) <= maximum, f"{name} is above its upper bound")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be boolean")


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest_object(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkloadProfileV1:
    workload_id: str
    logical_cells: int
    active_cells: int
    unique_stem_inputs: int
    task_mix_digest: str
    sequence_length_digest: str

    def __post_init__(self) -> None:
        _identifier("workload_id", self.workload_id)
        _integer("logical_cells", self.logical_cells, minimum=1)
        _integer("active_cells", self.active_cells, minimum=1)
        _integer("unique_stem_inputs", self.unique_stem_inputs, minimum=1)
        _require(self.active_cells <= self.logical_cells, "active Cells exceed logical Cells")
        _require(self.unique_stem_inputs <= self.logical_cells, "unique Stem inputs exceed logical Cells")
        _digest("task_mix_digest", self.task_mix_digest)
        _digest("sequence_length_digest", self.sequence_length_digest)

    @property
    def workload_digest(self) -> str:
        return _digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_WORKLOAD, "workload_digest": self.workload_digest}


@dataclass(frozen=True)
class CandidateStemSpecV1:
    candidate_id: str
    parameter_tier: str
    stem_digest: str
    checkpoint_digest: str
    architecture_id: str
    tokenizer_digest: str
    preprocessor_digest: str
    projector_registry_digest: str
    cell_head_digest: str
    objective_digest: str
    hidden_width: int
    stem_params: int
    projector_params: int
    cell_head_params: int
    controller_params: int
    current_generation: int = 0
    role: str = "encoder_only"
    frozen: bool = True
    source_bound: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("parameter_tier", self.parameter_tier),
            ("architecture_id", self.architecture_id),
        ):
            _identifier(name, value)
        for name, value in (
            ("stem_digest", self.stem_digest),
            ("checkpoint_digest", self.checkpoint_digest),
            ("tokenizer_digest", self.tokenizer_digest),
            ("preprocessor_digest", self.preprocessor_digest),
            ("projector_registry_digest", self.projector_registry_digest),
            ("cell_head_digest", self.cell_head_digest),
            ("objective_digest", self.objective_digest),
        ):
            _digest(name, value)
        _integer("hidden_width", self.hidden_width, minimum=1, maximum=8192)
        for name, value in (
            ("stem_params", self.stem_params),
            ("projector_params", self.projector_params),
            ("cell_head_params", self.cell_head_params),
            ("controller_params", self.controller_params),
            ("current_generation", self.current_generation),
        ):
            _integer(name, value, minimum=0)
        _require(self.role in {"encoder_only", "encoder_decoder"}, "unsupported Stem role")
        _boolean("frozen", self.frozen)
        _require(self.frozen, "candidate Stem must be frozen during qualification")
        _boolean("source_bound", self.source_bound)
        _require(self.source_bound, "candidate Stem must be source-bound")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_CANDIDATE}


@dataclass(frozen=True)
class MatchedBudgetV1:
    budget_id: str
    workload: WorkloadProfileV1
    max_stem_params: int
    max_projector_params: int
    max_cell_head_params: int
    max_controller_params: int
    max_encoder_flops: float
    max_projector_flops: float
    max_head_flops: float
    max_controller_flops: float
    max_p95_latency_ms: float
    max_peak_memory_bytes: float
    max_energy_mj: float

    def __post_init__(self) -> None:
        _identifier("budget_id", self.budget_id)
        for name, value in (
            ("max_stem_params", self.max_stem_params),
            ("max_projector_params", self.max_projector_params),
            ("max_cell_head_params", self.max_cell_head_params),
            ("max_controller_params", self.max_controller_params),
        ):
            _integer(name, value, minimum=1)
        for name, value in (
            ("max_encoder_flops", self.max_encoder_flops),
            ("max_projector_flops", self.max_projector_flops),
            ("max_head_flops", self.max_head_flops),
            ("max_controller_flops", self.max_controller_flops),
            ("max_p95_latency_ms", self.max_p95_latency_ms),
            ("max_peak_memory_bytes", self.max_peak_memory_bytes),
            ("max_energy_mj", self.max_energy_mj),
        ):
            _finite(name, value, minimum=0.0)
        _require(self.max_p95_latency_ms > 0 and self.max_peak_memory_bytes > 0, "latency and memory budgets must be positive")

    @property
    def budget_digest(self) -> str:
        return _digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "workload": self.workload.to_dict(), "schema": SCHEMA_BUDGET, "budget_digest": self.budget_digest}


@dataclass(frozen=True)
class CostNormalizationProfileV1:
    profile_id: str
    flop_reference: float
    memory_reference: float
    latency_reference: float
    energy_reference: float
    flop_weight: float = 0.25
    memory_weight: float = 0.25
    latency_weight: float = 0.25
    energy_weight: float = 0.25

    def __post_init__(self) -> None:
        _identifier("profile_id", self.profile_id)
        for name, value in (
            ("flop_reference", self.flop_reference),
            ("memory_reference", self.memory_reference),
            ("latency_reference", self.latency_reference),
            ("energy_reference", self.energy_reference),
        ):
            _finite(name, value, minimum=0.0)
            _require(float(value) > 0.0, f"{name} must be positive")
        weights = (self.flop_weight, self.memory_weight, self.latency_weight, self.energy_weight)
        for name, value in zip(("flop_weight", "memory_weight", "latency_weight", "energy_weight"), weights):
            _finite(name, value, minimum=0.0)
        _require(abs(sum(weights) - 1.0) <= 1e-9, "cost weights must sum to one")

    @property
    def profile_digest(self) -> str:
        return _digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_COST, "profile_digest": self.profile_digest}

    def normalized_score(self, receipt: "StemQualificationReceiptV1") -> float:
        total_flops = receipt.encoder_flops + receipt.projector_flops + receipt.head_flops + receipt.controller_flops
        return (
            self.flop_weight * total_flops / self.flop_reference
            + self.memory_weight * receipt.peak_memory_bytes / self.memory_reference
            + self.latency_weight * receipt.p95_latency_ms / self.latency_reference
            + self.energy_weight * receipt.energy_mj / self.energy_reference
        )


@dataclass(frozen=True)
class StemQualificationReceiptV1:
    candidate_id: str
    task_id: str
    modality: str
    stem_digest: str
    objective_digest: str
    source_digest: str
    training_source_digest: str
    budget_digest: str
    cost_profile_digest: str
    quality_lcb: float
    quality_ucb: float
    old_task_degradation: float
    ece: float
    ood_false_acceptance: float
    fallback_coverage: float
    rollback_recovery: float
    deleted_replay: int
    encoder_flops: float
    projector_flops: float
    head_flops: float
    controller_flops: float
    p95_latency_ms: float
    peak_memory_bytes: float
    energy_mj: float
    resident_params: int
    active_params: int
    cache_hit_rate: float
    throughput: float
    source_family_count: int
    future_window_count: int
    case_count: int
    confidence_level: float
    metric_definition_digest: str
    statistical_policy_digest: str
    paired_control_digest: str
    evidence_class: str
    independent_new_source: bool
    forward_executed: bool
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("task_id", self.task_id),
            ("modality", self.modality),
        ):
            _identifier(name, value)
        for name, value in (
            ("stem_digest", self.stem_digest),
            ("objective_digest", self.objective_digest),
            ("source_digest", self.source_digest),
            ("training_source_digest", self.training_source_digest),
            ("budget_digest", self.budget_digest),
            ("cost_profile_digest", self.cost_profile_digest),
            ("metric_definition_digest", self.metric_definition_digest),
            ("statistical_policy_digest", self.statistical_policy_digest),
            ("paired_control_digest", self.paired_control_digest),
        ):
            _digest(name, value)
        _require(self.source_digest != self.training_source_digest, "evaluation source must be source-disjoint from training")
        _require(self.evidence_class in EVIDENCE_CLASSES, "unknown evidence class")
        for name, value in (
            ("quality_lcb", self.quality_lcb),
            ("quality_ucb", self.quality_ucb),
            ("old_task_degradation", self.old_task_degradation),
            ("ece", self.ece),
            ("ood_false_acceptance", self.ood_false_acceptance),
            ("fallback_coverage", self.fallback_coverage),
            ("rollback_recovery", self.rollback_recovery),
            ("encoder_flops", self.encoder_flops),
            ("projector_flops", self.projector_flops),
            ("head_flops", self.head_flops),
            ("controller_flops", self.controller_flops),
            ("p95_latency_ms", self.p95_latency_ms),
            ("peak_memory_bytes", self.peak_memory_bytes),
            ("energy_mj", self.energy_mj),
            ("cache_hit_rate", self.cache_hit_rate),
            ("throughput", self.throughput),
            ("confidence_level", self.confidence_level),
        ):
            _finite(name, value, minimum=0.0)
        _require(self.quality_lcb <= self.quality_ucb, "quality interval is inverted")
        for name, value in (("fallback_coverage", self.fallback_coverage), ("rollback_recovery", self.rollback_recovery), ("cache_hit_rate", self.cache_hit_rate)):
            _require(value <= 1.0, f"{name} cannot exceed one")
        _require(self.confidence_level <= 1.0, "confidence_level cannot exceed one")
        _integer("deleted_replay", self.deleted_replay, minimum=0)
        for name, value in (
            ("resident_params", self.resident_params),
            ("active_params", self.active_params),
            ("source_family_count", self.source_family_count),
            ("future_window_count", self.future_window_count),
            ("case_count", self.case_count),
        ):
            _integer(name, value, minimum=1)
        _require(self.active_params <= self.resident_params, "active params exceed resident params")
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("forward_executed", self.forward_executed)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(not self.model_input_gold_visible, "gold cannot be visible to the model")

    @property
    def eligible(self) -> bool:
        return (
            self.evidence_class == "REAL_SHADOW"
            and self.independent_new_source
            and self.forward_executed
            and not self.model_input_gold_visible
            and self.source_family_count >= 2
            and self.future_window_count >= 2
        )

    @property
    def total_flops(self) -> float:
        return self.encoder_flops + self.projector_flops + self.head_flops + self.controller_flops

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_RECEIPT, "eligible": self.eligible, "total_flops": self.total_flops}


@dataclass(frozen=True)
class StemQualificationGateV1:
    candidate_id: str
    baseline_candidate_id: str
    objective_digest: str
    quality_lcb: float
    baseline_ucb: float
    quality_tolerance: float
    old_task_degradation: float
    ece: float
    ood_false_acceptance: float
    fallback_coverage: float
    rollback_recovery: float
    deleted_replay: int
    source_family_count: int
    future_window_count: int
    confidence_level: float
    evidence_class: str
    p95_latency_ms: float
    peak_memory_bytes: float
    energy_mj: float
    normalized_cost: float
    budget_feasible: bool
    measured_shared_execution: bool
    pareto_non_dominated: bool
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        _identifier("candidate_id", self.candidate_id)
        _identifier("baseline_candidate_id", self.baseline_candidate_id)
        _require(self.candidate_id != self.baseline_candidate_id, "candidate and baseline must differ")
        _digest("objective_digest", self.objective_digest)
        for name, value in (
            ("quality_lcb", self.quality_lcb),
            ("baseline_ucb", self.baseline_ucb),
            ("quality_tolerance", self.quality_tolerance),
            ("old_task_degradation", self.old_task_degradation),
            ("ece", self.ece),
            ("ood_false_acceptance", self.ood_false_acceptance),
            ("fallback_coverage", self.fallback_coverage),
            ("rollback_recovery", self.rollback_recovery),
            ("p95_latency_ms", self.p95_latency_ms),
            ("peak_memory_bytes", self.peak_memory_bytes),
            ("energy_mj", self.energy_mj),
            ("normalized_cost", self.normalized_cost),
        ):
            _finite(name, value, minimum=0.0)
        _require(self.quality_tolerance <= 1.0, "quality_tolerance cannot exceed one")
        _require(self.fallback_coverage <= 1.0 and self.rollback_recovery <= 1.0, "coverage cannot exceed one")
        _require(self.ood_false_acceptance < 1.0, "ood_false_acceptance must be below one")
        _integer("deleted_replay", self.deleted_replay, minimum=0)
        _integer("source_family_count", self.source_family_count, minimum=1)
        _integer("future_window_count", self.future_window_count, minimum=1)
        _finite("confidence_level", self.confidence_level, minimum=0.0, maximum=1.0)
        _require(self.evidence_class in EVIDENCE_CLASSES, "unknown evidence class")
        _boolean("budget_feasible", self.budget_feasible)
        _boolean("measured_shared_execution", self.measured_shared_execution)
        _boolean("pareto_non_dominated", self.pareto_non_dominated)
        _require(self.authority == "DENY_ALL", "qualification gate cannot carry authority")

    @property
    def passes(self) -> bool:
        return (
            self.evidence_class == "REAL_SHADOW"
            and self.source_family_count >= 2
            and self.future_window_count >= 2
            and self.confidence_level >= 0.95
            and self.quality_lcb >= self.baseline_ucb - self.quality_tolerance
            and self.old_task_degradation <= 0.02
            and self.ece <= 0.03
            and self.ood_false_acceptance < 0.005
            and self.fallback_coverage == 1.0
            and self.rollback_recovery == 1.0
            and self.deleted_replay == 0
            and self.p95_latency_ms > 0.0
            and self.peak_memory_bytes > 0.0
            and self.energy_mj > 0.0
            and self.normalized_cost >= 0.0
            and self.budget_feasible
            and self.measured_shared_execution
            and self.pareto_non_dominated
        )

    def reasons(self) -> tuple[str, ...]:
        checks = (
            (self.evidence_class == "REAL_SHADOW", "evidence_is_not_real_shadow"),
            (self.source_family_count >= 2, "source_family_count_below_two"),
            (self.future_window_count >= 2, "future_window_count_below_two"),
            (self.confidence_level >= 0.95, "confidence_level_below_0.95"),
            (self.quality_lcb >= self.baseline_ucb - self.quality_tolerance, "quality_lcb_below_baseline_tolerance"),
            (self.old_task_degradation <= 0.02, "old_task_degradation_exceeds_2pct"),
            (self.ece <= 0.03, "ece_exceeds_0.03"),
            (self.ood_false_acceptance < 0.005, "ood_false_acceptance_not_below_0.005"),
            (self.fallback_coverage == 1.0, "fallback_coverage_incomplete"),
            (self.rollback_recovery == 1.0, "rollback_recovery_incomplete"),
            (self.deleted_replay == 0, "deleted_replay_present"),
            (self.p95_latency_ms > 0.0, "p95_latency_missing"),
            (self.peak_memory_bytes > 0.0, "peak_memory_missing"),
            (self.energy_mj > 0.0, "energy_missing"),
            (self.budget_feasible, "budget_infeasible"),
            (self.measured_shared_execution, "shared_execution_not_measured"),
            (self.pareto_non_dominated, "candidate_is_cost_dominated"),
        )
        return tuple(reason for passed, reason in checks if not passed)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_GATE, "passes": self.passes, "reasons": self.reasons()}


def within_budget(candidate: CandidateStemSpecV1, receipt: StemQualificationReceiptV1, budget: MatchedBudgetV1) -> bool:
    return (
        candidate.stem_params <= budget.max_stem_params
        and candidate.projector_params <= budget.max_projector_params
        and candidate.cell_head_params <= budget.max_cell_head_params
        and candidate.controller_params <= budget.max_controller_params
        and receipt.encoder_flops <= budget.max_encoder_flops
        and receipt.projector_flops <= budget.max_projector_flops
        and receipt.head_flops <= budget.max_head_flops
        and receipt.controller_flops <= budget.max_controller_flops
        and receipt.p95_latency_ms <= budget.max_p95_latency_ms
        and receipt.peak_memory_bytes <= budget.max_peak_memory_bytes
        and receipt.energy_mj <= budget.max_energy_mj
    )


@dataclass(frozen=True)
class StemCandidateQualificationV1:
    matrix_id: str
    objective_digest: str
    budget: MatchedBudgetV1
    cost_profile: CostNormalizationProfileV1
    candidates: tuple[CandidateStemSpecV1, ...]
    receipts: tuple[StemQualificationReceiptV1, ...]
    gates: tuple[StemQualificationGateV1, ...]
    source_policy: str = _SOURCE_POLICY
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        _identifier("matrix_id", self.matrix_id)
        _digest("objective_digest", self.objective_digest)
        _require(self.source_policy == _SOURCE_POLICY, "candidate matrix requires independent source-disjoint evidence")
        _require(self.authority == "DENY_ALL", "candidate matrix cannot carry authority")
        _require(type(self.candidates) is tuple and type(self.receipts) is tuple and type(self.gates) is tuple, "matrix collections must be immutable tuples")
        _require(len(self.candidates) >= 2, "candidate matrix needs at least two Stems")
        _require(len({candidate.candidate_id for candidate in self.candidates}) == len(self.candidates), "candidate IDs must be unique")
        _require(len({candidate.stem_digest for candidate in self.candidates}) == len(self.candidates), "candidate Stem digests must be unique")
        _require(all(candidate.objective_digest == self.objective_digest for candidate in self.candidates), "candidate objective mismatch")
        _require(self.budget.budget_digest == self._budget_digest_from_receipts(), "budget digest does not match receipts")
        _require(self.cost_profile.profile_digest == self._cost_digest_from_receipts(), "cost profile digest does not match receipts")
        ids = {candidate.candidate_id for candidate in self.candidates}
        keys: set[tuple[str, str]] = set()
        by_candidate: dict[str, set[tuple[str, str]]] = {candidate_id: set() for candidate_id in ids}
        for receipt in self.receipts:
            _require(receipt.candidate_id in ids, "receipt references an unknown candidate")
            candidate = next(candidate for candidate in self.candidates if candidate.candidate_id == receipt.candidate_id)
            _require(receipt.stem_digest == candidate.stem_digest, "receipt Stem digest mismatch")
            _require(receipt.objective_digest == self.objective_digest, "receipt objective mismatch")
            _require(receipt.budget_digest == self.budget.budget_digest, "receipt budget mismatch")
            _require(receipt.cost_profile_digest == self.cost_profile.profile_digest, "receipt cost profile mismatch")
            key = (receipt.task_id, receipt.modality)
            _require(key not in by_candidate[receipt.candidate_id], "duplicate candidate task/modality receipt")
            by_candidate[receipt.candidate_id].add(key)
            keys.add(key)
        _require(self.receipts and all(by_candidate[candidate_id] == keys for candidate_id in ids), "every candidate must cover the same task/modality set")
        source_by_key: dict[tuple[str, str], tuple[str, str]] = {}
        for receipt in self.receipts:
            key = (receipt.task_id, receipt.modality)
            source = (receipt.source_digest, receipt.training_source_digest)
            if key in source_by_key:
                _require(source_by_key[key] == source, "matched candidates must use identical source digests")
            source_by_key[key] = source
        gate_ids = {gate.candidate_id for gate in self.gates}
        _require(gate_ids <= ids, "gate references an unknown candidate")
        _require(all(gate.objective_digest == self.objective_digest for gate in self.gates), "gate objective mismatch")

    def _budget_digest_from_receipts(self) -> str:
        return next(iter(self.receipts)).budget_digest if self.receipts else ""

    def _cost_digest_from_receipts(self) -> str:
        return next(iter(self.receipts)).cost_profile_digest if self.receipts else ""

    def eligible_receipts(self) -> tuple[StemQualificationReceiptV1, ...]:
        return tuple(receipt for receipt in self.receipts if receipt.eligible)

    def advisory(self) -> dict[str, Any]:
        passing = tuple(gate for gate in self.gates if gate.passes)
        candidate_id = passing[0].candidate_id if len(passing) == 1 else None
        return {
            "schema": "hepta.stem.candidate-advisory.v1",
            "candidate_id": candidate_id,
            "decision": "ADVISORY_SELECT" if candidate_id else "NO_GO",
            "reason": "unique_gate_pass" if candidate_id else ("multiple_passing_candidates" if len(passing) > 1 else "no_candidate_passed"),
            "authority": "DENY_ALL",
            "production_activation": False,
            "model_selection": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_MATRIX,
            "matrix_id": self.matrix_id,
            "objective_digest": self.objective_digest,
            "budget": self.budget.to_dict(),
            "cost_profile": self.cost_profile.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "receipts": [receipt.to_dict() for receipt in self.receipts],
            "gates": [gate.to_dict() for gate in self.gates],
            "source_policy": self.source_policy,
            "authority": self.authority,
            "eligible_receipts": len(self.eligible_receipts()),
            "advisory": self.advisory(),
        }


__all__ = [
    "CandidateQualificationError",
    "CandidateStemSpecV1",
    "CostNormalizationProfileV1",
    "MatchedBudgetV1",
    "SCHEMA_BUDGET",
    "SCHEMA_CANDIDATE",
    "SCHEMA_COST",
    "SCHEMA_GATE",
    "SCHEMA_MATRIX",
    "SCHEMA_RECEIPT",
    "SCHEMA_WORKLOAD",
    "StemCandidateQualificationV1",
    "StemQualificationGateV1",
    "StemQualificationReceiptV1",
    "WorkloadProfileV1",
    "within_budget",
]
