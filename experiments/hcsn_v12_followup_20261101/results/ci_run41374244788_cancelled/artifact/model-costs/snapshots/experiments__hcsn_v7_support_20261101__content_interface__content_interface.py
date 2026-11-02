"""Research contracts for common visible content and action-value control.

This module has no encoder, trained readout, or scientific confirmation adapter.
Fixture mode tests causal plumbing, never recognition quality or core benefit.
"""

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
import sys
from typing import Protocol


CORRECTNESS_TARGET = "correctness_of_common_stop_head.v1"


class ContractError(ValueError):
    pass


class MissingFittedAdapters(RuntimeError):
    pass


class Modality(Enum):
    AUDIO = "audio"
    VIDEO = "video"


class BackendKind(Enum):
    CORE = "core"
    DIRECT_HISTORY = "direct_history"


class Purpose(Enum):
    CONTRACT_FIXTURE = "contract_fixture"
    SCIENTIFIC_CONFIRMATION = "scientific_confirmation"


def finite(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ContractError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ContractError(f"{name} must be finite")
    if minimum is not None and value < minimum:
        raise ContractError(f"{name} below its allowed range")
    if maximum is not None and value > maximum:
        raise ContractError(f"{name} above its allowed range")
    return value


def vector(value, name):
    result = tuple(finite(x, name) for x in value)
    if not result:
        raise ContractError(f"{name} cannot be empty")
    return result


def identity(value, name):
    if not isinstance(value, str) or not 0 < len(value.encode()) <= 128:
        raise ContractError(f"{name} requires 1 to 128 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class PrefixObservation:
    """A completed prefix; all timestamps share the episode source-clock origin.

    raw holds features for the common content head. aligned holds features for
    the optional common pairing transform. Neither field accepts target labels
    by contract; identifying a maliciously encoded label needs dataset auditing.
    """

    event_id: str
    object_id: str
    modality: Modality
    prefix_end: float
    available_at: float
    completed_at: float
    raw: tuple
    aligned: tuple
    alignment_id: str
    aligned_window: tuple

    def __post_init__(self):
        identity(self.event_id, "Event identity")
        identity(self.object_id, "Object identity")
        identity(self.alignment_id, "Alignment identity")
        if not isinstance(self.modality, Modality):
            raise ContractError("Unknown modality")
        for name in ("prefix_end", "available_at", "completed_at"):
            object.__setattr__(self, name, finite(getattr(self, name), name, 0))
        if not 0 < self.prefix_end <= self.available_at <= self.completed_at:
            raise ContractError("Prefix release and completion violate causal order")
        object.__setattr__(self, "raw", vector(self.raw, "raw features"))
        object.__setattr__(self, "aligned", vector(self.aligned, "aligned features"))
        window = vector(self.aligned_window, "aligned window")
        if len(window) != 2 or not 0 <= window[0] < window[1] <= self.prefix_end:
            raise ContractError("Aligned features need a declared interval within the prefix")
        object.__setattr__(self, "aligned_window", window)


@dataclass(frozen=True, slots=True)
class CacheBudget:
    """Nominal float64 payload budget, distinct from Python/encoder memory."""

    max_payload_bytes: int
    max_prefix_end: int = 3
    max_events: int = 6

    def __post_init__(self):
        for name in ("max_payload_bytes", "max_prefix_end", "max_events"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContractError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class VisibleContent:
    """Only accepted prefixes, with immutable features and bounded metadata."""

    object_id: str
    budget: CacheBudget
    last_accepted_at: float = 0.0
    audio: PrefixObservation | None = None
    video: PrefixObservation | None = None
    accepted_event_ids: tuple = ()

    def __post_init__(self):
        identity(self.object_id, "Object identity")
        object.__setattr__(self, "accepted_event_ids", tuple(self.accepted_event_ids))
        for event_id in self.accepted_event_ids:
            identity(event_id, "Accepted event identity")
        object.__setattr__(self, "last_accepted_at", finite(self.last_accepted_at, "acceptance time", 0))
        if len(set(self.accepted_event_ids)) != len(self.accepted_event_ids):
            raise ContractError("Duplicate accepted event identity")
        if len(self.accepted_event_ids) > self.budget.max_events:
            raise ContractError("Accepted event metadata exceeds common capacity")
        for modality in Modality:
            obs = self.observation(modality)
            if obs is None:
                continue
            if obs.object_id != self.object_id or obs.modality != modality:
                raise ContractError("Observation belongs to a different object or modality")
            if obs.completed_at > self.last_accepted_at:
                raise ContractError("Cache contains an observation before its completion")
            if obs.prefix_end > self.budget.max_prefix_end:
                raise ContractError("Prefix exceeds the common content budget")
            if obs.event_id not in self.accepted_event_ids:
                raise ContractError("Cache contains an unaccepted observation")
        if self.nominal_payload_bytes > self.budget.max_payload_bytes:
            raise ContractError("Common content payload capacity exceeded")

    def observation(self, modality):
        if modality == Modality.AUDIO:
            return self.audio
        if modality == Modality.VIDEO:
            return self.video
        raise ContractError("Unknown modality")

    @property
    def nominal_payload_bytes(self):
        return 8 * sum(len(x.raw) + len(x.aligned) for x in (self.audio, self.video) if x is not None)

    def level(self, modality):
        obs = self.observation(modality)
        return 0.0 if obs is None else obs.prefix_end

    def accept(self, observation, accepted_at):
        accepted_at = finite(accepted_at, "acceptance time", 0)
        if observation.object_id != self.object_id:
            raise ContractError("Cannot mix objects in the common content cache")
        if observation.event_id in self.accepted_event_ids:
            raise ContractError("Duplicate event cannot update content again")
        if observation.completed_at > accepted_at:
            raise ContractError("Future completion cannot be consumed")
        if self.accepted_event_ids and accepted_at <= self.last_accepted_at:
            raise ContractError("Acceptance time must strictly advance")
        if observation.prefix_end != self.level(observation.modality) + 1:
            raise ContractError("Only the next one-second prefix is legal")
        return VisibleContent(
            object_id=self.object_id,
            budget=self.budget,
            last_accepted_at=accepted_at,
            audio=observation if observation.modality == Modality.AUDIO else self.audio,
            video=observation if observation.modality == Modality.VIDEO else self.video,
            accepted_event_ids=self.accepted_event_ids + (observation.event_id,),
        )

    def pair_interactions(self):
        if self.audio is None or self.video is None:
            return None
        if (self.audio.alignment_id != self.video.alignment_id
                or self.audio.aligned_window != self.video.aligned_window):
            raise ContractError("Pairing requires the same alignment identity and source interval")
        a, v = self.audio.aligned, self.video.aligned
        if len(a) != len(v):
            raise ContractError("A shared fitted alignment is required for pairing")
        return tuple(x * y for x, y in zip(a, v)) + tuple(abs(x - y) for x, y in zip(a, v))

    def storage_accounting(self):
        seen = set()

        def owned_size(obj):
            if obj is None or id(obj) in seen:
                return 0
            seen.add(id(obj))
            size = sys.getsizeof(obj)
            if is_dataclass(obj):
                size += sum(owned_size(getattr(obj, f.name)) for f in fields(obj))
            elif isinstance(obj, tuple):
                size += sum(owned_size(x) for x in obj)
            return size

        return {
            "nominal_float64_payload_bytes": self.nominal_payload_bytes,
            "nominal_payload_limit_bytes": self.budget.max_payload_bytes,
            "retained_python_object_graph_bytes": owned_size(self),
            "retained_event_count": len(self.accepted_event_ids),
            "dtype": "Python float (binary64); copied immutable tuples",
            "scope": "sys.getsizeof over this snapshot's unique dataclass/tuple/value objects; "
                     "not process RSS/PSS, allocator fragmentation, encoder, readout or transient pair workspace",
        }

    def fingerprint(self):
        observations = []
        for obs in (self.audio, self.video):
            observations.append(None if obs is None else {
                "id": obs.event_id, "modality": obs.modality.value,
                "prefix": obs.prefix_end, "available": obs.available_at,
                "completed": obs.completed_at, "raw": obs.raw, "aligned": obs.aligned,
                "alignment_id": obs.alignment_id, "aligned_window": obs.aligned_window,
            })
        payload = [self.object_id, self.last_accepted_at, self.accepted_event_ids,
                   self.budget.max_payload_bytes, self.budget.max_prefix_end,
                   self.budget.max_events, observations]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CoreSnapshot:
    """A 32-scalar state bound to exactly the same currently visible content."""

    core_id: str
    content_fingerprint: str
    values: tuple

    def __post_init__(self):
        object.__setattr__(self, "values", vector(self.values, "core state"))
        identity(self.core_id, "Core identity")
        if len(self.values) != 32:
            raise ContractError("Every core requires an identity and 32 state scalars")


@dataclass(frozen=True, slots=True)
class CorrectnessValue:
    probability: float
    head_id: str
    target: str = CORRECTNESS_TARGET

    def __post_init__(self):
        object.__setattr__(self, "probability", finite(self.probability, "correctness probability", 0, 1))
        identity(self.head_id, "Content head identity")
        if self.target != CORRECTNESS_TARGET:
            raise ContractError("Values must target correctness of the common STOP head")


@dataclass(frozen=True, slots=True)
class StopEvaluation:
    class_probabilities: tuple
    calibrated_correctness: CorrectnessValue

    def __post_init__(self):
        probs = tuple(finite(x, "class probability", 0, 1) for x in self.class_probabilities)
        if len(probs) < 2 or abs(sum(probs) - 1.0) > 1e-10:
            raise ContractError("STOP probabilities must be a normalized multiclass distribution")
        object.__setattr__(self, "class_probabilities", probs)

    @property
    def predicted_class(self):
        return max(range(len(self.class_probabilities)), key=self.class_probabilities.__getitem__)


class CommonStopHead(Protocol):
    """Read only visible content; core family/state is not an input."""

    def evaluate(self, content: VisibleContent) -> StopEvaluation:
        ...


@dataclass(frozen=True, slots=True)
class Action:
    """One requested next prefix; service forecasts cannot contain test outcomes."""

    modality: Modality
    prefix_end: float
    expected_additional_seconds: float
    deadline_miss_probability: float

    def __post_init__(self):
        if not isinstance(self.modality, Modality):
            raise ContractError("Unknown action modality")
        for name, limit in (("prefix_end", None), ("expected_additional_seconds", None),
                            ("deadline_miss_probability", 1)):
            object.__setattr__(self, name, finite(getattr(self, name), name, 0, limit))
        if self.prefix_end == 0 or self.expected_additional_seconds == 0:
            raise ContractError("A content action needs a positive prefix and elapsed forecast")

    @property
    def identity(self):
        return f"{self.modality.value}:{self.prefix_end:g}"


class ActionValueBackend(Protocol):
    """Same target/readout role for learned cores and direct-history reference."""

    kind: BackendKind
    reader_id: str

    def evaluate(self, content: VisibleContent, state: CoreSnapshot | None, action: Action) -> CorrectnessValue:
        ...


@dataclass(frozen=True, slots=True)
class CostWeights:
    observation: float = 0.02
    elapsed_second: float = 0.005
    deadline_miss: float = 1.0

    def __post_init__(self):
        for name in ("observation", "elapsed_second", "deadline_miss"):
            object.__setattr__(self, name, finite(getattr(self, name), name, 0))


@dataclass(frozen=True, slots=True)
class ScoredAction:
    action: Action
    forecast_correctness: float
    score: float
    increment_over_stop: float


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action | None
    stop: StopEvaluation
    stop_score: float
    alternatives: tuple
    backend: BackendKind
    reader_id: str
    core_id: str | None
    content_fingerprint: str
    core_state_supplied_to_reader: bool
    scientific_execution: bool = False


def select_action(content, state, stop_head, backend, actions, now, deadline,
                  costs=CostWeights(), purpose=Purpose.CONTRACT_FIXTURE):
    """Compare same-target expected correctness and explicit incremental costs.

    Prior incurred costs are common and cancel. Current STOP confidence is a
    separately calibrated correctness probability, not max(class probabilities).
    A positive score increment is required; exact ties choose STOP.
    """
    if purpose != Purpose.CONTRACT_FIXTURE:
        raise MissingFittedAdapters(
            "Scientific execution is unavailable: restored encoder, common STOP/calibration "
            "weights, action-value readers and independently frozen cohort are required."
        )
    now = finite(now, "decision time", 0)
    deadline = finite(deadline, "deadline", 0)
    if now < content.last_accepted_at:
        raise ContractError("Decision time precedes an accepted observation")
    identity(backend.reader_id, "Action-value reader identity")
    if backend.kind not in (BackendKind.CORE, BackendKind.DIRECT_HISTORY):
        raise ContractError("Every decision must declare its value backend and reader")
    if backend.kind == BackendKind.CORE:
        if state is None or state.content_fingerprint != content.fingerprint():
            raise ContractError("A core reader requires state for exactly this content snapshot")
    elif state is not None:
        raise ContractError("Direct-history baseline cannot silently consume core state")
    actions = tuple(actions)
    if len({a.identity for a in actions}) != len(actions):
        raise ContractError("Duplicate action alternatives")
    for action in actions:
        if action.prefix_end != content.level(action.modality) + 1 or action.prefix_end > content.budget.max_prefix_end:
            raise ContractError("Requested action is not a legal next prefix")
    stop = stop_head.evaluate(content)
    stop_score = stop.calibrated_correctness.probability - costs.deadline_miss * int(now > deadline)
    alternatives = []
    if now <= deadline:
        for action in actions:
            future = backend.evaluate(content, state, action)
            if future.head_id != stop.calibrated_correctness.head_id:
                raise ContractError("Current and future values refer to different content heads")
            score = (future.probability - costs.observation
                     - costs.elapsed_second * action.expected_additional_seconds
                     - costs.deadline_miss * action.deadline_miss_probability)
            alternatives.append(ScoredAction(action, future.probability, score, score - stop_score))
    best = max(alternatives, key=lambda x: (x.increment_over_stop, x.action.identity), default=None)
    chosen = best.action if best is not None and best.increment_over_stop > 0 else None
    return Decision(chosen, stop, stop_score, tuple(alternatives), backend.kind,
                    backend.reader_id, state.core_id if state is not None else None,
                    content.fingerprint(), backend.kind == BackendKind.CORE and bool(alternatives))
