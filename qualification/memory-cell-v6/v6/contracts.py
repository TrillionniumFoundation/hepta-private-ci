"""Bounded requests and prediction/evidence readouts, with explicit versions."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

OPERATIONS = ("current", "history", "semantic", "procedure", "change", "apply")
KINDS = ("event", "semantic", "procedure")
MAX_WIRE_BYTES = 131072


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def bounded_text(value, limit=256):
    return (
        isinstance(value, str)
        and 0 < len(value.encode()) <= limit
        and "\x00" not in value
    )


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def valid_digest(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def validate_value(value):
    if len(canonical(value)) > 16384:
        raise ValueError("value exceeds bounded readout")


@dataclass(frozen=True)
class MemoryRequest:
    query_id: str
    scope: str
    entity: str
    text: str
    at: int
    since: int
    max_hops: int = 4
    max_cells: int = 3
    schema: str = "hepta.memory.request.v1"

    def __post_init__(self):
        if self.schema != "hepta.memory.request.v1":
            raise ValueError("unknown request schema")
        if not all(bounded_text(x) for x in (self.query_id, self.scope, self.entity)):
            raise ValueError("invalid request identity")
        if not bounded_text(self.text, 8192):
            raise ValueError("invalid query text")
        if not integer(self.at, 0, 2**53 - 1) or not integer(self.since, 0, self.at):
            raise ValueError("invalid time interval")
        if not integer(self.max_hops, 1, 8) or not integer(self.max_cells, 1, 8):
            raise ValueError("invalid execution budget")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("request must be an object")
        try:
            return cls(**value)
        except TypeError as error:
            raise ValueError("invalid request fields") from error

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class MemoryReadout:
    query_id: str
    operation: str | None
    status: str
    value: object
    source_ids: tuple
    generation: int
    snapshot_digest: str
    prediction_kind: str
    cell_digests: tuple
    hops: int
    elapsed_seconds: float
    reason: str | None = None
    schema: str = "hepta.memory.readout.v1"

    def __post_init__(self):
        if self.schema != "hepta.memory.readout.v1" or not bounded_text(self.query_id):
            raise ValueError("invalid readout identity")
        if self.operation not in (*OPERATIONS, None):
            raise ValueError("unsupported operation")
        if self.status not in (
            "ok",
            "abstain",
            "stale",
            "unavailable",
            "budget_exceeded",
        ):
            raise ValueError("invalid disposition")
        if self.prediction_kind not in (
            "source_evidence",
            "model_prediction",
            "mixed",
            "none",
        ):
            raise ValueError("invalid prediction/evidence distinction")
        if not valid_digest(self.snapshot_digest):
            raise ValueError("invalid snapshot digest")
        for name, values, limit in (
            ("source", self.source_ids, 64),
            ("cell", self.cell_digests, 8),
        ):
            if (
                not isinstance(values, (list, tuple))
                or len(values) > limit
                or any(not valid_digest(value) for value in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("invalid, duplicate or unbounded " + name + " digests")
        if not integer(self.generation, 1, 2**53 - 1) or not integer(self.hops, 0, 8):
            raise ValueError("invalid generation or hops")
        if (
            type(self.elapsed_seconds) not in (int, float)
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise ValueError("invalid latency")
        validate_value(self.value)
        if self.status == "ok":
            if (
                self.operation is None
                or self.value is None
                or not self.source_ids
                or self.reason is not None
                or self.hops == 0
            ):
                raise ValueError("successful readout is incomplete")
            if (
                self.prediction_kind == "none"
                or (self.prediction_kind == "source_evidence" and self.cell_digests)
                or (
                    self.prediction_kind in ("model_prediction", "mixed")
                    and not self.cell_digests
                )
            ):
                raise ValueError("prediction kind contradicts model dependencies")
        elif (
            self.value is not None
            or self.source_ids
            or self.cell_digests
            or self.prediction_kind != "none"
            or not bounded_text(self.reason, 1024)
        ):
            raise ValueError("failed readout must not leak a partial answer")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("readout must be an object")
        try:
            return cls(**value)
        except TypeError as error:
            raise ValueError("invalid readout fields") from error

    def as_dict(self):
        return asdict(self)
