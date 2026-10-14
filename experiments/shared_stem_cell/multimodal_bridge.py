"""Research-only, pinned multimodal stem feature composition and Cell fan-out.

Consumes externally encoded text/image/audio/sensor vectors. It does NOT load a
model, confer multimodal competence, verify authorization, or execute a Cell.
All feature storage is immutable little-endian float32 bytes; bounded cache hits
return the same snapshot object and require a fresh host final-use check.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
import struct
from typing import Callable


MODALITIES = frozenset({"text", "image", "audio", "video", "sensor"})
MAX_COMMON = 512       # current Neuron model-port bound, not a multimodal optimum
MAX_DETAIL = 4096      # research sidecar limit, not Q24 drive width
MAX_MODALITIES = 5


class ContractError(ValueError):
    pass


def _digest(value: str) -> str:
    if (type(value) is not str or len(value) != 64
            or value == "0" * 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ContractError("nonzero canonical SHA-256 identity required")
    return value


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _pack(values: tuple[float, ...], maximum: int) -> bytes:
    if not 1 <= len(values) <= maximum:
        raise ContractError("bounded vector required")
    out = bytearray()
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value) or not -8 <= value <= 8:
            raise ContractError("finite, bounded vector entries required")
        out.extend(struct.pack("<f", 0.0 if value == 0 else value))
    return bytes(out)


def _unpack(data: bytes, maximum: int) -> tuple[float, ...]:
    if type(data) is not bytes or len(data) % 4 or not 4 <= len(data) <= 4 * maximum:
        raise ContractError("bounded immutable f32 bytes required")
    values = struct.unpack("<" + "f" * (len(data) // 4), data)
    _pack(values, maximum)  # also rejects nan, inf and out-of-range bytes
    return values


@dataclass(frozen=True)
class ModalityFeature:
    modality: str
    input_sha256: str
    encoder_sha256: str
    values_le_f32: bytes

    def __post_init__(self) -> None:
        if type(self.modality) is not str or self.modality not in MODALITIES:
            raise ContractError("unknown modality")
        _digest(self.input_sha256)
        _digest(self.encoder_sha256)
        _unpack(self.values_le_f32, MAX_DETAIL)

    @classmethod
    def from_vector(cls, modality: str, input_sha256: str, encoder_sha256: str,
                    values: tuple[float, ...]) -> ModalityFeature:
        return cls(modality, input_sha256, encoder_sha256, _pack(values, MAX_DETAIL))

    @property
    def values(self) -> tuple[float, ...]:
        return _unpack(self.values_le_f32, MAX_DETAIL)

    @property
    def feature_sha256(self) -> str:
        return hashlib.sha256(self.values_le_f32).hexdigest()


@dataclass(frozen=True)
class FrozenLinearBridge:
    """Externally fitted projection weights; never a randomly generated fallback."""
    modality: str
    rows: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]

    def __post_init__(self) -> None:
        if type(self.modality) is not str or self.modality not in MODALITIES or not self.rows or len(self.rows) > MAX_COMMON:
            raise ContractError("invalid projection modality/target width")
        width = len(self.rows[0])
        if not 1 <= width <= MAX_DETAIL or width * len(self.rows) > 262144:
            raise ContractError("projection parameter budget exceeded")
        if len(self.bias) != len(self.rows) or any(len(row) != width for row in self.rows):
            raise ContractError("projection dimensions mismatch")
        for values in (*self.rows, self.bias):
            _pack(values, MAX_DETAIL)

    @property
    def sha256(self) -> str:
        return _hash(["hepta.frozen-linear-bridge.v1", self.modality,
                      [hashlib.sha256(_pack(row, MAX_DETAIL)).hexdigest() for row in self.rows],
                      hashlib.sha256(_pack(self.bias, MAX_COMMON)).hexdigest()])

    def project(self, feature: ModalityFeature) -> tuple[float, ...]:
        if feature.modality != self.modality or len(feature.values) != len(self.rows[0]):
            raise ContractError("cross-modality or width-drift projection")
        values = feature.values
        out = tuple(math.fsum(a * b for a, b in zip(row, values)) + bias
                    for row, bias in zip(self.rows, self.bias))
        return _unpack(_pack(out, MAX_COMMON), MAX_COMMON)


@dataclass(frozen=True)
class StemKey:
    scope: str
    generation: int
    fence_sha256: str
    stem_sha256: str
    preprocessor_sha256: str
    bridge_sha256: str
    input_sha256: str

    def __post_init__(self) -> None:
        if (type(self.scope) is not str or not 1 <= len(self.scope.encode()) <= 128
                or any(ord(c) < 33 or ord(c) > 126 for c in self.scope)
                or type(self.generation) is not int or not 1 <= self.generation <= 2**63 - 1):
            raise ContractError("invalid scope or generation")
        for value in (self.fence_sha256, self.stem_sha256, self.preprocessor_sha256,
                      self.bridge_sha256, self.input_sha256):
            _digest(value)


@dataclass(frozen=True)
class FeatureSnapshot:
    key: StemKey
    common_le_f32: bytes
    detail: tuple[ModalityFeature, ...]
    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _unpack(self.common_le_f32, MAX_COMMON)
        if not 1 <= len(self.detail) <= MAX_MODALITIES:
            raise ContractError("bounded detail channels required")
        tags = [item.modality for item in self.detail]
        if tags != sorted(set(tags)):
            raise ContractError("duplicate or noncanonical modality order")
        object.__setattr__(self, "content_sha256", self._content_digest())

    def _content_digest(self) -> str:
        return _hash(["hepta.multimodal-stem-snapshot.v1", vars(self.key),
                      hashlib.sha256(self.common_le_f32).hexdigest(),
                      [[p.modality, p.input_sha256, p.encoder_sha256, p.feature_sha256]
                       for p in self.detail]])

    def verify(self) -> None:
        self.key.__post_init__()
        _unpack(self.common_le_f32, MAX_COMMON)
        if self._content_digest() != self.content_sha256:
            raise ContractError("changed snapshot content")

    def shared_view(self) -> memoryview:
        self.verify()
        return memoryview(self.common_le_f32)

    def neuron_q24(self) -> tuple[int, ...]:
        """Explicit Q24 boundary, signed nearest/even as Python round specifies."""
        self.verify()
        return tuple(round(value * (1 << 24))
                     for value in _unpack(self.common_le_f32, MAX_COMMON))

    @property
    def charged_bytes(self) -> int:
        return len(self.common_le_f32) + sum(len(x.values_le_f32) for x in self.detail)


class SharedStemComposer:
    def __init__(self, stem_sha256: str, preprocessor_sha256: str,
                 bridges: tuple[FrozenLinearBridge, ...]):
        self.stem_sha256 = _digest(stem_sha256)
        self.preprocessor_sha256 = _digest(preprocessor_sha256)
        if not 1 <= len(bridges) <= MAX_MODALITIES:
            raise ContractError("bounded bridge inventory required")
        modalities = [x.modality for x in bridges]
        if modalities != sorted(set(modalities)) or len({len(x.rows) for x in bridges}) != 1:
            raise ContractError("ordered unique projections with equal output width required")
        self.bridges = {x.modality: x for x in bridges}
        self.bridge_sha256 = _hash(["hepta.multimodal-bridge-inventory.v1",
                                    [[x.modality, x.sha256] for x in bridges]])

    def key(self, scope: str, generation: int, fence_sha256: str,
            detail: tuple[ModalityFeature, ...]) -> StemKey:
        self._check_detail(detail)
        inp = _hash(["hepta.multimodal-input.v1", [[x.modality, x.input_sha256,
                     x.encoder_sha256, x.feature_sha256] for x in detail]])
        return StemKey(scope, generation, fence_sha256, self.stem_sha256,
                       self.preprocessor_sha256, self.bridge_sha256, inp)

    def _check_detail(self, detail: tuple[ModalityFeature, ...]) -> None:
        mods = [x.modality for x in detail]
        if not mods or mods != sorted(set(mods)) or not set(mods) <= set(self.bridges):
            raise ContractError("unregistered or unordered multimodal inputs")

    def compose(self, key: StemKey, detail: tuple[ModalityFeature, ...]) -> FeatureSnapshot:
        current_bridge = _hash(["hepta.multimodal-bridge-inventory.v1",
                                [[x.modality, x.sha256] for x in self.bridges.values()]])
        if current_bridge != self.bridge_sha256:
            raise ContractError("frozen projection changed after registration")
        if key != self.key(key.scope, key.generation, key.fence_sha256, detail):
            raise ContractError("unbound source, generation or bridge identity")
        projections = [self.bridges[feature.modality].project(feature) for feature in detail]
        # Mean fusion is a deliberately weak baseline, not attention or an optimum.
        values = tuple(math.fsum(x[i] for x in projections) / len(projections)
                       for i in range(len(projections[0])))
        return FeatureSnapshot(key, _pack(values, MAX_COMMON), detail)


class BoundedStemCache:
    """Research fan-out, not an authorization owner or cross-process memory pool."""
    def __init__(self, max_bytes: int):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 256 * 1024 * 1024:
            raise ContractError("cache size outside bounds")
        self.max_bytes = max_bytes
        self.items: OrderedDict[StemKey, FeatureSnapshot] = OrderedDict()
        self.bytes = self.hits = self.producer_calls = self.evictions = 0

    def get(self, key: StemKey, producer: Callable[[], FeatureSnapshot],
            final_use: Callable[[StemKey], bool]) -> FeatureSnapshot:
        if not callable(final_use) or final_use(key) is not True:
            raise ContractError("fresh external final-use permission required")
        if key in self.items:
            value = self.items[key]
            value.verify()
            self.items.move_to_end(key)
            self.hits += 1
        else:
            value = producer()
            self.producer_calls += 1
            if not isinstance(value, FeatureSnapshot) or value.key != key:
                raise ContractError("producer key differs from admitted request")
            value.verify()
            charge = value.charged_bytes
            if charge <= self.max_bytes:
                while self.items and self.bytes + charge > self.max_bytes:
                    _, old = self.items.popitem(last=False)
                    self.bytes -= old.charged_bytes
                    self.evictions += 1
                self.items[key] = value
                self.bytes += charge
        if final_use(key) is not True:
            raise ContractError("revoked before final use")
        return value

    def clear(self) -> None:
        self.items.clear()
        self.bytes = 0
