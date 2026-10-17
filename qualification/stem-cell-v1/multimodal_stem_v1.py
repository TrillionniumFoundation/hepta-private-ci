"""Research-only source-bound multimodal feature reuse and sparse Cell control.

No model execution, training, authority admission, or scientific quality claim.
Requires authenticated original-feature producer in a separate research step.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Sequence

MODALITIES = frozenset({"text", "image", "audio", "video"})
MAX_SLOTS = 256
WIDTH = 384
MAX_ACTIVE = 32

class AdmissionError(ValueError):
    pass

def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _require_sha(s: str) -> None:
    if not isinstance(s, str) or len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise AdmissionError("noncanonical sha256")

@dataclass(frozen=True)
class FeatureEnvelope:
    modality: str
    original_sha256: str
    feature_sha256: str
    encoder_sha256: str
    tokenizer_sha256: str
    preprocessor_sha256: str
    quantization_sha256: str
    projection_sha256: str
    principal: str
    purpose: str
    generation: int
    epoch: int
    slot_count: int
    width: int
    timestamps: tuple[int, ...]
    regions: tuple[tuple[int, int, int, int], ...]
    source_kind: str
    reviewed: bool = False

    def validate(self) -> None:
        if self.modality not in MODALITIES or self.source_kind not in {"original", "derived"}:
            raise AdmissionError("unsupported modality or source kind")
        for key in ("original_sha256", "feature_sha256", "encoder_sha256",
                    "tokenizer_sha256", "preprocessor_sha256", "quantization_sha256",
                    "projection_sha256"):
            _require_sha(getattr(self, key))
        if (not isinstance(self.principal, str) or not self.principal.strip()
                or not isinstance(self.purpose, str) or not self.purpose.strip()
                or type(self.generation) is not int or self.generation < 1
                or type(self.epoch) is not int or self.epoch < 0):
            raise AdmissionError("invalid identity or lifecycle")
        if self.width != WIDTH or not 1 <= self.slot_count <= MAX_SLOTS:
            raise AdmissionError("shape budget")
        if self.timestamps and (len(self.timestamps) != self.slot_count
                or any(type(t) is not int or t < 0 for t in self.timestamps)
                or tuple(sorted(self.timestamps)) != self.timestamps):
            raise AdmissionError("invalid timestamps")
        if self.regions and (len(self.regions) != self.slot_count or
                any(len(box) != 4 or any(type(v) is not int for v in box)
                    or box[0] < 0 or box[1] < 0 or box[2] <= 0 or box[3] <= 0
                    for box in self.regions)):
            raise AdmissionError("invalid regions")
        if self.modality in {"audio", "video"} and not self.timestamps:
            raise AdmissionError("temporal source requires timestamps")
        if self.modality == "image" and not self.regions:
            raise AdmissionError("image requires regions")

    def key(self) -> str:
        self.validate()
        # Include every field to prevent cross-principal, purpose, modality or
        # lifecycle reuse, and reject collisions from changed source coordinates.
        raw = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":")).encode()
        return _digest(b"hepta.stem.feature.v1\x00" + raw)

def admit_features(env: FeatureEnvelope, raw_feature_bytes: bytes) -> str:
    env.validate()
    if not env.reviewed:
        raise AdmissionError("unreviewed feature producer")
    if _digest(raw_feature_bytes) != env.feature_sha256:
        raise AdmissionError("feature byte mismatch")
    # This verifies supplied feature bytes, NOT external model authenticity.
    return env.key()

class ReuseLedger:
    def __init__(self):
        self._seen: set[str] = set()
        self.unique_feature_admissions = 0
        self.reused_requests = 0

    def access(self, env: FeatureEnvelope, raw_feature_bytes: bytes) -> bool:
        key = admit_features(env, raw_feature_bytes)
        if key in self._seen:
            self.reused_requests += 1
            return True
        self._seen.add(key)
        # Logical unique-feature count only; never call this a physical forward.
        self.unique_feature_admissions += 1
        return False

@dataclass(frozen=True)
class CellHead:
    identity: str
    weights: tuple[float, ...]
    bias: float

    def score(self, slots: Sequence[Sequence[float]]) -> float:
        if len(self.weights) != WIDTH or not slots or len(slots) > MAX_SLOTS:
            raise AdmissionError("head or slots shape")
        if not self.identity:
            raise AdmissionError("empty cell identity")
        if any(len(row) != WIDTH for row in slots):
            raise AdmissionError("slot feature shape")
        if not math.isfinite(self.bias) or any(not math.isfinite(v) for v in self.weights):
            raise AdmissionError("invalid head weights")
        # Mean pooling is a controlled baseline, not proof of multimodal reasoning.
        pooled = [0.0] * WIDTH
        for row in slots:
            for i, val in enumerate(row):
                if not math.isfinite(val) or abs(val) > 8:
                    raise AdmissionError("invalid feature")
                pooled[i] += val / len(slots)
        value = sum(a*b for a,b in zip(pooled, self.weights)) + self.bias
        if not math.isfinite(value):
            raise AdmissionError("nonfinite Cell score")
        return value

def select_cells(cells: Sequence[CellHead], slots: Sequence[Sequence[float]],
                 top_k: int = 8) -> tuple[tuple[str, float], ...]:
    if not cells or not 1 <= top_k <= MAX_ACTIVE or len(cells) > 4096:
        raise AdmissionError("selection budget")
    if len({cell.identity for cell in cells}) != len(cells):
        raise AdmissionError("duplicate Cell")
    scores = [(c.identity, c.score(slots)) for c in cells]
    return tuple(sorted(scores, key=lambda item: (-item[1], item[0]))[:top_k])

def audit_split(old_scores: Sequence[int], new_scores: Sequence[int],
                old_retention: Sequence[int], split_cost: float,
                minimum_groups: int = 200) -> dict:
    if (len(old_scores) != len(new_scores) or len(old_scores) < minimum_groups
            or not old_retention or len(old_retention) != len(old_scores)):
        raise AdmissionError("insufficient independent-group evidence")
    if any(x not in (0,1) for s in (old_scores,new_scores,old_retention) for x in s):
        raise AdmissionError("invalid outcome")
    if not math.isfinite(split_cost) or split_cost < 0:
        raise AdmissionError("invalid cost")
    improvement = (sum(new_scores) - sum(old_scores)) / len(old_scores)
    retention = sum(old_retention) / len(old_retention)
    # Never authorizes split. No independent evaluator or source audit supplied.
    return {"delta_future": improvement, "old_retention": retention,
            "charged_cost": split_cost, "authority": "DENY_ALL",
            "split_authorized": False, "quality_attested": False}
