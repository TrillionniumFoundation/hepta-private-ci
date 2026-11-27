"""Typed local research-memory results; parameter recall has a separate origin."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value, limit=128):
    if (
        type(value) is not str
        or not 1 <= len(value.encode()) <= limit
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value) is None
    ):
        raise ValueError("bounded stable identifier required")
    return value


def key(entity, relation):
    for value, maximum in ((entity, 64), (relation, 32)):
        if (
            type(value) is not str
            or not 1 <= len(value) <= maximum
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value) is None
        ):
            raise ValueError("catalog-compatible entity and relation required")
    return entity, relation


class ReadStatus(str, Enum):
    ANSWERED = "answered"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"
    INDETERMINATE = "indeterminate"


class MemoryCellRoleV1(str, Enum):
    """Implemented local roles; each owns a separately bound source history."""

    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class SourceConflict(ValueError):
    """A source revision does not match the caller's expected predecessor."""


class LeaseLost(ValueError):
    """A worker no longer owns the training attempt it is trying to publish."""


@dataclass(frozen=True)
class ReadResult:
    status: ReadStatus
    answer: str | None
    origin: str
    source_roots: tuple[str, ...]
    source_ids: tuple[str, ...]
    source_epoch: int


@dataclass(frozen=True)
class WriteReceipt:
    operation: str
    source_id: str
    revision: int
    source_digest: str
    source_epoch: int
    training_job_id: int | None


def verify_snapshot(snapshot):
    material = {k: v for k, v in snapshot.items() if k != "digest"}
    if snapshot.get("digest") != digest(material):
        raise ValueError("training snapshot content changed")
    return snapshot
