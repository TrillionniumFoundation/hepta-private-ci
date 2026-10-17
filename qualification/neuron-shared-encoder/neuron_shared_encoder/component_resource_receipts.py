"""Componentized resource receipts for the shared Stem transfer gate.

This is a research-only accounting boundary.  It records the dimensions that
an end-to-end receipt must charge separately (encoder, modality tower,
projector, decoder, Cell, controller, state, cache and verifier) and binds
those charges to a device/runtime identity and to the same checkpoint and
Reader source identities as the prospective transfer plan.

The raw receipt deliberately keeps its component fields.  The compatibility
adapter to ``ResourceCostV1`` is a fixed projection because that older
contract has only encoder/Cell/controller/verification buckets.  The scalar
``ResourceCostV1.total_units`` remains an experiment-local accounting unit;
it is never presented as a physical equivalence between FLOPs, bytes,
milliseconds or energy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping


SCHEMA_COMPONENT = "hepta.prospective.component-usage.v1"
SCHEMA_DEVICE = "hepta.prospective.device-receipt.v1"
SCHEMA_RECEIPT = "hepta.prospective.component-resource-receipt.v1"
AGGREGATION_POLICY = "fixed_component_projection_v1"

REAL_SHADOW = "REAL_SHADOW"
REAL_MODEL_LOCAL_QUALIFICATION = "REAL_MODEL_LOCAL_QUALIFICATION"
SYNTHETIC_SMOKE = "SYNTHETIC_SMOKE"
HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
INCOMPLETE = "INCOMPLETE"

COMPONENTS = (
    "encoder",
    "tower",
    "projector",
    "decoder",
    "cell",
    "controller",
    "state",
    "cache",
    "verifier",
)
_REAL_EVIDENCE = {REAL_SHADOW, REAL_MODEL_LOCAL_QUALIFICATION}
_ALL_EVIDENCE = {
    REAL_SHADOW,
    REAL_MODEL_LOCAL_QUALIFICATION,
    SYNTHETIC_SMOKE,
    HISTORICAL_REPLAY,
    INCOMPLETE,
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class ComponentReceiptError(ValueError):
    """Raised when a componentized receipt cannot be safely audited."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ComponentReceiptError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, f"{name} must be a lowercase sha256")


def _blob(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX40.fullmatch(value) is not None, f"{name} must be a lowercase Git SHA-1")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and _IDENT.fullmatch(value) is not None, f"{name} is not a stable identifier")


def _integer(name: str, value: Any, *, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")


def _finite_nonnegative(name: str, value: Any) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)) and float(value) >= 0.0, f"{name} must be finite and non-negative")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ComponentUsageV1:
    """One charged component and its native resource dimensions."""

    component: str
    component_digest: str
    device_digest: str
    forward_calls: int
    input_tokens: int
    flops: float
    peak_memory_bytes: float
    p95_latency_ms: float
    energy_mj: float
    resident_params: int
    active_params: int

    def __post_init__(self) -> None:
        _require(self.component in COMPONENTS, "unknown receipt component")
        _digest("component_digest", self.component_digest)
        _digest("device_digest", self.device_digest)
        for name in ("forward_calls", "input_tokens", "resident_params", "active_params"):
            _integer(name, getattr(self, name))
        _require(self.active_params <= self.resident_params, "active component parameters exceed resident parameters")
        for name in ("flops", "peak_memory_bytes", "p95_latency_ms", "energy_mj"):
            _finite_nonnegative(name, getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_COMPONENT}


@dataclass(frozen=True)
class DeviceReceiptV1:
    """Measured device/runtime envelope for all component charges."""

    device_id: str
    device_digest: str
    runtime_digest: str
    device_kind: str
    precision: str
    device_count: int
    peak_memory_bytes: float
    energy_mj: float

    def __post_init__(self) -> None:
        _identifier("device_id", self.device_id)
        _digest("device_digest", self.device_digest)
        _digest("runtime_digest", self.runtime_digest)
        _require(isinstance(self.device_kind, str) and self.device_kind, "device_kind is required")
        _require(isinstance(self.precision, str) and self.precision, "precision is required")
        _integer("device_count", self.device_count, minimum=1)
        _finite_nonnegative("peak_memory_bytes", self.peak_memory_bytes)
        _finite_nonnegative("energy_mj", self.energy_mj)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_DEVICE}


@dataclass(frozen=True)
class ComponentResourceReceiptV1:
    """Complete or explicitly incomplete end-to-end component receipt.

    ``evidence_class`` is preserved exactly from the harness.  In particular,
    ``REAL_MODEL_LOCAL_QUALIFICATION`` is not silently renamed to
    ``REAL_SHADOW``.  Only a receipt already labelled ``REAL_SHADOW`` can be
    adapted to the prospective plan's strict shadow gate.
    """

    receipt_id: str
    candidate_id: str
    budget_digest: str
    cost_weights_digest: str
    evidence_class: str
    model_digest: str | None
    tokenizer_digest: str | None
    preprocessor_digest: str | None
    runtime_digest: str | None
    source_digest: str | None
    source_blob_digest: str | None
    reader_forward_calls: int | None
    charged_input_tokens: int | None
    components: tuple[ComponentUsageV1, ...] | None
    device: DeviceReceiptV1 | None
    independent_new_source: bool
    model_input_gold_visible: bool = False
    status: str = "COMPLETE"
    missing_fields: tuple[str, ...] = ()

    _DIGEST_FIELDS = (
        "model_digest",
        "tokenizer_digest",
        "preprocessor_digest",
        "runtime_digest",
        "source_digest",
        "source_blob_digest",
    )

    def __post_init__(self) -> None:
        _identifier("receipt_id", self.receipt_id)
        _identifier("candidate_id", self.candidate_id)
        _digest("budget_digest", self.budget_digest)
        _digest("cost_weights_digest", self.cost_weights_digest)
        _require(self.evidence_class in _ALL_EVIDENCE, "unknown resource evidence class")
        _require(self.status in {"COMPLETE", "INCOMPLETE"}, "status must be COMPLETE or INCOMPLETE")
        _boolean("independent_new_source", self.independent_new_source)
        _boolean("model_input_gold_visible", self.model_input_gold_visible)
        _require(self.independent_new_source, "component receipt requires an independent source")
        _require(not self.model_input_gold_visible, "gold cannot be model-visible")

        actual_missing: list[str] = []
        for name in self._DIGEST_FIELDS:
            value = getattr(self, name)
            if value is None:
                actual_missing.append(name)
                continue
            if name == "source_blob_digest":
                _blob(name, value)
            else:
                _digest(name, value)
        if self.reader_forward_calls is None:
            actual_missing.append("reader_forward_calls")
        else:
            _integer("reader_forward_calls", self.reader_forward_calls)
        if self.charged_input_tokens is None:
            actual_missing.append("charged_input_tokens")
        else:
            _integer("charged_input_tokens", self.charged_input_tokens)

        if self.components is None:
            actual_missing.append("components")
        else:
            component_ids = tuple(item.component for item in self.components)
            present = set(component_ids)
            actual_missing.extend(f"components.{name}" for name in COMPONENTS if name not in present)
            _require(len(component_ids) == len(set(component_ids)), "component names must be unique")
            for item in self.components:
                _require(item.device_digest == (self.device.device_digest if self.device is not None else item.device_digest), "component/device digest mismatch")

        if self.device is None:
            actual_missing.append("device")
        else:
            _require(self.device.runtime_digest == (self.runtime_digest or self.device.runtime_digest), "runtime/device digest mismatch")

        actual_missing_tuple = tuple(sorted(set(actual_missing)))
        _require(tuple(sorted(self.missing_fields)) == self.missing_fields, "missing_fields must be sorted")
        _require(actual_missing_tuple == self.missing_fields, "missing_fields must exactly describe missing receipt values")
        if self.status == "COMPLETE":
            _require(not actual_missing_tuple, "complete receipt has missing fields")
            _require(self.evidence_class != INCOMPLETE, "complete receipt cannot use INCOMPLETE evidence")
        else:
            _require(bool(actual_missing_tuple), "incomplete receipt must identify missing fields")
            _require(self.evidence_class == INCOMPLETE, "incomplete receipt must preserve INCOMPLETE evidence")

    @property
    def complete(self) -> bool:
        return self.status == "COMPLETE" and not self.missing_fields

    @property
    def components_by_name(self) -> dict[str, ComponentUsageV1]:
        _require(self.components is not None, "component list is incomplete")
        return {item.component: item for item in self.components}

    @property
    def charged_flops(self) -> float:
        return sum(item.flops for item in self.components_by_name.values())

    @property
    def charged_latency_ms(self) -> float:
        return sum(item.p95_latency_ms for item in self.components_by_name.values())

    @property
    def charged_peak_memory_bytes(self) -> float:
        _require(self.device is not None, "device receipt is incomplete")
        # Device peak memory is the end-to-end measurement.  Component peaks
        # stay available for audit and are not added a second time.
        return float(self.device.peak_memory_bytes)

    @property
    def charged_energy_mj(self) -> float:
        _require(self.device is not None, "device receipt is incomplete")
        return float(self.device.energy_mj)

    def validate_against_budget(self, budget: Any, *, expected_forward_calls: int | None = None) -> None:
        """Fail closed if the complete receipt does not fit one fixed budget."""
        _require(self.complete, "incomplete component receipt cannot be budget-qualified")
        _require(self.budget_digest == budget.budget_digest, "component receipt budget digest mismatch")
        _require(self.cost_weights_digest == budget.cost_weights_digest, "component receipt cost weights mismatch")
        if expected_forward_calls is not None:
            _require(self.reader_forward_calls == expected_forward_calls, "reader forward-call budget is not equal")
        _require(self.reader_forward_calls <= budget.max_forward_calls, "forward-call budget exceeded")
        _require(self.charged_input_tokens <= budget.max_input_tokens, "input-token budget exceeded")
        _require(self.charged_flops <= budget.max_flops, "FLOPs budget exceeded")
        _require(self.charged_peak_memory_bytes <= budget.max_peak_memory_bytes, "memory budget exceeded")
        _require(self.charged_latency_ms <= budget.max_p95_latency_ms, "latency budget exceeded")
        _require(self.charged_energy_mj <= budget.max_energy_mj, "energy budget exceeded")

    def to_resource_cost(self) -> Any:
        """Project into the legacy fixed-accounting System2 cost buckets.

        The raw receipt remains authoritative.  The legacy buckets cannot
        represent tower/projector/decoder/state/cache/device separately, so
        this deterministic projection groups them for compatibility and keeps
        ``AGGREGATION_POLICY`` explicit.  It is not a physical equivalence.
        """
        _require(self.complete, "incomplete component receipt cannot become a System2 cost")
        _require(self.evidence_class == REAL_SHADOW, "only REAL_SHADOW receipts may enter the strict System2 adapter")
        from .prospective_plan import ResourceCostV1

        by_name = self.components_by_name
        encoder_flops = sum(by_name[name].flops for name in ("encoder", "tower", "projector"))
        cell_flops = sum(by_name[name].flops for name in ("decoder", "cell", "state", "cache"))
        controller_flops = by_name["controller"].flops
        verification_flops = by_name["verifier"].flops
        return ResourceCostV1(
            encoder_flops=encoder_flops,
            cell_flops=cell_flops,
            controller_flops=controller_flops,
            verification_flops=verification_flops,
            latency_ms=self.charged_latency_ms,
            memory_bytes=self.charged_peak_memory_bytes,
            energy_mj=self.charged_energy_mj,
        )

    def to_prospective_receipt(self, budget: Any, *, expected_forward_calls: int | None = None) -> Any:
        """Adapt one complete REAL_SHADOW receipt to ``ResourceReceiptV1``."""
        self.validate_against_budget(budget, expected_forward_calls=expected_forward_calls)
        _require(self.evidence_class == REAL_SHADOW, "prospective plan requires raw REAL_SHADOW evidence")
        from .prospective_plan import ResourceReceiptV1

        return ResourceReceiptV1(
            candidate_id=self.candidate_id,
            budget_digest=self.budget_digest,
            evidence_class=self.evidence_class,
            forward_calls=self.reader_forward_calls,
            input_tokens=self.charged_input_tokens,
            flops=self.charged_flops,
            peak_memory_bytes=self.charged_peak_memory_bytes,
            p95_latency_ms=self.charged_latency_ms,
            energy_mj=self.charged_energy_mj,
            independent_new_source=self.independent_new_source,
            model_input_gold_visible=self.model_input_gold_visible,
        )

    @property
    def receipt_digest(self) -> str:
        return _canonical_digest({"schema": SCHEMA_RECEIPT, **self.to_dict(include_digest=False)})

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {"schema": SCHEMA_RECEIPT, **asdict(self)}
        result["missing_fields"] = list(self.missing_fields)
        result["components"] = None if self.components is None else [item.to_dict() for item in self.components]
        result["device"] = None if self.device is None else self.device.to_dict()
        result["aggregation_policy"] = AGGREGATION_POLICY
        if include_digest:
            result["receipt_digest"] = self.receipt_digest
        return result


def adapt_component_receipts(
    receipts: Iterable[ComponentResourceReceiptV1],
    budget: Any,
    *,
    expected_candidate_ids: Iterable[str] | None = None,
    expected_forward_calls: int | None = None,
) -> dict[str, Any]:
    """Validate and adapt a complete candidate set without relabeling evidence."""
    items = tuple(receipts)
    _require(items, "component receipt set cannot be empty")
    ids = tuple(item.candidate_id for item in items)
    _require(len(ids) == len(set(ids)), "component receipt candidate IDs must be unique")
    if expected_candidate_ids is not None:
        _require(set(ids) == set(expected_candidate_ids), "component receipts must cover exactly the planned candidates")
    result: dict[str, Any] = {}
    for item in items:
        result[item.candidate_id] = item.to_prospective_receipt(budget, expected_forward_calls=expected_forward_calls)
    return result


__all__ = [
    "AGGREGATION_POLICY",
    "COMPONENTS",
    "ComponentReceiptError",
    "ComponentResourceReceiptV1",
    "ComponentUsageV1",
    "DeviceReceiptV1",
    "HISTORICAL_REPLAY",
    "INCOMPLETE",
    "REAL_MODEL_LOCAL_QUALIFICATION",
    "REAL_SHADOW",
    "SCHEMA_COMPONENT",
    "SCHEMA_DEVICE",
    "SCHEMA_RECEIPT",
    "SYNTHETIC_SMOKE",
    "adapt_component_receipts",
]
