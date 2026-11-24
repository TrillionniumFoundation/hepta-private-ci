"""Shadow-only Stem bakeoff receipts and deterministic Pareto selection.

This module records measurements; it does not load a model, select a runtime,
or grant execution authority. A production evaluator must supply receipts from
the target host and preserve the exact benchmark and runtime digests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from cell_fast_path_actionir import canonical_digest


ZERO = "0" * 64
STATUSES = frozenset(("succeeded", "failed", "cancelled", "indeterminate"))


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value


def _bounded(value: int, field: str, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > upper:
        raise ValueError(f"{field} must be an integer in [0, {upper}]")
    return value


def _positive(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True)
class StemEvaluationReceiptV1:
    candidate_id: str
    stem_digest: str
    hidden_abi_digest: str
    benchmark_digest: str
    runtime_digest: str
    modalities: Tuple[str, ...]
    parameter_count: int
    weight_bytes: int
    quality_lcb_milli: int
    calibration_error_ppm: int
    ood_coverage_ppm: int
    latency_p95_ns: int
    latency_p99_ns: int
    observed_memory_bytes: int
    energy_nj: int
    deterministic: bool
    adapter_hooks: bool
    status: str
    receipt_digest: str
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        if not self.candidate_id or not isinstance(self.candidate_id, str):
            raise ValueError("candidate_id must be non-empty")
        for name in ("stem_digest", "hidden_abi_digest", "benchmark_digest", "runtime_digest", "receipt_digest"):
            _digest(getattr(self, name), name)
        if not self.modalities or tuple(sorted(set(self.modalities))) != self.modalities:
            raise ValueError("modalities must be a sorted non-empty tuple")
        if any(not isinstance(item, str) or not item for item in self.modalities):
            raise ValueError("modalities must contain non-empty strings")
        _positive(self.parameter_count, "parameter_count")
        _positive(self.weight_bytes, "weight_bytes")
        _bounded(self.quality_lcb_milli, "quality_lcb_milli", 1_000_000)
        _bounded(self.calibration_error_ppm, "calibration_error_ppm", 1_000_000)
        _bounded(self.ood_coverage_ppm, "ood_coverage_ppm", 1_000_000)
        if not isinstance(self.deterministic, bool) or not isinstance(self.adapter_hooks, bool):
            raise ValueError("deterministic and adapter_hooks must be booleans")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status}")
        if self.authority != "DENY_ALL":
            raise ValueError("Stem evaluation receipts cannot carry authority")
        metrics = (
            self.quality_lcb_milli,
            self.calibration_error_ppm,
            self.ood_coverage_ppm,
            self.latency_p95_ns,
            self.latency_p99_ns,
            self.observed_memory_bytes,
            self.energy_nj,
        )
        if self.status == "succeeded":
            _positive(self.latency_p95_ns, "latency_p95_ns")
            _positive(self.latency_p99_ns, "latency_p99_ns")
            _positive(self.observed_memory_bytes, "observed_memory_bytes")
            _positive(self.energy_nj, "energy_nj")
            if self.latency_p99_ns < self.latency_p95_ns:
                raise ValueError("latency_p99_ns must be >= latency_p95_ns")
        elif any(value != 0 for value in metrics):
            raise ValueError("non-succeeded receipts cannot carry evaluation metrics")


@dataclass(frozen=True)
class StemBakeoffPolicyV1:
    benchmark_digest: str
    required_modalities: Tuple[str, ...]
    min_quality_lcb_milli: int
    max_calibration_error_ppm: int
    min_ood_coverage_ppm: int
    max_latency_p95_ns: int
    max_latency_p99_ns: int
    max_memory_bytes: int
    max_energy_nj: int
    require_deterministic: bool = True
    require_adapter_hooks: bool = True

    def __post_init__(self) -> None:
        _digest(self.benchmark_digest, "benchmark_digest")
        if tuple(sorted(set(self.required_modalities))) != self.required_modalities:
            raise ValueError("required_modalities must be sorted and unique")
        if not self.required_modalities:
            raise ValueError("required_modalities must not be empty")
        _bounded(self.min_quality_lcb_milli, "min_quality_lcb_milli", 1_000_000)
        _bounded(self.max_calibration_error_ppm, "max_calibration_error_ppm", 1_000_000)
        _bounded(self.min_ood_coverage_ppm, "min_ood_coverage_ppm", 1_000_000)
        _positive(self.max_latency_p95_ns, "max_latency_p95_ns")
        _positive(self.max_latency_p99_ns, "max_latency_p99_ns")
        _positive(self.max_memory_bytes, "max_memory_bytes")
        _positive(self.max_energy_nj, "max_energy_nj")
        if self.max_latency_p99_ns < self.max_latency_p95_ns:
            raise ValueError("max_latency_p99_ns must be >= max_latency_p95_ns")


@dataclass(frozen=True)
class StemBakeoffDecisionV1:
    benchmark_digest: str
    receipt_digests: Tuple[str, ...]
    eligible_candidate_ids: Tuple[str, ...]
    pareto_candidate_ids: Tuple[str, ...]
    selected_candidate_id: Optional[str]
    reason_codes: Tuple[str, ...]
    decision_digest: str
    authority: str = "DENY_ALL"
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        _digest(self.benchmark_digest, "benchmark_digest")
        for digest in self.receipt_digests:
            _digest(digest, "receipt_digest")
        _digest(self.decision_digest, "decision_digest")
        if tuple(sorted(set(self.receipt_digests))) != self.receipt_digests:
            raise ValueError("receipt_digests must be sorted and unique")
        if tuple(sorted(set(self.eligible_candidate_ids))) != self.eligible_candidate_ids:
            raise ValueError("eligible_candidate_ids must be sorted and unique")
        if tuple(sorted(set(self.pareto_candidate_ids))) != self.pareto_candidate_ids:
            raise ValueError("pareto_candidate_ids must be sorted and unique")
        if self.selected_candidate_id is not None and self.selected_candidate_id not in self.pareto_candidate_ids:
            raise ValueError("selected candidate must be on the Pareto frontier")
        if self.authority != "DENY_ALL" or self.effect_admitted:
            raise ValueError("bakeoff decisions cannot carry authority or effects")


def _eligible(receipt: StemEvaluationReceiptV1, policy: StemBakeoffPolicyV1) -> bool:
    return (
        receipt.status == "succeeded"
        and receipt.benchmark_digest == policy.benchmark_digest
        and set(policy.required_modalities).issubset(receipt.modalities)
        and receipt.quality_lcb_milli >= policy.min_quality_lcb_milli
        and receipt.calibration_error_ppm <= policy.max_calibration_error_ppm
        and receipt.ood_coverage_ppm >= policy.min_ood_coverage_ppm
        and receipt.latency_p95_ns <= policy.max_latency_p95_ns
        and receipt.latency_p99_ns <= policy.max_latency_p99_ns
        and receipt.observed_memory_bytes <= policy.max_memory_bytes
        and receipt.energy_nj <= policy.max_energy_nj
        and (not policy.require_deterministic or receipt.deterministic)
        and (not policy.require_adapter_hooks or receipt.adapter_hooks)
    )


def _dominates(left: StemEvaluationReceiptV1, right: StemEvaluationReceiptV1) -> bool:
    better_or_equal = (
        left.quality_lcb_milli >= right.quality_lcb_milli
        and left.ood_coverage_ppm >= right.ood_coverage_ppm
        and left.calibration_error_ppm <= right.calibration_error_ppm
        and left.latency_p99_ns <= right.latency_p99_ns
        and left.observed_memory_bytes <= right.observed_memory_bytes
        and left.energy_nj <= right.energy_nj
    )
    strictly_better = (
        left.quality_lcb_milli > right.quality_lcb_milli
        or left.ood_coverage_ppm > right.ood_coverage_ppm
        or left.calibration_error_ppm < right.calibration_error_ppm
        or left.latency_p99_ns < right.latency_p99_ns
        or left.observed_memory_bytes < right.observed_memory_bytes
        or left.energy_nj < right.energy_nj
    )
    return better_or_equal and strictly_better


def select_stem_bakeoff(receipts: Iterable[StemEvaluationReceiptV1], policy: StemBakeoffPolicyV1) -> StemBakeoffDecisionV1:
    values = tuple(receipts)
    if not values:
        raise ValueError("at least one receipt is required")
    if len({item.candidate_id for item in values}) != len(values):
        raise ValueError("candidate_id values must be unique")
    receipt_digests = tuple(sorted(item.receipt_digest for item in values))
    eligible = tuple(sorted((item for item in values if _eligible(item, policy)), key=lambda item: item.candidate_id))
    pareto = tuple(item for item in eligible if not any(_dominates(other, item) for other in eligible if other != item))
    pareto_ids = tuple(sorted(item.candidate_id for item in pareto))
    selected: Optional[StemEvaluationReceiptV1] = None
    if pareto:
        selected = sorted(
            pareto,
            key=lambda item: (
                -item.quality_lcb_milli,
                -item.ood_coverage_ppm,
                item.calibration_error_ppm,
                item.latency_p99_ns,
                item.observed_memory_bytes,
                item.energy_nj,
                item.candidate_id,
            ),
        )[0]
    reason_codes = ("SELECTED_PARETO_CANDIDATE",) if selected else ("NO_ELIGIBLE_STEM",)
    payload: Mapping[str, object] = {
        "schema": "hepta.stem-bakeoff-decision.v1",
        "benchmark_digest": policy.benchmark_digest,
        "receipt_digests": receipt_digests,
        "eligible_candidate_ids": tuple(item.candidate_id for item in eligible),
        "pareto_candidate_ids": pareto_ids,
        "selected_candidate_id": selected.candidate_id if selected else None,
        "reason_codes": reason_codes,
        "authority": "DENY_ALL",
        "effect_admitted": False,
    }
    return StemBakeoffDecisionV1(
        benchmark_digest=policy.benchmark_digest,
        receipt_digests=receipt_digests,
        eligible_candidate_ids=tuple(item.candidate_id for item in eligible),
        pareto_candidate_ids=pareto_ids,
        selected_candidate_id=selected.candidate_id if selected else None,
        reason_codes=reason_codes,
        decision_digest=canonical_digest(payload),
    )
