"""Typed research reports and check scheduling; no report confers host authority.

Parsing a claimed verdict never executes a checker or creates a capability.
Horizon steps form a closed interval; predictions precede it and receipts may
arrive later. Canonical JSON is deterministic for this Python schema, not JCS.
"""

from dataclasses import dataclass, fields
import hashlib
import json
import math
import re


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name):
    _require(
        type(value) is str and bool(value.strip()) and value == value.strip(),
        f"{name} must be nonempty unpadded text",
    )


def _sha(value, name):
    _require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"{name} must be a lowercase SHA256",
    )


def _integer(value, name):
    _require(type(value) is int and value >= 0, f"{name} must be a nonnegative integer")


def _number(value, name, maximum=None):
    _require(type(value) in (int, float), f"{name} must be numeric, excluding bool")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    _require(
        math.isfinite(result) and result >= 0, f"{name} must be finite and nonnegative"
    )
    _require(maximum is None or result <= maximum, f"{name} exceeds its range")
    return result


def _strings(value, name, nonempty=False):
    _require(type(value) in (tuple, list), f"{name} must be an array")
    for item in value:
        _text(item, name)
    _require(len(set(value)) == len(value), f"{name} contains duplicates")
    _require(not nonempty or bool(value), f"{name} must not be empty")
    return tuple(value)


@dataclass(frozen=True)
class Scope:
    task_id: str
    attempt_id: str
    subject_sha256: str
    state_version: int
    domain: str
    event: str
    horizon_start: int
    horizon_end: int

    def __post_init__(self):
        for name in ("task_id", "attempt_id", "domain", "event"):
            _text(getattr(self, name), name)
        _sha(self.subject_sha256, "subject_sha256")
        for name in ("state_version", "horizon_start", "horizon_end"):
            _integer(getattr(self, name), name)
        _require(self.horizon_start <= self.horizon_end, "horizon is reversed")


@dataclass(frozen=True)
class ModelIdentity:
    base_sha256: str
    adapter_sha256: str | None
    policy_sha256: str

    def __post_init__(self):
        _sha(self.base_sha256, "base_sha256")
        _sha(self.policy_sha256, "policy_sha256")
        if self.adapter_sha256 is not None:
            _sha(self.adapter_sha256, "adapter_sha256")


@dataclass(frozen=True)
class RiskPrediction:
    scope: Scope
    model: ModelIdentity
    probability: float
    observed_step: int
    evidence_sha256: str

    def __post_init__(self):
        _require(
            type(self.scope) is Scope and type(self.model) is ModelIdentity,
            "risk requires exact Scope and ModelIdentity types",
        )
        object.__setattr__(
            self, "probability", _number(self.probability, "probability", 1)
        )
        _integer(self.observed_step, "observed_step")
        _require(
            self.observed_step <= self.scope.horizon_start,
            "prediction is retrospective",
        )
        _sha(self.evidence_sha256, "evidence_sha256")


_METRICS = {
    "brier": "proper_scoring_rule",
    "ece": "calibration_diagnostic",
    "score_miscoverage": "score_event_frequency",
    "accepted_trajectory_error_rate": "outcome_event_frequency",
}


@dataclass(frozen=True)
class CalibrationReport:
    """Empirical metric with explicit provenance; never a coverage guarantee.

    data_sha256 binds the dataset manifest. Group sets are declared partitions,
    not proof that the underlying material is independent. Empty training means
    no new fitting; calibration and confirmation partitions must be declared.
    """

    scope: Scope
    model: ModelIdentity
    training_source_groups: tuple[str, ...]
    calibration_source_groups: tuple[str, ...]
    confirmation_source_groups: tuple[str, ...]
    data_sha256: str
    metric: str
    metric_kind: str
    metric_value: float
    sample_count: int
    drift: str
    assumptions: tuple[str, ...]

    def __post_init__(self):
        _require(
            type(self.scope) is Scope and type(self.model) is ModelIdentity,
            "calibration requires exact Scope and ModelIdentity types",
        )
        seen = set()
        for name in (
            "training_source_groups",
            "calibration_source_groups",
            "confirmation_source_groups",
        ):
            groups = _strings(
                getattr(self, name), name, name != "training_source_groups"
            )
            _require(
                not seen.intersection(groups), "source groups leak between partitions"
            )
            seen.update(groups)
            object.__setattr__(self, name, groups)
        _sha(self.data_sha256, "data_sha256")
        _text(self.metric, "metric")
        _require(
            self.metric in _METRICS and _METRICS[self.metric] == self.metric_kind,
            "metric and metric_kind mismatch",
        )
        object.__setattr__(
            self, "metric_value", _number(self.metric_value, "metric_value", 1)
        )
        _integer(self.sample_count, "sample_count")
        _require(self.sample_count > 0, "an empirical metric needs samples")
        _require(
            self.drift in ("not_detected", "detected", "unknown"), "invalid drift state"
        )
        object.__setattr__(
            self, "assumptions", _strings(self.assumptions, "assumptions", True)
        )


@dataclass(frozen=True)
class VerificationReceipt:
    """A claimed checker result scoped to one subject/property, not authorization."""

    scope: Scope
    property: str
    assumptions: tuple[str, ...]
    checker_id: str
    checker_version: str
    evidence_sha256: str
    checked_step: int
    verdict: str
    reason: str
    residual_obligations: tuple[str, ...]

    def __post_init__(self):
        _require(type(self.scope) is Scope, "receipt requires the exact Scope type")
        for name in ("property", "checker_id", "checker_version", "reason"):
            _text(getattr(self, name), name)
        object.__setattr__(
            self, "assumptions", _strings(self.assumptions, "assumptions")
        )
        residual = _strings(self.residual_obligations, "residual_obligations")
        object.__setattr__(self, "residual_obligations", residual)
        _sha(self.evidence_sha256, "evidence_sha256")
        _integer(self.checked_step, "checked_step")
        _require(
            self.checked_step >= self.scope.horizon_start, "receipt predates its scope"
        )
        _require(self.verdict in ("proved", "refuted", "unknown"), "invalid verdict")
        _require(
            self.verdict != "proved" or not residual, "proved has residual obligations"
        )
        _require(
            self.verdict != "unknown" or bool(residual),
            "unknown needs residual obligations",
        )


_TAGS = {
    RiskPrediction: "risk_prediction",
    CalibrationReport: "calibration_report",
    VerificationReceipt: "verification_receipt",
}


def _wire(value):
    if type(value) in (*_TAGS, Scope, ModelIdentity):
        result = {
            field.name: _wire(getattr(value, field.name)) for field in fields(value)
        }
        return (
            {"type": _TAGS[type(value)], **result} if type(value) in _TAGS else result
        )
    if type(value) is dict:
        _require(
            all(type(key) is str for key in value), "JSON object keys must be strings"
        )
        return {key: _wire(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_wire(item) for item in value]
    _require(
        value is None or type(value) in (str, int, float, bool),
        "unsupported JSON value",
    )
    return value


def canonical_json(value):
    """Encode reports with type tags, or ordinary JSON; reject nonfinite numbers."""
    try:
        return json.dumps(
            _wire(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, RecursionError) as error:
        raise ValueError("invalid JSON value") from error


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _build(cls, value):
    _require(type(value) is dict, f"{cls.__name__} must be an object")
    _require(
        set(value) == {field.name for field in fields(cls)},
        f"{cls.__name__} has missing or unknown fields",
    )
    data = dict(value)
    for name, nested in (("scope", Scope), ("model", ModelIdentity)):
        if name in data:
            data[name] = _build(nested, data[name])
    return cls(**data)


def parse_record(raw):
    """Parse a bounded, strict report. Neither provenance nor truth is authenticated."""
    _require(
        type(raw) is str and len(raw) <= 65536,
        "record must be JSON text under 64 Ki characters",
    )
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda item: _require(
                False, f"invalid JSON constant: {item}"
            ),
        )
    except RecursionError as error:
        raise ValueError("record is too deeply nested") from error
    _require(
        type(value) is dict and type(value.get("type")) is str, "missing report type"
    )
    cls = next((kind for kind, tag in _TAGS.items() if tag == value["type"]), None)
    _require(cls is not None, "unknown report type")
    return _build(cls, {key: item for key, item in value.items() if key != "type"})


def assert_bound(record, scope, model=None, evidence_sha256=None, *, expected_type):
    """Reject cross-type/subject/model/evidence reuse; do not authenticate claims."""
    _require(
        expected_type in tuple(_TAGS) and type(record) is expected_type,
        "report type mismatch",
    )
    _require(type(scope) is Scope and record.scope == scope, "scope mismatch")
    if model is not None:
        _require(
            type(model) is ModelIdentity
            and type(record) in (RiskPrediction, CalibrationReport)
            and record.model == model,
            "model mismatch",
        )
    if evidence_sha256 is not None:
        _sha(evidence_sha256, "expected evidence_sha256")
        _require(
            type(record) in (RiskPrediction, VerificationReceipt)
            and record.evidence_sha256 == evidence_sha256,
            "evidence mismatch",
        )


def select_check(
    risk, expected_check_cost, error_loss, remaining_budget, mandatory=False
):
    """Choose check/defer/blocked only. A choice never authorizes an action.

    risk may be a RiskPrediction or a probability. This is a simple expected-loss
    baseline; checker efficacy and downstream outcomes are not modeled.
    """
    probability = _number(
        risk.probability if type(risk) is RiskPrediction else risk, "risk", 1
    )
    cost = _number(expected_check_cost, "expected_check_cost")
    loss = _number(error_loss, "error_loss")
    budget = _number(remaining_budget, "remaining_budget")
    _require(type(mandatory) is bool, "mandatory must be bool")
    if mandatory:
        return "check" if cost <= budget else "blocked"
    return "check" if cost <= budget and probability * loss >= cost else "defer"
