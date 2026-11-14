"""Hepta Cell Fabric P0: isolated, DENY_ALL numerical research mechanisms.

Neither digests nor returned receipts authenticate an OS observer or grant effects.
No pretrained weights, learned reasoning, multimodal generation, or FBSDE theorem
is claimed by this reference implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import time
from typing import Callable

Q24 = 1 << 24
LIMIT = 8 * Q24


class Denied(ValueError):
    """Fail-closed admission or capability rejection."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: str) -> str:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise Denied("non-canonical digest")
    return value


@dataclass(frozen=True)
class StemSpec:
    model_digest: str
    preprocess_digest: str
    quantization_digest: str
    width: int
    generation: int
    epoch: int

    def __post_init__(self) -> None:
        for v in (self.model_digest, self.preprocess_digest, self.quantization_digest):
            digest(v)
        if not 1 <= self.width <= 384 or self.generation <= 0 or self.epoch <= 0:
            raise Denied("invalid stem identity")


@dataclass(frozen=True)
class Observation:
    payload: bytes
    principal: str
    purpose: str
    modality: str
    generation: int
    epoch: int
    expiry_ns: int
    declared_source_digest: str

    def verify(self, spec: StemSpec, now_ns: int, allowed: bool) -> None:
        if not allowed or self.generation != spec.generation or self.epoch != spec.epoch:
            raise Denied("unauthorized or stale generation")
        if now_ns >= self.expiry_ns or self.expiry_ns <= 0 or now_ns < 0:
            raise Denied("expired observation")
        if not self.principal or not self.purpose or self.modality not in {"text", "image", "audio", "video"}:
            raise Denied("invalid scope or modality")
        if len(self.payload) == 0 or len(self.payload) > 1_048_576:
            raise Denied("invalid source length")
        if digest(self.declared_source_digest) != sha(self.payload):
            raise Denied("source changed")


@dataclass(frozen=True)
class Feature:
    values_q24: tuple[int, ...]
    source_digest: str
    stem_digest: str


class StemBank:
    """Counts actual external encoder calls; borrows are separately admitted."""

    def __init__(self, spec: StemSpec, encode: Callable[[bytes], tuple[int, ...]]):
        self.spec = spec
        self.encode = encode
        self._cache: dict[tuple[object, ...], Feature] = {}
        self.forward_calls = 0
        self.cache_hits = 0

    def borrow(self, obs: Observation, now_ns: int, *, allowed: bool) -> Feature:
        obs.verify(self.spec, now_ns, allowed)
        key = (obs.principal, obs.purpose, obs.modality, obs.generation,
               obs.epoch, self.spec.model_digest, self.spec.preprocess_digest,
               self.spec.quantization_digest, obs.declared_source_digest)
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        result = tuple(self.encode(obs.payload))
        if len(result) != self.spec.width or any(
            type(v) is not int or abs(v) > LIMIT for v in result
        ):
            raise Denied("non-canonical encoder features")
        self.forward_calls += 1
        feature = Feature(result, obs.declared_source_digest, self.spec.model_digest)
        if len(self._cache) >= 4096:
            self._cache.clear()  # bounded, no cross-generation implicit migration
        self._cache[key] = feature
        return feature


def round_q24(numerator: int) -> int:
    sign = -1 if numerator < 0 else 1
    n = abs(numerator)
    whole, rem = divmod(n, Q24)
    if 2 * rem > Q24 or (2 * rem == Q24 and whole % 2):
        whole += 1
    return sign * whole


def q24_dot(features: tuple[int, ...], weights: tuple[int, ...]) -> int:
    if not 1 <= len(features) <= 16 or len(features) != len(weights):
        raise Denied("invalid dot dimension")
    if any(type(x) is not int or abs(x) > LIMIT for x in features + weights):
        raise Denied("invalid Q24 inputs")
    return round_q24(sum(a * b for a, b in zip(features, weights)))


@dataclass(frozen=True)
class Head:
    cell_id: str
    stem_digest: str
    weights_q24: tuple[int, ...]

    def evaluate(self, feature: Feature) -> int:
        if not self.cell_id or self.stem_digest != feature.stem_digest:
            raise Denied("Head/Stem mismatch")
        return q24_dot(feature.values_q24, self.weights_q24)


@dataclass(frozen=True)
class Edge:
    probability: Fraction
    reward: Fraction
    successor: str


@dataclass(frozen=True)
class Choice:
    name: str
    cost_units: int
    edges: tuple[Edge, ...]


@dataclass(frozen=True)
class Decision:
    action: str
    value: Fraction
    all_values: tuple[tuple[str, Fraction], ...]
    visited_states: int


class FiniteNdu:
    """Exact finite public-information Bellman reference, NOT a stochastic FBSDE."""

    def __init__(self, graph: dict[str, tuple[Choice, ...]], terminal: dict[str, Fraction],
                 *, discount: Fraction = Fraction(1), max_depth: int = 4):
        if not isinstance(discount, Fraction) or not Fraction(0) < discount <= 1 or not 1 <= max_depth <= 4:
            raise Denied("invalid NDU profile")
        if len(graph) > 128 or len(terminal) > 128:
            raise Denied("unbounded NDU graph")
        for state, choices in graph.items():
            if not state or not choices or len(choices) > 8 or len({a.name for a in choices}) != len(choices):
                raise Denied("invalid actions")
            if not any(a.name == "stop" for a in choices):
                raise Denied("stop is mandatory")
            for action in choices:
                if not action.name or not 1 <= action.cost_units <= 16 or not 1 <= len(action.edges) <= 8:
                    raise Denied("invalid action budget")
                if any(not isinstance(e.probability, Fraction) or not isinstance(e.reward, Fraction) or e.probability.denominator > 1_000_000 or e.reward.denominator > 1_000_000 for e in action.edges):
                    raise Denied("unsupported stochastic precision")
                if action.name == "stop" and any(e.successor not in terminal for e in action.edges):
                    raise Denied("stop must terminate")
                if sum((e.probability for e in action.edges), Fraction()) != 1:
                    raise Denied("non-normalized probability")
                if any(e.probability < 0 or abs(e.reward) > 100 or e.successor not in graph and e.successor not in terminal for e in action.edges):
                    raise Denied("invalid transition")
        if any(not isinstance(v, Fraction) or abs(v) > 100 for v in terminal.values()):
            raise Denied("invalid terminal outcome")
        self.graph, self.terminal = graph, terminal
        self.discount, self.max_depth = discount, max_depth

    def choose(self, state: str, budget: int) -> Decision:
        if state not in self.graph or not 1 <= budget <= 16:
            raise Denied("state or budget unsupported")
        visited = 0
        cache: dict[tuple[str, int, int], Fraction] = {}

        def score(at: str, left: int, depth: int) -> Fraction:
            nonlocal visited
            if at in self.terminal:
                return self.terminal[at]
            if depth == 0:
                return Fraction(0)  # explicit zero-valued horizon truncation
            key = (at, left, depth)
            if key in cache:
                return cache[key]
            visited += 1
            if visited > 512:
                raise Denied("NDU state expansion limit")
            possible: list[Fraction] = []
            for a in self.graph[at]:
                if a.cost_units > left:
                    continue
                expected = sum((e.probability * (e.reward + self.discount * score(e.successor, left - a.cost_units, depth - 1)) for e in a.edges), Fraction())
                possible.append(expected)
            if not possible:
                raise Denied("no affordable legal action")
            cache[key] = max(possible)
            return cache[key]

        evaluated = []
        for a in self.graph[state]:
            if a.cost_units <= budget:
                value = sum((e.probability * (e.reward + self.discount * score(e.successor, budget - a.cost_units, self.max_depth - 1)) for e in a.edges), Fraction())
                evaluated.append((a.name, value))
        if not evaluated:
            raise Denied("no affordable action")
        # Deterministic stable tie rule, favor explicit stop on ties.
        winner = max(evaluated, key=lambda pair: (pair[1], pair[0] == "stop"))
        return Decision(winner[0], winner[1], tuple(evaluated), visited)


@dataclass(frozen=True)
class ContractionCertificate:
    approximation: Fraction
    residual: Fraction
    error_bound: Fraction
    iterations: int


def certify_scalar_contraction(*, fixed_reward: Fraction, q: Fraction,
                               max_steps: int = 64, tolerance: Fraction = Fraction(1, 1 << 20)) -> ContractionCertificate:
    """Certified scalar map F(y)=reward+q*y; not global/coupled FBSDE well-posedness."""
    if (not all(isinstance(x, Fraction) for x in (fixed_reward, q, tolerance))
            or abs(fixed_reward) > 1_000_000 or q.denominator > 1_000_000
            or not Fraction(0) <= q < Fraction(3, 4)
            or not 1 <= max_steps <= 64 or tolerance <= 0):
        raise Denied("unqualified contraction")
    value = Fraction(0)
    for step in range(1, max_steps + 1):
        residual = abs(fixed_reward + q * value - value)
        bound = residual / (1 - q)
        if bound <= tolerance:
            return ContractionCertificate(value, residual, bound, step)
        value = fixed_reward + q * value
    raise Denied("contraction solver exhausted")


def make_synthetic_encoder(width: int) -> Callable[[bytes], tuple[int, ...]]:
    """Deliberately non-pretrained deterministic CPU input (only for mechanism tests)."""
    if not 1 <= width <= 16:
        raise Denied("toy only accepts width <= 16")
    def encode(payload: bytes) -> tuple[int, ...]:
        out = []
        for i in range(width):
            h = hashlib.sha256(i.to_bytes(2, "big") + payload).digest()
            out.append((int.from_bytes(h[:4], "big") % (2 * Q24 + 1)) - Q24)
        return tuple(out)
    return encode


def synthetic_head(i: int, stem_digest: str, width: int) -> Head:
    weights = tuple((((i * 17 + j * 31) % 31) - 15) * (Q24 // 32) for j in range(width))
    return Head(f"cell-{i}", stem_digest, weights)


def percentile_ns(values: list[int], fraction: float) -> int:
    if not values:
        raise Denied("no measured values")
    return sorted(values)[math.ceil((len(values) - 1) * fraction)]


def physical_shadow_bench(cell_count: int, repetitions: int = 16) -> dict[str, object]:
    """Physical CPU toy encoder + all Cell head calls; no real model/GUI."""
    if cell_count not in {64, 256, 1024, 4096} or not 4 <= repetitions <= 128:
        raise Denied("benchmark profile")
    stem = sha(b"real-frozen-stem-identity-not-a-pretrained-claim")
    spec = StemSpec(stem, sha(b"toy-preprocessor"), sha(b"toy-q24"), 16, 1, 1)
    bank = StemBank(spec, make_synthetic_encoder(16))
    payload = b"immutable synthetic input only"
    obs = Observation(payload, "isolated-test", "research", "text", 1, 1,
                      (1 << 63) - 1, sha(payload))
    heads = tuple(synthetic_head(i, stem, 16) for i in range(cell_count))
    samples = []
    checksum = 0
    for _ in range(repetitions):
        t0 = time.perf_counter_ns()
        for head in heads:
            feat = bank.borrow(obs, time.monotonic_ns(), allowed=True)
            checksum = (checksum * 0x100000001B3 + (head.evaluate(feat) & ((1 << 64) - 1))) & ((1 << 64) - 1)
        samples.append(time.perf_counter_ns() - t0)
    return {"kind": "real_cpu_synthetic_model_mechanism_only",
            "cell_count": cell_count, "repetitions": repetitions,
            "unique_encoder_forwards": bank.forward_calls,
            "cache_borrows": bank.cache_hits,
            "actual_head_calls": cell_count * repetitions,
            "p50_ns": percentile_ns(samples, 0.50),
            "p95_ns": percentile_ns(samples, 0.95),
            "p99_ns": percentile_ns(samples, 0.99),
            "checksum": checksum, "authority": "DENY_ALL",
            "no_model_quality_or_effect_claim": True}
