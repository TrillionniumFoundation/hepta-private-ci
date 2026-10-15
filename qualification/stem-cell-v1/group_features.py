"""Research-only V2 feature references; the native Q24 V1 ABI is unchanged.

Identities must describe all output-affecting inputs: pin model weights/config,
hash tokenizer assets, and hash preprocessing (including truncation, pooling,
precision and adapter configuration). Source digests cover the actual input.
Numeric byte limits describe canonical payload bytes, not Python heap usage.
"""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
import re
import struct
from threading import RLock


def content_digest(data):
    """Hash actual source/config bytes rather than a human-readable label."""
    if not isinstance(data, bytes):
        raise TypeError("digest input must be bytes")
    return sha256(data).hexdigest()


@dataclass(frozen=True)
class FeatureIdentity:
    scope: str
    generation: int
    model_revision: str
    tokenizer_digest: str
    preprocess_digest: str
    source_digest: str
    modality: str

    def __post_init__(self):
        for value in (self.scope, self.model_revision):
            if not isinstance(value, str) or not value or len(value) > 512:
                raise ValueError("scope and pinned model revision must be bounded strings")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a nonnegative integer")
        for value in (self.tokenizer_digest, self.preprocess_digest, self.source_digest):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("identity digests must be SHA256 hex of actual content")
        if self.modality not in {"text", "image", "audio", "video", "multimodal"}:
            raise ValueError("unsupported modality")


def _materialize(value):
    # Tensor support is duck typed and imports no numerical runtime. Detach and
    # clone before reading so neither an autograd graph nor external storage is kept.
    if hasattr(value, "detach"):
        value = value.detach().clone().cpu()
    return value.tolist() if hasattr(value, "tolist") else value


def _matrix(value, rows, width):
    shape = getattr(value, "shape", None)
    if shape is not None and (len(shape) != 2 or not 0 < shape[0] <= rows or not 0 < shape[1] <= width):
        raise ValueError("matrix shape exceeds bounds")
    value = _materialize(value)
    if not isinstance(value, (list, tuple)) or not 0 < len(value) <= rows:
        raise ValueError("matrix row count exceeds bounds")
    result = []
    for row in value:
        if not isinstance(row, (list, tuple)) or not 0 < len(row) <= width:
            raise ValueError("matrix width exceeds bounds")
        try:
            row = tuple(float(x) for x in row)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("matrix values must be finite numbers") from exc
        if any(not math.isfinite(x) for x in row):
            raise ValueError("matrix values must be finite")
        if result and len(row) != len(result[0]):
            raise ValueError("ragged matrix")
        result.append(row)
    return tuple(result)


def _vector(value, length):
    shape = getattr(value, "shape", None)
    if shape is not None and (len(shape) != 1 or shape[0] != length):
        raise ValueError("vector shape mismatch")
    value = _materialize(value)
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError("vector length mismatch")
    return tuple(value)


@dataclass(frozen=True)
class FeatureSnapshotV2:
    identity: FeatureIdentity
    tokens: object
    mask: object
    positions: object = None
    timestamps: object = None
    digest: str = field(init=False)
    nbytes: int = field(init=False)

    def __post_init__(self):
        if not isinstance(self.identity, FeatureIdentity):
            raise TypeError("FeatureIdentity required")
        tokens = _matrix(self.tokens, 256, 512)
        count = len(tokens)
        mask = _vector(self.mask, count)
        if any(x not in (0, 1, False, True) for x in mask) or not any(mask):
            raise ValueError("mask must be binary and include a valid token")
        mask = tuple(bool(x) for x in mask)
        positions = None
        if self.positions is not None:
            positions = _matrix(self.positions, count, 3)
            if len(positions) != count or any(x < 0 or x > 2**31 - 1 or not x.is_integer() for row in positions for x in row):
                raise ValueError("positions require one bounded integer coordinate row per token")
        timestamps = None
        if self.timestamps is not None:
            try:
                timestamps = tuple(float(x) for x in _vector(self.timestamps, count))
            except (TypeError, OverflowError) as exc:
                raise ValueError("timestamps must be finite numbers") from exc
            if any(not math.isfinite(x) or x < 0 for x in timestamps):
                raise ValueError("timestamps must be finite and nonnegative")
            if any(a > b for a, b in zip(timestamps, timestamps[1:])):
                raise ValueError("timestamps must be ordered")
        for name, value in (("tokens", tokens), ("mask", mask), ("positions", positions), ("timestamps", timestamps)):
            object.__setattr__(self, name, value)
        metadata = {"version": 2, "identity": asdict(self.identity), "shape": self.shape,
                    "position_width": len(positions[0]) if positions else 0,
                    "has_timestamps": timestamps is not None}
        payload = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        payload += bytes(mask)
        for values in (tokens, positions):
            if values is not None:
                payload += b"".join(struct.pack("<d", x) for row in values for x in row)
        if timestamps is not None:
            payload += b"".join(struct.pack("<d", x) for x in timestamps)
        object.__setattr__(self, "digest", content_digest(payload))
        object.__setattr__(self, "nbytes", len(payload))

    @property
    def shape(self):
        return len(self.tokens), len(self.tokens[0])


class FeatureCache:
    """One immutable encoding per identity for a bounded scope/generation.

    Reject capacity overflow rather than silently evict and re-encode. Start a
    new generation/cache when the request or model state changes.
    """

    def __init__(self, scope, generation, max_entries=64, max_bytes=64 * 1024 * 1024):
        if type(max_entries) is not int or max_entries <= 0 or type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("cache bounds must be positive integers")
        self.scope, self.generation = scope, generation
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries, self._bytes, self._lock = {}, 0, RLock()

    def get_or_encode(self, identity, factory):
        if not isinstance(identity, FeatureIdentity) or (identity.scope, identity.generation) != (self.scope, self.generation):
            raise ValueError("feature scope/generation mismatch")
        with self._lock:
            if identity in self._entries:
                return self._entries[identity]
            if len(self._entries) >= self.max_entries:
                raise ValueError("feature cache entry bound exceeded")
            snapshot = factory()
            if not isinstance(snapshot, FeatureSnapshotV2) or snapshot.identity != identity:
                raise ValueError("factory returned another feature identity")
            if self._bytes + snapshot.nbytes > self.max_bytes:
                raise ValueError("feature cache byte bound exceeded")
            self._entries[identity] = snapshot
            self._bytes += snapshot.nbytes
            return snapshot

    @property
    def nbytes(self):
        return self._bytes


class BoundedWorkspace:
    """Current immutable recurrent state only; no unbounded history or graph."""

    def __init__(self, scope, generation, slots=32, width=384, max_steps=8, max_bytes=1024 * 1024):
        if not isinstance(scope, str) or not scope or type(generation) is not int or generation < 0:
            raise ValueError("valid scope/generation required")
        if any(type(x) is not int or x <= 0 for x in (slots, width, max_steps, max_bytes)):
            raise ValueError("workspace bounds must be positive integers")
        if slots > 256 or width > 512 or max_steps > 256 or slots * width * 8 > max_bytes:
            raise ValueError("workspace exceeds hard bounds or byte budget")
        self.scope, self.generation = scope, generation
        self.slots, self.width, self.max_steps, self.max_bytes = slots, width, max_steps, max_bytes
        self._state, self._step = (), 0

    def write(self, step, slots, *, scope, generation):
        if (scope, generation) != (self.scope, self.generation):
            raise ValueError("workspace scope/generation mismatch")
        if type(step) is not int or step != self._step + 1 or step > self.max_steps:
            raise ValueError("workspace steps must advance sequentially within bounds")
        state = _matrix(slots, self.slots, self.width)
        if len(state[0]) != self.width:
            raise ValueError("workspace width mismatch")
        self._state, self._step = state, step
        return self._state

    @property
    def state(self):
        return self._state

    @property
    def step(self):
        return self._step

    @property
    def nbytes(self):
        return len(self._state) * self.width * 8
