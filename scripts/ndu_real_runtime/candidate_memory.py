"""Bounded development candidate memory using only released actor inputs.

Current candidates precede distinct historical candidates, newest observation
first. Greedy admission skips records that exceed the byte/entry budget. Boxes
remain in original-image coordinates; no ROI transform or new OCR is performed.
Serialized resident bytes are a logical measure, not Python RAM or physical cost.
This module does not change the frozen actor, evaluator or scientific HOLD.
"""

from dataclasses import asdict, dataclass, replace
import json
import math
import re
import time


FEATURE_WIDTH = 126
ORIGINS = {"pixel_ocr", "registered_public_text", "no_recognized_text"}


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _size(value):
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


@dataclass(frozen=True)
class CandidateScope:
    original_operation_id: str
    case_id: str
    source_image_sha256: str
    source_width: int
    source_height: int

    def __post_init__(self):
        for value in (self.original_operation_id, self.case_id):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.encode()) > 256
            ):
                raise ValueError(
                    "bounded nonempty operation and case identities required"
                )
        if not isinstance(self.source_image_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.source_image_sha256
        ):
            raise ValueError("canonical source image SHA-256 required")
        if not all(
            _integer(v, 1, 1_000_000) for v in (self.source_width, self.source_height)
        ):
            raise ValueError("bounded positive original-image dimensions required")


@dataclass(frozen=True)
class CandidateRecord:
    text: str
    bbox: tuple
    origin: str
    features: tuple
    observed_step: int
    scope: CandidateScope

    @property
    def key(self):
        return self.text, self.bbox, self.origin


@dataclass(frozen=True)
class MemoryReceipt:
    status: str
    scope_reset: bool
    reset_discarded: int
    input_candidates: int
    duplicate_candidates: int
    byte_dropped: int
    entry_dropped: int
    resident_entries: int
    resident_serialized_bytes: int
    decision_cpu_seconds: float
    decision_wall_seconds: float
    policy: str = "current_then_recent_distinct_v1"
    full_physical_cost_known: bool = False
    scientific_acceptance: str = "HOLD"


@dataclass(frozen=True)
class MemoryDecision:
    records: tuple
    receipt: MemoryReceipt


class CandidateMemoryError(ValueError):
    """Rejected actor inputs carry the cost and remaining resident-state count."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


def _record(scope, step, metadata, features):
    if not isinstance(metadata, dict) or set(metadata) != {"text", "bbox", "origin"}:
        raise ValueError("only public text, bbox and origin metadata are accepted")
    text, box, origin = metadata["text"], metadata["bbox"], metadata["origin"]
    if not isinstance(text, str) or len(text.encode()) > 8192:
        raise ValueError("candidate text exceeds its UTF-8 bound")
    if not isinstance(origin, str) or origin not in ORIGINS:
        raise ValueError("unknown public candidate origin")
    if not text and origin != "no_recognized_text":
        raise ValueError("only the no-recognized-text observation may be empty")
    if (
        not isinstance(box, (list, tuple))
        or len(box) != 4
        or not all(_integer(value, 0, 1_000_000) for value in box)
    ):
        raise ValueError("four bounded original-image integer coordinates required")
    x1, y1, x2, y2 = box
    if not (x1 < x2 <= scope.source_width and y1 < y2 <= scope.source_height):
        raise ValueError("candidate bbox lies outside the original image")
    if not isinstance(features, (list, tuple)) or len(features) != FEATURE_WIDTH:
        raise ValueError("exactly 126 public candidate features required")
    if any(
        type(value) not in (int, float) or not math.isfinite(value)
        for value in features
    ):
        raise ValueError("features must be finite real numbers, never booleans")
    return CandidateRecord(
        text, tuple(box), origin, tuple(map(float, features)), step, scope
    )


class CandidateMemory:
    """Single-actor bounded pool; observations must advance within each scope.

    A scope change clears the pool before candidate validation, including a
    rejected new observation. Other rejected calls preserve the current pool.
    Byte accounting covers the canonical JSON scope and complete record roster.
    """

    def __init__(self, *, max_serialized_bytes, max_entries=128):
        self._empty_bytes = _size({"scope": None, "records": []})
        if not _integer(max_entries, 1, 128):
            raise ValueError("entry cap must be an integer in [1,128]")
        if not _integer(max_serialized_bytes, self._empty_bytes, 16 * 1024**2):
            raise ValueError("an explicit bounded serialized-byte budget is required")
        self._max_entries, self._max_serialized_bytes = (
            max_entries,
            max_serialized_bytes,
        )
        self._scope, self._last_step, self._records = None, None, ()
        self._resident_bytes = self._empty_bytes

    @property
    def max_entries(self):
        return self._max_entries

    @property
    def max_serialized_bytes(self):
        return self._max_serialized_bytes

    def observe(self, scope, observed_step, candidate_metadata, candidate_features):
        """Select copied immutable records; no labels or evaluator inputs exist."""
        wall, cpu = time.perf_counter(), time.process_time()
        counts = dict(
            scope_reset=False,
            reset_discarded=0,
            input_candidates=0,
            duplicate_candidates=0,
            byte_dropped=0,
            entry_dropped=0,
        )

        def receipt(status):
            return MemoryReceipt(
                status=status,
                **counts,
                resident_entries=len(self._records),
                resident_serialized_bytes=self._resident_bytes,
                decision_cpu_seconds=time.process_time() - cpu,
                decision_wall_seconds=time.perf_counter() - wall,
            )

        try:
            if not isinstance(scope, CandidateScope):
                raise ValueError("an explicit original-source scope is required")
            if scope != self._scope:
                counts.update(scope_reset=True, reset_discarded=len(self._records))
                self._scope, self._last_step, self._records = None, None, ()
                self._resident_bytes = self._empty_bytes
                empty_bytes = _size({"scope": asdict(scope), "records": []})
                if empty_bytes > self.max_serialized_bytes:
                    raise ValueError("source scope alone exceeds the byte budget")
                self._scope, self._resident_bytes = scope, empty_bytes
            if not _integer(observed_step, 0, 2**31 - 1) or (
                self._last_step is not None and observed_step <= self._last_step
            ):
                raise ValueError("observed step must strictly advance within a scope")
            if (
                not isinstance(candidate_metadata, (list, tuple))
                or not isinstance(candidate_features, (list, tuple))
                or len(candidate_metadata) != len(candidate_features)
                or len(candidate_metadata) > 128
            ):
                raise ValueError(
                    "matching bounded public metadata/features rosters required"
                )
            counts["input_candidates"] = len(candidate_metadata)
            current = tuple(
                _record(scope, observed_step, metadata, features)
                for metadata, features in zip(candidate_metadata, candidate_features)
            )
            previous = sorted(self._records, key=lambda record: -record.observed_step)
            selected, seen = [], set()
            resident = _size({"scope": asdict(scope), "records": []})
            for record in (*current, *previous):
                if record.key in seen:
                    counts["duplicate_candidates"] += 1
                    continue
                seen.add(record.key)
                if len(selected) == self.max_entries:
                    counts["entry_dropped"] += 1
                    continue
                addition = _size(asdict(record)) + bool(selected)
                if resident + addition > self.max_serialized_bytes:
                    counts["byte_dropped"] += 1
                    continue
                selected.append(record)
                resident += addition
            self._records, self._last_step = tuple(selected), observed_step
            self._resident_bytes = resident
            copied = tuple(replace(record) for record in self._records)
        except (ValueError, TypeError, OverflowError) as error:
            raise CandidateMemoryError(str(error), receipt("rejected")) from error
        return MemoryDecision(copied, receipt("selected" if copied else "empty"))
