"""Shadow-only prospective equal-budget plan for a shared Stem experiment.

This module defines the experiment boundary that must exist before a real
frozen-checkpoint transfer matrix is collected.  It does not load a model,
train a Cell, select a winner, mutate a running snapshot, or turn synthetic
data into efficacy evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


SCHEMA_PLAN = "hepta.prospective.equal-budget-plan.v1"
SCHEMA_BUDGET = "hepta.prospective.resource-budget.v1"
SCHEMA_READER = "hepta.prospective.reader-design.v1"
SCHEMA_CANDIDATE = "hepta.prospective.candidate-arm.v1"
SCHEMA_RECEIPT = "hepta.prospective.resource-receipt.v1"

READER_ARMS = ("none", "distractor", "withheld", "full")
REQUIRED_CANDIDATES = (
    "shared_head",
    "split_head",
    "lora_r2",
    "lora_r4",
    "lora_r8",
    "full_fork",
    "strong_cheap",
    "zero_feature_prior",
    "no_change_teacher",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class ProspectivePlanError(ValueError):
    """Raised when a prospective experiment would not be auditable."""


def _load_system2_contracts():
    """Load the research-only System2 contract without changing package paths."""

    try:
        from stem_transfer_cell_artifact import (  # type: ignore
            ResourceCostV1,
            System2CandidateV1,
            System2IntervalGateV1,
        )
        return ResourceCostV1, System2CandidateV1, System2IntervalGateV1
    except ModuleNotFoundError:
        contract_path = Path(__file__).resolve().parents[2] / "stem-transfer-cell-artifact-p0" / "stem_transfer_cell_artifact.py"
        spec = importlib.util.spec_from_file_location("stem_transfer_cell_artifact", contract_path)
        if spec is None or spec.loader is None:
            raise ProspectivePlanError(f"unable to load Stem/System2 contract: {contract_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # pragma: no cover - loader details vary by Python
            raise ProspectivePlanError("unable to load Stem/System2 contract") from exc
        return module.ResourceCostV1, module.System2CandidateV1, module.System2IntervalGateV1


ResourceCostV1, System2CandidateV1, System2IntervalGateV1 = _load_system2_contracts()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProspectivePlanError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _git_blob_digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX40.fullmatch(value)), f"{name} must be a lowercase Git SHA-1")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _integer(name: str, value: Any, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")


def _finite_nonnegative(name: str, value: Any) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)) and float(value) >= 0.0, f"{name} must be finite and non-negative")


def _contains_gold_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(key in {"gold", "canonical_gold", "gold_answer", "evaluator_gold", "answer_key", "correct_answer"} for key in value):
            return True
        return any(_contains_gold_key(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_gold_key(child) for child in value)
    return False


def reader_request_digest(*, task_id: str, reader_arm: str, source_path: str, state: Mapping[str, Any], questions: Mapping[str, Any], manifest_sha256: str) -> str:
    """Hash model-visible request fields only; evaluator gold is forbidden."""
    _identifier("task_id", task_id)
    _require(reader_arm in READER_ARMS, "unknown Reader arm")
    _require(isinstance(source_path, str) and source_path and not source_path.startswith("/"), "invalid source path")
    _digest("manifest_sha256", manifest_sha256)
    _require(not _contains_gold_key((state, questions)), "gold key cannot enter request digest")
    payload = {"task_id": task_id, "reader_arm": reader_arm, "source_path": source_path, "state": state, "questions": questions, "manifest_sha256": manifest_sha256}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResourceBudgetV1:
    budget_digest: str
    cost_weights_digest: str
    max_forward_calls: int
    max_input_tokens: int
    max_flops: float
    max_peak_memory_bytes: float
    max_p95_latency_ms: float
    max_energy_mj: float

    def __post_init__(self) -> None:
        _digest("budget_digest", self.budget_digest)
        _digest("cost_weights_digest", self.cost_weights_digest)
        _integer("max_forward_calls", self.max_forward_calls, minimum=1)
        _integer("max_input_tokens", self.max_input_tokens, minimum=1)
        for name in ("max_flops", "max_peak_memory_bytes", "max_p95_latency_ms", "max_energy_mj"):
            _finite_nonnegative(name, getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_BUDGET}


@dataclass(frozen=True)
class ReaderDesignV1:
    manifest_sha256: str
    independent_source_digest: str
    task_count: int
    presentations: int = 1
    arms: tuple[str, ...] = READER_ARMS
    independent_new_source: bool = True
    independently_held_labels: bool = True
    model_input_gold_visible: bool = False
    assignment_seed: int = 17

    def __post_init__(self) -> None:
        _digest("manifest_sha256", self.manifest_sha256)
        _digest("independent_source_digest", self.independent_source_digest)
        _integer("task_count", self.task_count, minimum=1)
        # P1 has no presentation index in ProspectiveCaseV1.  Refuse the
        # four-presentation option until a v2 case schema binds each repeated
        # presentation explicitly, otherwise the call budget could be
        # overstated while the matrix still contains one four-arm group.
        _require(self.presentations == 1, "P1 Reader design requires one presentation; use a v2 case schema for four")
        _require(tuple(self.arms) == READER_ARMS, "Reader arms must be none/distractor/withheld/full in order")
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("independently_held_labels", self.independently_held_labels)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(self.independent_new_source, "prospective plan requires an independent new source")
        _require(self.independently_held_labels, "prospective plan requires independently held labels")
        _require(not self.model_input_gold_visible, "gold must remain evaluator-only")
        _integer("assignment_seed", self.assignment_seed, minimum=0)

    @property
    def calls_per_candidate(self) -> int:
        return self.task_count * len(READER_ARMS) * self.presentations

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_READER}


@dataclass(frozen=True)
class CandidateArmV1:
    candidate_id: str
    family: str
    stem_digest: str
    adapter_digest: str
    head_digest: str
    objective_digest: str
    budget_digest: str
    resident_params: int
    active_params: int
    cell_count: int
    adapter_rank: int
    shared_stem_frozen: bool
    control: bool = False
    gate_eligible: bool = True
    reference_only: bool = False

    def __post_init__(self) -> None:
        _identifier("candidate_id", self.candidate_id)
        _require(self.family in {"shared_head", "split_head", "lora", "full_fork", "baseline"}, "unknown candidate family")
        for name, value in (("stem_digest", self.stem_digest), ("adapter_digest", self.adapter_digest), ("head_digest", self.head_digest), ("objective_digest", self.objective_digest), ("budget_digest", self.budget_digest)):
            _digest(name, value)
        for name in ("resident_params", "active_params", "cell_count"):
            _integer(name, getattr(self, name), minimum=1)
        _integer("adapter_rank", self.adapter_rank, minimum=0)
        _require(self.active_params <= self.resident_params, "active parameters cannot exceed resident parameters")
        _boolean("shared_stem_frozen", self.shared_stem_frozen)
        _boolean("control", self.control)
        _boolean("gate_eligible", self.gate_eligible)
        _boolean("reference_only", self.reference_only)
        _require(not (self.gate_eligible and self.reference_only), "reference-only candidate cannot enter the System2 gate")
        if self.reference_only:
            _require(self.control, "reference-only candidate must be a control")
        if self.family == "split_head":
            _require(self.cell_count > 1, "split_head must contain more than one Cell")
        if self.family == "lora":
            _require(self.adapter_rank in (2, 4, 8), "LoRA candidate rank must be 2, 4, or 8")
        if self.family in {"shared_head", "split_head", "lora"}:
            _require(self.shared_stem_frozen, "shared Stem experiment arms must freeze the Stem")
            _require(not self.control, "shared Stem experiment arms are not controls")
        if self.family in {"full_fork", "baseline"}:
            _require(self.control, "full fork and baseline arms must be controls")
        if self.family == "full_fork":
            _require(self.reference_only and not self.gate_eligible, "full fork must remain reference-only")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_CANDIDATE}


@dataclass(frozen=True)
class ResourceReceiptV1:
    candidate_id: str
    budget_digest: str
    evidence_class: str
    forward_calls: int | None
    input_tokens: int | None
    flops: float | None
    peak_memory_bytes: float | None
    p95_latency_ms: float | None
    energy_mj: float | None
    independent_new_source: bool
    model_input_gold_visible: bool = False
    missing_fields: tuple[str, ...] = ()

    _NUMERIC_FIELDS = (
        "forward_calls", "input_tokens", "flops", "peak_memory_bytes",
        "p95_latency_ms", "energy_mj",
    )

    def __post_init__(self) -> None:
        _identifier("candidate_id", self.candidate_id)
        _digest("budget_digest", self.budget_digest)
        _require(self.evidence_class in {"REAL_SHADOW", "SYNTHETIC_SMOKE", "INCOMPLETE"}, "unknown resource evidence class")
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(self.independent_new_source, "resource receipt must identify an independent source")
        _require(not self.model_input_gold_visible, "resource receipt cannot expose model-visible gold")
        actual_missing = tuple(name for name in self._NUMERIC_FIELDS if getattr(self, name) is None)
        _require(tuple(sorted(actual_missing)) == tuple(self.missing_fields), "missing_fields must exactly describe missing receipt values")
        if self.evidence_class == "INCOMPLETE":
            _require(bool(actual_missing), "incomplete resource receipt must identify missing fields")
        else:
            _require(not actual_missing, "complete resource receipt cannot contain missing fields")
        for name in self._NUMERIC_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if name in {"forward_calls", "input_tokens"}:
                _integer(name, value, minimum=0)
            else:
                _finite_nonnegative(name, value)

    def to_dict(self) -> dict[str, Any]:
        result = {**asdict(self), "schema": SCHEMA_RECEIPT}
        result["missing_fields"] = list(self.missing_fields)
        return result


@dataclass(frozen=True)
class ProspectiveCaseV1:
    """One candidate/task/Reader-arm observation in the transfer matrix."""

    case_id: str
    candidate_id: str
    task_id: str
    reader_arm: str
    source_split: str
    source_digest: str
    source_blob_digest: str
    request_digest: str
    reader_manifest_digest: str
    budget_digest: str
    replicate: int
    evidence_class: str
    status: str
    label_digest: str | None
    model_digest: str | None
    quality: float | None
    quality_lcb: float | None
    quality_ucb: float | None
    resource: ResourceReceiptV1 | None
    resident_params: int | None
    active_params: int | None
    independent_new_source: bool = True
    model_input_gold_visible: bool = False
    missing_fields: tuple[str, ...] = ()

    _REQUIRED_COMPLETE_FIELDS = (
        "label_digest", "model_digest", "quality", "quality_lcb", "quality_ucb", "resource",
        "resident_params", "active_params",
    )

    def __post_init__(self) -> None:
        for name, value in (("case_id", self.case_id), ("candidate_id", self.candidate_id), ("task_id", self.task_id)):
            _identifier(name, value)
        _require(self.reader_arm in READER_ARMS, "unknown Reader arm")
        _require(self.source_split in {"validation", "future", "ood"}, "unknown source split")
        for name, value in (("source_digest", self.source_digest), ("request_digest", self.request_digest), ("reader_manifest_digest", self.reader_manifest_digest), ("budget_digest", self.budget_digest)):
            _digest(name, value)
        _git_blob_digest("source_blob_digest", self.source_blob_digest)
        _integer("replicate", self.replicate, minimum=0)
        _require(self.evidence_class in {"REAL_SHADOW", "SYNTHETIC_SMOKE", "HISTORICAL_REPLAY", "INCOMPLETE"}, "unknown case evidence class")
        _require(self.status in {"COMPLETE", "INCOMPLETE"}, "unknown case status")
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(self.independent_new_source, "prospective case requires an independent source")
        _require(not self.model_input_gold_visible, "gold cannot be visible to the model")
        if self.label_digest is not None:
            _digest("label_digest", self.label_digest)
        if self.model_digest is not None:
            _digest("model_digest", self.model_digest)
        for name in ("quality", "quality_lcb", "quality_ucb"):
            value = getattr(self, name)
            if value is not None:
                _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")
        if self.quality_lcb is not None and self.quality_ucb is not None:
            _require(self.quality_lcb <= self.quality_ucb, "quality interval is inverted")
        for name in ("resident_params", "active_params"):
            value = getattr(self, name)
            if value is not None:
                _integer(name, value, minimum=1)
        if self.active_params is not None and self.resident_params is not None:
            _require(self.active_params <= self.resident_params, "active parameters exceed resident parameters")
        actual_missing = tuple(name for name in self._REQUIRED_COMPLETE_FIELDS if getattr(self, name) is None)
        _require(tuple(sorted(actual_missing)) == tuple(self.missing_fields), "case missing_fields are not exact")
        if self.status == "COMPLETE":
            _require(not actual_missing, "complete case has missing fields")
            _require(self.evidence_class == "REAL_SHADOW", "complete case must be real shadow evidence")
        if self.status == "INCOMPLETE":
            _require(bool(actual_missing), "incomplete case must identify missing fields")
        if self.resource is not None:
            _require(self.resource.candidate_id == self.candidate_id, "resource receipt candidate mismatch")
            _require(self.resource.budget_digest == self.budget_digest, "resource receipt budget mismatch")

    def to_dict(self) -> dict[str, Any]:
        result = {**asdict(self), "schema": "hepta.prospective.case.v1"}
        result["missing_fields"] = list(self.missing_fields)
        if self.resource is not None:
            result["resource"] = self.resource.to_dict()
        return result


@dataclass(frozen=True)
class ProspectiveEqualBudgetPlanV1:
    plan_id: str
    shared_stem_digest: str
    objective_digest: str
    budget: ResourceBudgetV1
    reader: ReaderDesignV1
    candidates: tuple[CandidateArmV1, ...]
    status: str = "SHADOW_ONLY"
    selection_authority: bool = False
    current_run_mutation: bool = False

    def __post_init__(self) -> None:
        _identifier("plan_id", self.plan_id)
        _digest("shared_stem_digest", self.shared_stem_digest)
        _digest("objective_digest", self.objective_digest)
        _require(self.status == "SHADOW_ONLY", "prospective plan cannot be promoted")
        _boolean("selection_authority", self.selection_authority)
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(not self.selection_authority, "prospective plan cannot select a production model")
        _require(not self.current_run_mutation, "prospective plan cannot mutate the current run")
        _require(len(self.candidates) >= len(REQUIRED_CANDIDATES), "required candidate arms are missing")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        _require(len(set(ids)) == len(ids), "candidate IDs must be unique")
        missing = sorted(set(REQUIRED_CANDIDATES) - set(ids))
        _require(not missing, f"required candidate arms missing: {missing}")
        gate_ids = {candidate.candidate_id for candidate in self.candidates if candidate.gate_eligible}
        _require({"shared_head", "split_head", "strong_cheap", "zero_feature_prior"} <= gate_ids, "minimum gate candidates are missing")
        for candidate in self.candidates:
            _require(candidate.budget_digest == self.budget.budget_digest, "candidate budget digest mismatch")
            if candidate.gate_eligible:
                _require(candidate.stem_digest == self.shared_stem_digest, "shared Stem arm has a different Stem digest")
                _require(candidate.objective_digest == self.objective_digest, "gate candidate objective digest mismatch")
            if candidate.candidate_id == "full_fork":
                _require(candidate.reference_only and not candidate.gate_eligible, "full fork must remain reference-only")
            if candidate.candidate_id == "no_change_teacher":
                _require(candidate.reference_only and not candidate.gate_eligible, "teacher must remain reference-only")
        rank_by_id = {candidate.candidate_id: candidate.adapter_rank for candidate in self.candidates}
        for identifier, rank in (("lora_r2", 2), ("lora_r4", 4), ("lora_r8", 8)):
            _require(rank_by_id[identifier] == rank, f"{identifier} has the wrong adapter rank")
        _require(self.budget.max_forward_calls >= self.reader.calls_per_candidate, "budget cannot cover the Reader design")

    @property
    def expected_calls(self) -> int:
        return len(self.candidates) * self.reader.calls_per_candidate

    def validate_resource_receipts(self, receipts: Iterable[ResourceReceiptV1]) -> None:
        """Fail closed until every candidate has a complete, bounded receipt."""
        items = tuple(receipts)
        by_id = {receipt.candidate_id: receipt for receipt in items}
        expected_ids = {candidate.candidate_id for candidate in self.candidates}
        _require(set(by_id) == expected_ids, "resource receipts must cover exactly the planned candidates")
        for receipt in items:
            _require(receipt.budget_digest == self.budget.budget_digest, "receipt budget digest mismatch")
            _require(receipt.evidence_class == "REAL_SHADOW", "synthetic or incomplete receipt cannot qualify the plan")
            _require(receipt.forward_calls == self.reader.calls_per_candidate, "candidate forward-call budget is not equal")
            _require(receipt.input_tokens is not None and receipt.input_tokens <= self.budget.max_input_tokens, "input-token budget exceeded")
            _require(receipt.flops is not None and receipt.flops <= self.budget.max_flops, "FLOPs budget exceeded")
            _require(receipt.peak_memory_bytes is not None and receipt.peak_memory_bytes <= self.budget.max_peak_memory_bytes, "memory budget exceeded")
            _require(receipt.p95_latency_ms is not None and receipt.p95_latency_ms <= self.budget.max_p95_latency_ms, "latency budget exceeded")
            _require(receipt.energy_mj is not None and receipt.energy_mj <= self.budget.max_energy_mj, "energy budget exceeded")

    def validate_cases(self, cases: Iterable[ProspectiveCaseV1]) -> None:
        """Check four-arm completeness and source separation before scoring."""
        items = tuple(cases)
        candidate_ids = {candidate.candidate_id for candidate in self.candidates}
        _require(items, "prospective case set cannot be empty")
        _require({case.candidate_id for case in items} == candidate_ids, "case set must cover exactly the planned candidates")
        _require(all(case.reader_manifest_digest == self.reader.manifest_sha256 for case in items), "Reader manifest mismatch")
        _require(all(case.budget_digest == self.budget.budget_digest for case in items), "case budget mismatch")
        _require(len(set((case.case_id for case in items))) == len(items), "case IDs must be unique")
        grouped: dict[tuple[str, str, str, int], list[ProspectiveCaseV1]] = {}
        for case in items:
            key = (case.candidate_id, case.task_id, case.source_split, case.replicate)
            grouped.setdefault(key, []).append(case)
        for group in grouped.values():
            _require(len(group) == len(READER_ARMS), "every candidate/task/replicate must have exactly four Reader cases")
            _require({case.reader_arm for case in group} == set(READER_ARMS), "every candidate/task/replicate must have one of each Reader arm")
            identities = {(case.source_digest, case.source_blob_digest, case.reader_manifest_digest, case.model_digest) for case in group}
            _require(len(identities) == 1, "four Reader arms must share source, manifest, and model identities")
        task_groups: dict[tuple[str, str, int], set[str]] = {}
        for case in items:
            task_groups.setdefault((case.candidate_id, case.source_split, case.replicate), set()).add(case.task_id)
        _require(all(len(task_ids) == self.reader.task_count for task_ids in task_groups.values()), "Reader task count is incomplete")
        _require({case.source_split for case in items} >= {"future", "ood"}, "future and OOD splits are both required")
        future_sources = {case.source_digest for case in items if case.source_split == "future"}
        ood_sources = {case.source_digest for case in items if case.source_split == "ood"}
        _require(not future_sources & ood_sources, "future and OOD source digests must not overlap")
        future_blobs = {case.source_blob_digest for case in items if case.source_split == "future"}
        ood_blobs = {case.source_blob_digest for case in items if case.source_split == "ood"}
        _require(not future_blobs & ood_blobs, "future and OOD source blobs must not overlap")
        for case in items:
            _require(case.request_digest != case.source_digest, "request digest must bind the full request, not only the source")
            _require(case.status == "COMPLETE" and case.evidence_class == "REAL_SHADOW", "incomplete, synthetic, or historical cases cannot enter the transfer matrix")
            _require(case.resource is not None and case.resource.evidence_class == "REAL_SHADOW", "only complete real shadow cases can be scored")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema": SCHEMA_PLAN,
            "plan_id": self.plan_id,
            "shared_stem_digest": self.shared_stem_digest,
            "objective_digest": self.objective_digest,
            "budget": self.budget.to_dict(),
            "reader": self.reader.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "status": self.status,
            "selection_authority": self.selection_authority,
            "current_run_mutation": self.current_run_mutation,
            "expected_calls": self.expected_calls,
        }
        return result


def build_system2_interval_gate(
    plan: ProspectiveEqualBudgetPlanV1,
    utility_intervals: Mapping[str, tuple[float, float]],
    resource_costs: Mapping[str, ResourceCostV1],
    evidence_digests: Mapping[str, str],
    evidence_classes: Mapping[str, str],
    cases: Iterable[ProspectiveCaseV1],
    *,
    feasible: Mapping[str, bool] | None = None,
    margin: float = 0.0,
) -> Any:
    """Build an advisory System2 gate over one validated gate-candidate set.

    The caller supplies intervals only after an independent real-shadow
    evaluator has produced them, and must provide the complete case matrix so
    this function can fail closed before constructing the advisory.  This
    adapter deliberately does not score a response, infer an interval, or
    certify efficacy.  The returned
    ``System2IntervalGateV1`` is advisory-only; its ``advisory()`` result is
    ``NO_GO`` on interval overlap and ``ADVISORY_SELECT`` only under strict
    interval dominance.  It never grants authority or mutates a running
    snapshot.
    """

    _require(plan.status == "SHADOW_ONLY", "System2 gate requires a shadow-only plan")
    _require(not plan.selection_authority and not plan.current_run_mutation, "System2 gate cannot carry runtime authority")
    _finite_nonnegative("margin", margin)
    case_items = tuple(cases)
    plan.validate_cases(case_items)
    receipt_by_id = {case.resource.candidate_id: case.resource for case in case_items if case.resource is not None}
    _require(len(receipt_by_id) == len(plan.candidates), "System2 gate needs one resource receipt per planned candidate")
    plan.validate_resource_receipts(tuple(receipt_by_id.values()))
    gate_candidates = tuple(candidate for candidate in plan.candidates if candidate.gate_eligible)
    gate_ids = {candidate.candidate_id for candidate in gate_candidates}
    _require(len(gate_candidates) >= 2, "System2 requires at least two gate candidates")
    _require(set(utility_intervals) == gate_ids, "utility intervals must cover exactly gate candidates")
    _require(set(resource_costs) == gate_ids, "resource costs must cover exactly gate candidates")
    _require(set(evidence_digests) == gate_ids, "evidence digests must cover exactly gate candidates")
    _require(set(evidence_classes) == gate_ids, "evidence classes must cover exactly gate candidates")
    if feasible is None:
        feasible = {candidate_id: True for candidate_id in gate_ids}
    _require(set(feasible) == gate_ids, "feasibility flags must cover exactly gate candidates")

    candidates = []
    for candidate in gate_candidates:
        interval = utility_intervals[candidate.candidate_id]
        _require(isinstance(interval, tuple) and len(interval) == 2, "utility interval must be a pair")
        lower, upper = interval
        _require(type(lower) in (int, float) and type(upper) in (int, float), "utility interval values must be numeric")
        _require(math.isfinite(float(lower)) and math.isfinite(float(upper)), "utility interval values must be finite")
        _require(float(lower) <= float(upper), "utility interval is inverted")
        evidence_digest = evidence_digests[candidate.candidate_id]
        _digest("evidence_digest", evidence_digest)
        _require(evidence_classes[candidate.candidate_id] == "REAL_SHADOW", "System2 gate cannot consume synthetic or incomplete evidence")
        _boolean("feasible", feasible[candidate.candidate_id])
        try:
            candidates.append(
                System2CandidateV1(
                    candidate_id=candidate.candidate_id,
                    stem_digest=candidate.stem_digest,
                    objective_digest=candidate.objective_digest,
                    utility_lcb=float(lower),
                    utility_ucb=float(upper),
                    cost=resource_costs[candidate.candidate_id],
                    evidence_digest=evidence_digest,
                    feasible=feasible[candidate.candidate_id],
                    authority="DENY_ALL",
                    model_efficacy_measured=False,
                )
            )
        except Exception as exc:
            raise ProspectivePlanError("invalid System2 candidate interval or cost") from exc
    try:
        return System2IntervalGateV1(tuple(candidates), margin=float(margin))
    except Exception as exc:
        raise ProspectivePlanError("invalid System2 interval gate") from exc

__all__ = [
    "CandidateArmV1",
    "build_system2_interval_gate",
    "ProspectiveEqualBudgetPlanV1",
    "ProspectiveCaseV1",
    "ProspectivePlanError",
    "READER_ARMS",
    "REQUIRED_CANDIDATES",
    "ReaderDesignV1",
    "ResourceBudgetV1",
    "ResourceCostV1",
    "ResourceReceiptV1",
    "SCHEMA_PLAN",
    "reader_request_digest",
]
