"""Arrival-clock streaming with separate continuous and measurement updates.

An encoder sees only the supplied raw prefix. Its returned tokens retain their
individual rows, including several contents arriving at the same timestamp.
This adapter does not certify the encoder's strength, train a model, or turn
source identifiers into model features. Core advance/observe/query operations
are deliberately separate: a zero-duration observation still has an effect.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np


def _sha(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("expected lowercase SHA256")
    return value


def _clock(value):
    if type(value) is not int or not 0 <= value < 2**53:
        raise ValueError("clock must be an exact nonnegative integer in microseconds")
    return value


@dataclass(frozen=True)
class FrontendIdentity:
    """Pin actual checkpoint, preprocessing and runtime; names are insufficient."""

    checkpoint_sha256: str
    preprocessing_sha256: str
    runtime_sha256: str
    width: int
    max_tokens: int

    def __post_init__(self):
        for value in (self.checkpoint_sha256, self.preprocessing_sha256, self.runtime_sha256):
            _sha(value)
        if type(self.width) is not int or not 1 <= self.width <= 65536:
            raise ValueError("bounded positive feature width required")
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 65536:
            raise ValueError("bounded positive token limit required")


@dataclass(frozen=True)
class Prefix:
    """Raw prefix available by arrival time; targets are outside this interface.

    Clocks must already be mapped into a common frozen microsecond coordinate.
    This carrier does not measure sensor synchronization or perform the crop.
    """

    payload: bytes
    source_start_micros: int
    source_end_micros: int
    arrival_micros: int

    def __post_init__(self):
        times = tuple(_clock(v) for v in (self.source_start_micros,
                                         self.source_end_micros, self.arrival_micros))
        if not times[0] <= times[1] <= times[2] or not isinstance(self.payload, bytes):
            raise ValueError("prefix must be available before its declared arrival")
        if not self.payload:
            raise ValueError("empty raw prefix")


@dataclass(frozen=True)
class EncodedEvent:
    """Read-only owned tokens and their provenance, without answer labels."""

    raw_arrival_micros: int
    encode_started_micros: int
    ready_micros: int
    order: int
    source_end_micros: int
    modality: int
    prefix_sha256: str
    frontend: FrontendIdentity
    tokens: np.ndarray

    def __post_init__(self):
        times = tuple(_clock(v) for v in (self.source_end_micros, self.raw_arrival_micros,
                                         self.encode_started_micros, self.ready_micros))
        if not all(a <= b for a, b in zip(times[:-1], times[1:])):
            raise ValueError("future prefix or inverted acquisition/encoding clocks")
        if type(self.order) is not int or not 0 <= self.order < 2**53:
            raise ValueError("stable nonnegative arrival order required")
        if type(self.modality) is not int or not 0 <= self.modality < 256:
            raise ValueError("bounded modality ID required")
        _sha(self.prefix_sha256)
        value = np.array(self.tokens, dtype=np.float64, order="C", copy=True)
        if (value.ndim != 2 or value.shape[1] != self.frontend.width
                or not 1 <= len(value) <= self.frontend.max_tokens
                or not np.isfinite(value).all()):
            raise ValueError("invalid finite token matrix")
        # A byte-backed array cannot be made writable by setflags(write=True).
        value = np.frombuffer(value.tobytes(), dtype=np.float64).reshape(value.shape)
        object.__setattr__(self, "tokens", value)


class PrefixEncoder:
    """Hash-check local weights before invoking the declared prefix-only encoder.

    The caller owns the encoder implementation and preprocessing/runtime pins.
    This check establishes checkpoint possession, not an attestation that a
    Python callback used those weights or that pretraining was contamination free.
    """

    def __init__(self, identity, checkpoint, encode_prefix, *, clock_micros):
        if (not isinstance(identity, FrontendIdentity) or not callable(encode_prefix)
                or not callable(clock_micros)):
            raise ValueError("frontend identity, encoder and common monotonic clock required")
        path = Path(checkpoint)
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular checkpoint required")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != identity.checkpoint_sha256:
            raise ValueError("checkpoint identity mismatch")
        self.identity, self.encode_prefix = identity, encode_prefix
        self.clock_micros = clock_micros

    def encode(self, prefix, *, order, modality):
        if not isinstance(prefix, Prefix):
            raise ValueError("explicit raw prefix required")
        started = _clock(self.clock_micros())
        if started < prefix.arrival_micros:
            raise ValueError("encoding starts before raw acquisition or clocks differ")
        # No suffix, file name, speaker/clip identity, task label or query answer
        # is passed to the encoder. Cropping must precede contextual encoding.
        tokens = self.encode_prefix(prefix.payload)
        # Build the unpublished immutable CPU snapshot before sampling readiness.
        # Array-like/device results can block or materialize in __array__; even
        # the owned copy, finite checks and payload hash belong before this clock.
        event = EncodedEvent(prefix.arrival_micros, started, started, order,
                             prefix.source_end_micros, modality,
                             hashlib.sha256(prefix.payload).hexdigest(), self.identity, tokens)
        ready = _clock(self.clock_micros())
        if ready < started:
            raise ValueError("encoder completion clock moved backwards")
        object.__setattr__(event, "ready_micros", ready)
        return event


class EventCore(Protocol):
    """Core with an explicit flow, instantaneous observation, and pure readout.

    Observe receives tokens and modality, never prefix hashes or source IDs.
    Implementations must make query observational; state mutation is their duty
    to test, not something an arbitrary Python wrapper can prove.
    """

    def advance(self, seconds: float) -> None: ...
    def observe(self, tokens: np.ndarray, modality: int) -> None: ...
    def query(self, query: np.ndarray) -> np.ndarray: ...


class ArrivalStream:
    """A bounded batch is validated entirely before any core operation.

    Dynamics use feature-ready arrival time, not retrospectively sorted source time. Ties use
    the frozen explicit order; this is causal sequential J, not a claim of
    permutation invariance. Distinct source contents are never averaged away.
    Exceptions from the core poison the stream because it may be partly mutated.
    """

    def __init__(self, core, frontends, *, start_micros=0, max_batch_tokens=4096):
        self.core, self.frontends = core, dict(frontends)
        self.time = _clock(start_micros)
        if (not self.frontends or any(type(k) is not int or not 0 <= k < 256
                or not isinstance(v, FrontendIdentity) for k, v in self.frontends.items())):
            raise ValueError("explicit modality/frontend mapping required")
        if type(max_batch_tokens) is not int or not 1 <= max_batch_tokens <= 65536:
            raise ValueError("bounded token budget required")
        self.max_batch_tokens = max_batch_tokens
        self.last_order = -1
        self.sealed_through = -1
        self.poisoned = False

    def push(self, events):
        if self.poisoned:
            raise RuntimeError("stream needs explicit recovery after a core failure")
        if not isinstance(events, (tuple, list)) or not 1 <= len(events) <= 4096:
            raise ValueError("bounded nonempty event batch required")
        previous = (self.time, self.last_order)
        count = 0
        for event in events:
            if not isinstance(event, EncodedEvent):
                raise ValueError("encoded event required")
            current = (event.ready_micros, event.order)
            if event.ready_micros <= self.sealed_through:
                raise ValueError("query already sealed this event-time frontier")
            if current <= previous:
                raise ValueError("arrival/order must increase; replay needs explicit recovery")
            if self.frontends.get(event.modality) != event.frontend:
                raise ValueError("frontend identity differs from the common frozen frontend")
            count += len(event.tokens)
            if count > self.max_batch_tokens:
                raise ValueError("batch token budget exceeded")
            previous = current
        try:
            for event in events:
                if event.ready_micros > self.time:
                    self.core.advance((event.ready_micros-self.time)/1_000_000)
                self.core.observe(event.tokens, event.modality)
                self.time, self.last_order = event.ready_micros, event.order
        except BaseException:
            self.poisoned = True
            raise

    def query(self, query, *, at_micros):
        if self.poisoned:
            raise RuntimeError("stream needs explicit recovery after a core failure")
        if _clock(at_micros) < self.time:
            raise ValueError("cannot retrospectively query a state containing later arrivals")
        vector = np.array(query, dtype=np.float64, copy=True)
        if vector.ndim != 1 or not 1 <= len(vector) <= 65536 or not np.isfinite(vector).all():
            raise ValueError("bounded finite query vector required")
        try:
            if at_micros > self.time:
                self.core.advance((at_micros-self.time)/1_000_000)
            answer = np.array(self.core.query(vector), dtype=np.float64, copy=True)
            if answer.ndim != 1 or not 1 <= len(answer) <= 65536 or not np.isfinite(answer).all():
                raise ValueError("invalid core answer")
            if at_micros > self.time:
                self.last_order = -1
            self.time = at_micros
            self.sealed_through = at_micros
            return answer
        except BaseException:
            self.poisoned = True
            raise
