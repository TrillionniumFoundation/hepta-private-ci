"""Bounded component identities, JSON values, budgets, and lifecycle protocols."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Protocol


class CellError(ValueError):
    pass


class PendingExecution(CellError):
    pass


class RequestConflict(CellError):
    pass


def _bounded_json(value: Any, limit: int = 262144) -> str:
    nodes = 0

    def check(item, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 32768:
            raise CellError("JSON structure exceeds the bounded interface")
        if item is None or type(item) in (bool, str):
            return
        if type(item) in (int, float):
            if abs(item) > 1e100 or not math.isfinite(item):
                raise CellError("non-finite or excessively large number")
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise CellError("only finite JSON values are supported")

    check(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > limit:
        raise CellError("JSON byte budget exceeded")
    return encoded


def digest(value: Any) -> str:
    return hashlib.sha256(_bounded_json(value).encode()).hexdigest()


def _token(value: str):
    """Only canonical Python strings may name a stable owner, Cell or run."""
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise CellError("invalid bounded stable identifier")


def _hex(value: str):
    """Reject identity subclasses before equality can spoof a zero digest."""
    if (
        type(value) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", value)
        or value == "0" * 64
    ):
        raise CellError("expected a nonzero lowercase SHA256 digest")


@dataclass(frozen=True)
class ComponentIdentity:
    implementation: str
    bundle_digest: str
    effectful: bool = False
    configuration_digest: str | None = None

    def __post_init__(self):
        _token(self.implementation)
        _hex(self.bundle_digest)
        if self.configuration_digest is not None:
            _hex(self.configuration_digest)
        if type(self.effectful) is not bool:
            raise CellError("effectful must be boolean")

    @property
    def digest(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class Partition:
    principal_id: str
    agent_id: str
    cell_id: str
    run_id: str

    def __post_init__(self):
        for value in asdict(self).values():
            _token(value)

    @property
    def digest(self):
        data = bytearray(b"hepta.cell.state-partition.v1\0")
        for value in asdict(self).values():
            raw = value.encode()
            data.extend(len(raw).to_bytes(4, "big"))
            data.extend(raw)
        return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Budget:
    max_work_units: int = 10000
    max_input_bytes: int = 65536
    max_output_bytes: int = 65536
    max_state_bytes: int = 65536
    max_elapsed_ms: int = 1000

    def __post_init__(self):
        ceilings = (1000000000, 262144, 262144, 262144, 60000)
        for value, ceiling in zip(asdict(self).values(), ceilings):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise CellError("invalid bounded budget")


@dataclass(frozen=True)
class OwnerLimits:
    """Total retained rows per database; epochs include every partition's epoch zero.

    Limits are persisted on first open and cannot be changed by reopening.
    Existing per-partition limits remain additional bounds, never eviction rules.
    """

    max_cells: int = 128
    max_intents: int = 4096
    max_checkpoints: int = 2048
    max_epochs: int = 2048

    def __post_init__(self):
        for value, ceiling in zip(asdict(self).values(), (128, 131072, 16384, 16384)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise CellError("invalid bounded owner limit")


@dataclass(frozen=True)
class StepContext:
    partition: Partition
    request_id: str
    identity: ComponentIdentity
    retrieval_view: Any
    budget: Budget
    epoch: int = 0


@dataclass(frozen=True)
class StepResult:
    output: Any
    state: Any
    work_units: int


class Component(Protocol):
    @property
    def identity(self) -> ComponentIdentity: ...
    def initial_state(self) -> Any: ...
    def step(self, payload: Any, state: Any, context: StepContext) -> StepResult: ...


@dataclass(frozen=True)
class PendingIntent:
    partition: Partition
    request_id: str
    identity: ComponentIdentity
    epoch: int
    payload: Any
    state: Any
    retrieval_view: Any
    budget: Budget
    request_digest: str


@dataclass(frozen=True)
class ReadbackResult:
    result: StepResult
    original_elapsed_ns: int | None


@dataclass(frozen=True)
class Qualification:
    source_identity: str
    candidate_identity: str
    evaluation_digest: str

    def __post_init__(self):
        for value in asdict(self).values():
            _hex(value)
