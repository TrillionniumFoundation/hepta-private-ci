"""Research-only real-checkpoint qualification receipt contracts.

This module closes the evidence boundary between a Stem manifest and a real
shadow run. It composes checkpoint identity, source-disjoint split identity,
confidence intervals and componentized measured resources. It never loads a
checkpoint, chooses a model, mutates runtime state, or grants production
authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any


SCHEMA_CHECKPOINT = "hepta.stem.checkpoint-ref.v1"
SCHEMA_SPLIT = "hepta.stem.source-disjoint-split.v1"
SCHEMA_METRIC = "hepta.stem.metric-interval.v1"
SCHEMA_RESOURCE = "hepta.stem.component-resource-receipt.v1"
SCHEMA_RUN = "hepta.stem.qualification-run.v1"
SCHEMA_RECEIPT = SCHEMA_RUN
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_REQUIRED_COMPONENTS = {
    "encoder_only": {"stem_encoder", "modality_tower", "projector", "cell_head", "device"},
    "encoder_decoder": {"stem_encoder", "modality_tower", "projector", "cell_head", "controller_decoder", "device"},
    "full_generation": {"stem_encoder", "modality_tower", "projector", "cell_head", "controller_decoder", "state_cache", "verification", "device"},
}


class StemQualificationError(ValueError):
    """Raised when a real Stem qualification receipt is incomplete or invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StemQualificationError(message)


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _integer(name: str, value: Any, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{name} must be a non-negative integer")


def _finite(name: str, value: float, *, minimum: float = 0.0) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)) and float(value) >= minimum, f"{name} must be finite and non-negative")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be boolean")


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest_object(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckpointRefV1:
    model_id: str
    model_manifest_digest: str
    weights_digest: str
    tokenizer_digest: str
    preprocessor_digest: str
    backend_id: str
    runtime_digest: str
    device_identity_digest: str
    checkpoint_digest: str
    quantization_digest: str
    stem_digest: str
    parameter_count: int
    generation: int
    quantization_id: str
    source_bound: bool = True
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        for name, value in (("model_id", self.model_id), ("backend_id", self.backend_id), ("quantization_id", self.quantization_id)):
            _identifier(name, value)
        for name, value in (
            ("model_manifest_digest", self.model_manifest_digest),
            ("weights_digest", self.weights_digest),
            ("tokenizer_digest", self.tokenizer_digest),
            ("preprocessor_digest", self.preprocessor_digest),
            ("runtime_digest", self.runtime_digest),
            ("device_identity_digest", self.device_identity_digest),
            ("checkpoint_digest", self.checkpoint_digest),
            ("quantization_digest", self.quantization_digest),
            ("stem_digest", self.stem_digest),
        ):
            _digest(name, value)
        _integer("parameter_count", self.parameter_count, minimum=1)
        _integer("generation", self.generation)
        _boolean("source_bound", self.source_bound)
        _require(self.source_bound, "checkpoint must be source-bound")
        _require(self.authority == "DENY_ALL", "checkpoint identity cannot carry authority")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_CHECKPOINT}


@dataclass(frozen=True)
class SourceDisjointSplitV1:
    train_source_digest: str
    eval_source_digest: str
    train_manifest_digest: str
    eval_manifest_digest: str
    future_source_digest: str
    ood_source_digest: str
    future_manifest_digest: str
    ood_manifest_digest: str
    split_manifest_digest: str
    lineage_digest: str
    dedupe_report_digest: str
    train_count: int
    eval_count: int
    overlap_count: int
    source_family_count: int
    future_window_count: int
    independent_new_source: bool = True
    policy: str = "independent_new_source_required"

    def __post_init__(self) -> None:
        for name, value in (
            ("train_source_digest", self.train_source_digest),
            ("eval_source_digest", self.eval_source_digest),
            ("train_manifest_digest", self.train_manifest_digest),
            ("eval_manifest_digest", self.eval_manifest_digest),
            ("future_source_digest", self.future_source_digest),
            ("ood_source_digest", self.ood_source_digest),
            ("future_manifest_digest", self.future_manifest_digest),
            ("ood_manifest_digest", self.ood_manifest_digest),
            ("split_manifest_digest", self.split_manifest_digest),
            ("lineage_digest", self.lineage_digest),
            ("dedupe_report_digest", self.dedupe_report_digest),
        ):
            _digest(name, value)
        source_digests = {self.train_source_digest, self.eval_source_digest, self.future_source_digest, self.ood_source_digest}
        _require(len(source_digests) == 4, "train/eval/future/ood sources must be disjoint")
        for name, value in (("train_count", self.train_count), ("eval_count", self.eval_count), ("source_family_count", self.source_family_count), ("future_window_count", self.future_window_count)):
            _integer(name, value, minimum=1)
        _integer("overlap_count", self.overlap_count, minimum=0)
        _require(self.overlap_count == 0, "source-disjoint split contains overlap")
        _boolean("independent_new_source", self.independent_new_source)
        _require(self.independent_new_source, "qualification requires an independent new source")
        _require(self.policy == "independent_new_source_required", "unsupported split policy")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_SPLIT}


@dataclass(frozen=True)
class MetricIntervalV1:
    metric_id: str
    value: float
    lcb: float
    ucb: float
    sample_count: int
    confidence_level: float
    evaluator_digest: str
    heldout_source_digest: str

    def __post_init__(self) -> None:
        _identifier("metric_id", self.metric_id)
        for name, value in (("value", self.value), ("lcb", self.lcb), ("ucb", self.ucb)):
            _finite(name, value)
        _require(self.lcb <= self.value <= self.ucb, "metric interval must contain its value")
        _integer("sample_count", self.sample_count, minimum=1)
        _finite("confidence_level", self.confidence_level)
        _require(0.0 < self.confidence_level <= 1.0, "confidence_level must be in (0, 1]")
        _digest("evaluator_digest", self.evaluator_digest)
        _digest("heldout_source_digest", self.heldout_source_digest)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_METRIC}


@dataclass(frozen=True)
class ComponentResourceReceiptV1:
    component_id: str
    component_kind: str
    artifact_digest: str
    measurement_digest: str
    forward_calls: int
    input_tokens: int
    flops: float
    peak_memory_bytes: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    energy_mj: float
    parameter_count: int
    evidence_class: str = "REAL_SHADOW"
    complete: bool = True

    def __post_init__(self) -> None:
        _identifier("component_id", self.component_id)
        _require(self.component_kind in {
            "stem_encoder",
            "modality_tower",
            "projector",
            "cell_head",
            "controller_decoder",
            "state_cache",
            "verification",
            "device",
        }, "unsupported resource component kind")
        _digest("artifact_digest", self.artifact_digest)
        _digest("measurement_digest", self.measurement_digest)
        is_device = self.component_kind == "device"
        for name, value in (
            ("forward_calls", self.forward_calls),
            ("input_tokens", self.input_tokens),
            ("parameter_count", self.parameter_count),
        ):
            _integer(name, value, minimum=0 if is_device else 1)
        for name, value in (
            ("flops", self.flops),
            ("peak_memory_bytes", self.peak_memory_bytes),
            ("p50_latency_ms", self.p50_latency_ms),
            ("p95_latency_ms", self.p95_latency_ms),
            ("p99_latency_ms", self.p99_latency_ms),
            ("energy_mj", self.energy_mj),
        ):
            _finite(name, value)
        _require(self.p50_latency_ms <= self.p95_latency_ms <= self.p99_latency_ms, "component latency quantiles must be ordered")
        _require(self.peak_memory_bytes > 0 and self.p95_latency_ms > 0 and self.energy_mj > 0, "component resources must be positive")
        _require(is_device or self.flops > 0, "model component FLOPs must be positive")
        _require(self.evidence_class == "REAL_SHADOW", "only REAL_SHADOW components can qualify")
        _boolean("complete", self.complete)
        _require(self.complete, "incomplete component receipts cannot qualify")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": "hepta.stem.component-resource.v1"}


@dataclass(frozen=True)
class ComponentResourceBundleV1:
    bundle_id: str
    benchmark_id: str
    hardware_digest: str
    runtime_digest: str
    measurement_digest: str
    components: tuple[ComponentResourceReceiptV1, ...]
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    energy_mj: float
    batch_size: int
    warmup_steps: int
    measured_steps: int
    repetitions: int
    cache_hit_rate: float
    component_profile: str = "full_generation"
    complete: bool = True

    def __post_init__(self) -> None:
        _identifier("bundle_id", self.bundle_id)
        _identifier("benchmark_id", self.benchmark_id)
        for name, value in (("hardware_digest", self.hardware_digest), ("runtime_digest", self.runtime_digest), ("measurement_digest", self.measurement_digest)):
            _digest(name, value)
        _require(self.component_profile in _REQUIRED_COMPONENTS, "unsupported component profile")
        _require(type(self.components) is tuple and self.components, "components must be a non-empty tuple")
        _require(all(isinstance(component, ComponentResourceReceiptV1) for component in self.components), "invalid resource component")
        required = _REQUIRED_COMPONENTS[self.component_profile]
        _require({component.component_kind for component in self.components} == required, "resource bundle must cover every component kind exactly")
        _require(len(self.components) == len(required), "resource component kinds must be unique")
        _require(self.components == tuple(sorted(self.components, key=lambda component: component.component_kind)), "components must be sorted by kind")
        for name, value in (
            ("p50_latency_ms", self.p50_latency_ms),
            ("p95_latency_ms", self.p95_latency_ms),
            ("p99_latency_ms", self.p99_latency_ms),
            ("energy_mj", self.energy_mj),
            ("cache_hit_rate", self.cache_hit_rate),
        ):
            _finite(name, value)
        _require(self.p50_latency_ms <= self.p95_latency_ms <= self.p99_latency_ms, "bundle latency quantiles must be ordered")
        _require(self.p95_latency_ms > 0 and self.energy_mj > 0, "bundle resources must be positive")
        _require(0.0 <= self.cache_hit_rate <= 1.0, "cache_hit_rate must be in [0, 1]")
        for name, value in (("batch_size", self.batch_size), ("warmup_steps", self.warmup_steps), ("measured_steps", self.measured_steps), ("repetitions", self.repetitions)):
            _integer(name, value, minimum=1)
        _boolean("complete", self.complete)
        _require(self.complete, "incomplete resource bundles cannot qualify")

    @property
    def total_flops(self) -> float:
        return sum(component.flops for component in self.components)

    @property
    def peak_component_memory_bytes(self) -> float:
        return max(component.peak_memory_bytes for component in self.components)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RESOURCE,
            "bundle_id": self.bundle_id,
            "benchmark_id": self.benchmark_id,
            "hardware_digest": self.hardware_digest,
            "runtime_digest": self.runtime_digest,
            "measurement_digest": self.measurement_digest,
            "components": [component.to_dict() for component in self.components],
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "energy_mj": self.energy_mj,
            "batch_size": self.batch_size,
            "warmup_steps": self.warmup_steps,
            "measured_steps": self.measured_steps,
            "repetitions": self.repetitions,
            "cache_hit_rate": self.cache_hit_rate,
            "component_profile": self.component_profile,
            "complete": self.complete,
            "total_flops": self.total_flops,
            "peak_component_memory_bytes": self.peak_component_memory_bytes,
        }


@dataclass(frozen=True)
class StemQualificationRunV1:
    run_id: str
    candidate_id: str
    stem_digest: str
    stem_generation: int
    checkpoint: CheckpointRefV1
    source_split: SourceDisjointSplitV1
    registry_stem_digest: str
    registry_generation: int
    tower_registry_digest: str
    projector_registry_digest: str
    objective_digest: str
    evaluation_plan_digest: str
    cases_digest: str
    budget_digest: str
    cost_profile_digest: str
    evidence_manifest_digest: str
    metrics: tuple[MetricIntervalV1, ...]
    resources: ComponentResourceBundleV1
    evidence_class: str = "REAL_SHADOW"
    status: str = "SHADOW_COMPLETE"
    model_input_gold_visible: bool = False
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        _identifier("run_id", self.run_id)
        _identifier("candidate_id", self.candidate_id)
        _digest("stem_digest", self.stem_digest)
        _integer("stem_generation", self.stem_generation)
        _require(self.stem_digest == self.checkpoint.stem_digest, "run Stem digest differs from checkpoint")
        _require(self.stem_generation == self.checkpoint.generation, "run generation differs from checkpoint")
        _digest("registry_stem_digest", self.registry_stem_digest)
        _integer("registry_generation", self.registry_generation)
        _require(self.registry_stem_digest == self.stem_digest, "registry Stem digest differs from run")
        _require(self.registry_generation == self.checkpoint.generation, "registry generation differs from checkpoint")
        _digest("tower_registry_digest", self.tower_registry_digest)
        _digest("projector_registry_digest", self.projector_registry_digest)
        _digest("objective_digest", self.objective_digest)
        _digest("evaluation_plan_digest", self.evaluation_plan_digest)
        _digest("cases_digest", self.cases_digest)
        _digest("budget_digest", self.budget_digest)
        _digest("cost_profile_digest", self.cost_profile_digest)
        _digest("evidence_manifest_digest", self.evidence_manifest_digest)
        _require(self.evidence_class == "REAL_SHADOW", "only REAL_SHADOW runs can qualify")
        _require(self.status == "SHADOW_COMPLETE", "run is not complete")
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(not self.model_input_gold_visible, "gold cannot be visible to the model")
        _require(self.authority == "DENY_ALL", "qualification run cannot carry authority")
        _require(type(self.metrics) is tuple and self.metrics, "metrics must be a non-empty tuple")
        _require(len({metric.metric_id for metric in self.metrics}) == len(self.metrics), "metric IDs must be unique")
        _require(self.metrics == tuple(sorted(self.metrics, key=lambda metric: metric.metric_id)), "metrics must be sorted by ID")
        for metric in self.metrics:
            _require(metric.heldout_source_digest == self.source_split.eval_source_digest, "metric source differs from split")
            _require(metric.sample_count <= self.source_split.eval_count, "metric sample count exceeds evaluation cohort")
        _require(self.resources.runtime_digest == self.checkpoint.runtime_digest, "resource runtime differs from checkpoint runtime")
        _require(self.resources.hardware_digest == self.checkpoint.device_identity_digest, "resource hardware differs from checkpoint device")

    @property
    def run_digest(self) -> str:
        return _digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RUN,
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "stem_digest": self.stem_digest,
            "stem_generation": self.stem_generation,
            "checkpoint": self.checkpoint.to_dict(),
            "source_split": self.source_split.to_dict(),
            "registry_stem_digest": self.registry_stem_digest,
            "registry_generation": self.registry_generation,
            "tower_registry_digest": self.tower_registry_digest,
            "projector_registry_digest": self.projector_registry_digest,
            "objective_digest": self.objective_digest,
            "evaluation_plan_digest": self.evaluation_plan_digest,
            "cases_digest": self.cases_digest,
            "budget_digest": self.budget_digest,
            "cost_profile_digest": self.cost_profile_digest,
            "evidence_manifest_digest": self.evidence_manifest_digest,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "resources": self.resources.to_dict(),
            "evidence_class": self.evidence_class,
            "status": self.status,
            "model_input_gold_visible": self.model_input_gold_visible,
            "authority": self.authority,
        }


def qualify_from_receipt(
    receipt: Any,
    *,
    run_id: str,
    candidate_id: str,
    task_id: str,
    expected_budget_digest: str,
    expected_cases_digest: str,
    expected_cost_profile_digest: str,
    checkpoint: CheckpointRefV1,
    source_split: SourceDisjointSplitV1,
    registry_stem_digest: str,
    registry_generation: int,
    tower_registry_digest: str,
    projector_registry_digest: str,
    objective_digest: str,
    evaluation_plan_digest: str,
    cases_digest: str,
    budget_digest: str,
    cost_profile_digest: str,
    evidence_manifest_digest: str,
    metrics: tuple[MetricIntervalV1, ...],
    resources: ComponentResourceBundleV1,
) -> StemQualificationRunV1:
    """Upgrade a complete REAL_SHADOW bridge receipt into a full run.

    Point-only, synthetic, historical or incomplete bridge receipts are
    deliberately rejected; they cannot be silently promoted by filling missing
    intervals or runtime measurements.
    """

    _require(getattr(receipt, "receipt_status", None) == "COMPLETE", "bridge receipt is incomplete")
    _require(getattr(receipt, "evidence_class", None) == "REAL_SHADOW", "bridge receipt is not REAL_SHADOW")
    _require(getattr(receipt, "independent_new_source", False), "bridge receipt lacks independent source")
    _require(not getattr(receipt, "model_input_gold_visible", True), "bridge receipt exposes model-visible gold")
    _require(getattr(receipt, "stem_digest", None) == checkpoint.stem_digest, "bridge receipt Stem mismatch")
    _require(getattr(receipt, "source_digest", None) == source_split.eval_source_digest, "bridge receipt source mismatch")
    _require(getattr(receipt, "task_id", None) == task_id, "bridge receipt task mismatch")
    _require(getattr(receipt, "budget_digest", None) == expected_budget_digest, "bridge receipt budget mismatch")
    _require(getattr(receipt, "model_digest", None) == checkpoint.checkpoint_digest, "bridge receipt model identity is missing or mismatched")
    _identifier("candidate_id", candidate_id)
    _digest("expected_budget_digest", expected_budget_digest)
    _digest("expected_cases_digest", expected_cases_digest)
    _digest("expected_cost_profile_digest", expected_cost_profile_digest)
    _require(cases_digest == expected_cases_digest, "cases digest does not match expected plan")
    _require(cost_profile_digest == expected_cost_profile_digest, "cost profile digest does not match expected plan")
    return StemQualificationRunV1(
        run_id=run_id,
        candidate_id=candidate_id,
        stem_digest=checkpoint.stem_digest,
        stem_generation=checkpoint.generation,
        checkpoint=checkpoint,
        source_split=source_split,
        registry_stem_digest=registry_stem_digest,
        registry_generation=registry_generation,
        tower_registry_digest=tower_registry_digest,
        projector_registry_digest=projector_registry_digest,
        objective_digest=objective_digest,
        evaluation_plan_digest=evaluation_plan_digest,
        cases_digest=cases_digest,
        evidence_manifest_digest=evidence_manifest_digest,
        metrics=metrics,
        resources=resources,
    )


__all__ = [
    "CheckpointRefV1",
    "ComponentResourceBundleV1",
    "ComponentResourceReceiptV1",
    "MetricIntervalV1",
    "SCHEMA_CHECKPOINT",
    "SCHEMA_METRIC",
    "SCHEMA_RECEIPT",
    "SCHEMA_RESOURCE",
    "SCHEMA_RUN",
    "SCHEMA_SPLIT",
    "SourceDisjointSplitV1",
    "StemQualificationError",
    "StemQualificationRunV1",
    "qualify_from_receipt",
]
