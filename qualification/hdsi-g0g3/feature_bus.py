"""Research-only scoped shared-feature fanout, NOT a production Encoder or authority provider.

The encoder callback must provide genuine, separately attested model work. Every
borrow (including a cache hit) is checked against a caller-supplied current-use
policy. Input, model and preprocessing identity are inseparable from scope.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Callable

MAX_BORROWERS = 4096
MAX_VECTOR = 1024
MAX_INPUT = 8192
MAX_UNIQUE = 1024


class Denied(ValueError):
    pass


def canon(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Denied("noncanonical content") from exc


def digest(value: object) -> str:
    return hashlib.sha256(b"hepta.hdsi.feature.v1\0" + canon(value)).hexdigest()


def _sha(s: object) -> bool:
    return type(s) is str and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _ident(s: object) -> bool:
    return (type(s) is str and 1 <= len(s) <= 96 and s.isascii()
            and all(c.isalnum() or c in ".:-_" for c in s))


@dataclass(frozen=True)
class Scope:
    principal: str
    purpose: str
    generation: int
    epoch: int
    revocation: str
    model_sha: str
    preprocess_sha: str

    def validate(self) -> None:
        if not (_ident(self.principal) and _ident(self.purpose)
                and type(self.generation) is int and 0 < self.generation < 2**63
                and type(self.epoch) is int and 0 <= self.epoch < 2**63
                and _sha(self.revocation) and _sha(self.model_sha)
                and _sha(self.preprocess_sha)):
            raise Denied("invalid scoped model material or fence")


@dataclass(frozen=True)
class Borrow:
    scope: Scope
    modality: str
    payload: bytes
    cell_id: str
    approved_use: str

    def validate(self) -> None:
        self.scope.validate()
        if (self.modality not in ("text", "image", "audio", "video")
                or type(self.payload) is not bytes or not 1 <= len(self.payload) <= MAX_INPUT
                or not _ident(self.cell_id) or not _ident(self.approved_use)):
            raise Denied("invalid borrow identity or input bytes")


@dataclass(frozen=True)
class Receipt:
    key: str
    model_sha: str
    input_sha: str
    values: tuple[float, ...]
    cache_hit: bool


class SharedFeatureBus:
    """Bounded per-process study. Callback is mandatory on EVERY borrow."""

    def __init__(self, width: int, encoder: Callable[[bytes, str], tuple[float, ...]],
                 allow_use: Callable[[Borrow], bool],
                 batch_encode: Callable[[list[tuple[bytes, str]]], list[tuple[float, ...]]] | None = None) -> None:
        if type(width) is not int or not 1 <= width <= MAX_VECTOR:
            raise Denied("width must be bounded")
        if not callable(encoder) or not callable(allow_use):
            raise Denied("encoder and authority adapter are required")
        self.width = width
        self._encode = encoder
        self._allowed = allow_use
        if batch_encode is not None and not callable(batch_encode):
            raise Denied("batch encoder must be callable")
        self._batch_encode = batch_encode
        self._cache: dict[str, tuple[float, ...]] = {}
        self.physical_calls = 0
        self.borrow_count = 0

    def fanout(self, borrows: list[Borrow]) -> list[Receipt]:
        if type(borrows) is not list or not 1 <= len(borrows) <= MAX_BORROWERS:
            raise Denied("bounded borrower fleet required")
        # Preflight all entries and all revocation decisions before any forward.
        keys: list[tuple[Borrow, str, str]] = []
        unique = set()
        for b in borrows:
            if type(b) is not Borrow:
                raise Denied("typed borrow required")
            b.validate()
            if self._allowed(b) is not True:
                raise Denied("current-use authorization denied")
            input_sha = hashlib.sha256(b.payload).hexdigest()
            key = digest({"scope": vars(b.scope), "modality": b.modality,
                          "payload_sha256": input_sha})
            unique.add(key)
            keys.append((b, key, input_sha))
        if len(unique) > MAX_UNIQUE or len(unique | self._cache.keys()) > MAX_UNIQUE:
            raise Denied("unique physical encoder budget")
        # Stage all new encodings; failed model output cannot partially
        # publish a cache generation or report a completed logical borrow.
        new: dict[str, tuple[float, ...]] = {}
        missing = [(b, key) for b, key, _ in keys
                   if key not in self._cache and key not in new]
        # Preserve first-seen order and remove duplicates before the model call.
        missing = list({key: (b, key) for b, key in missing}.values())
        if self._batch_encode is not None and missing:
            results = self._batch_encode([(b.payload, b.modality) for b, _ in missing])
            if type(results) is not list or len(results) != len(missing):
                raise Denied("incorrect batch encoder cardinality")
        else:
            results = [self._encode(b.payload, b.modality) for b, _ in missing]
        for (b, key), raw in zip(missing, results):
            if (type(raw) is not tuple or len(raw) != self.width
                    or any(type(v) not in (float, int) or not math.isfinite(v)
                           or abs(v) > 8 for v in raw)):
                raise Denied("invalid actual encoder values")
            new[key] = tuple(float(v) for v in raw)
        # Recheck immediately before publication: authorization can be
        # revoked during a slow pretrained batch forward. Cost may already
        # have been incurred, but no stale feature may be returned or cached.
        for b, _, _ in keys:
            if self._allowed(b) is not True:
                raise Denied("current-use authority changed before publication")
        seen = set(self._cache)
        outputs = []
        for b, key, input_sha in keys:
            outputs.append(Receipt(key, b.scope.model_sha, input_sha,
                                   self._cache.get(key, new.get(key)), key in seen))
            seen.add(key)
        self._cache.update(new)
        self.physical_calls += len(new)  # distinct physically computed SEQUENCES, not batches
        self.borrow_count += len(keys)
        return outputs

    def invalidate(self) -> None:
        self._cache.clear()

    @property
    def resident_features(self) -> int:
        return len(self._cache)
