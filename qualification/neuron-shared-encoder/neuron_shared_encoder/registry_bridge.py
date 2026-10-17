"""Research-only binding for modality envelopes and frozen registries.

This module connects the existing ModalityEnvelopeV1 input contract to the
source-bound tower/projector registries. It performs identity, shape and
capability checks only. It never loads a checkpoint, executes a model,
trains an adapter, selects a Stem, or grants runtime authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any

try:
    from .modality_registry import (
        ModalityTowerRegistryV1,
        ProjectorRegistryV1,
        RegistryError,
        bind_modality_registries,
    )
except ImportError:  # direct qualification-file execution
    from modality_registry import (  # type: ignore
        ModalityTowerRegistryV1,
        ProjectorRegistryV1,
        RegistryError,
        bind_modality_registries,
    )


SCHEMA_BOUND_ENVELOPE = "hepta.modality.bound-envelope.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _integer(name: str, value: Any, *, minimum: int, maximum: int) -> None:
    _require(type(value) is int, f"{name} must be an integer")
    _require(minimum <= value <= maximum, f"{name} is outside its bounds")


def _finite_nonnegative(name: str, value: float | int) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")
    _require(float(value) >= 0.0, f"{name} must be non-negative")


@dataclass(frozen=True)
class BoundModalityEnvelopeV1:
    """A readonly envelope proven compatible with one frozen registry pair."""

    modality: str
    stem_digest: str
    raw_digest: str
    feature_digest: str
    projector_digest: str
    tower_id: str
    projector_id: str
    tower_registry_digest: str
    projector_registry_digest: str
    latent_width: int
    slots: int
    temporal_span_ms: float | None = None
    region_count: int = 0
    source_bound: bool = True
    readonly: bool = True
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        _require(self.modality in {"audio", "image", "text", "video"}, "unsupported modality")
        for name, value in (
            ("stem_digest", self.stem_digest),
            ("raw_digest", self.raw_digest),
            ("feature_digest", self.feature_digest),
            ("projector_digest", self.projector_digest),
            ("tower_registry_digest", self.tower_registry_digest),
            ("projector_registry_digest", self.projector_registry_digest),
        ):
            _digest(name, value)
        _identifier("tower_id", self.tower_id)
        _identifier("projector_id", self.projector_id)
        _integer("latent_width", self.latent_width, minimum=1, maximum=2048)
        _integer("slots", self.slots, minimum=1, maximum=256)
        _integer("region_count", self.region_count, minimum=0, maximum=4096)
        if self.temporal_span_ms is not None:
            _finite_nonnegative("temporal_span_ms", self.temporal_span_ms)
        if self.modality in {"audio", "video"}:
            _require(self.temporal_span_ms is not None, "temporal modalities require a time span")
        else:
            _require(self.temporal_span_ms is None, "only temporal modalities may carry a time span")
        if self.modality != "image":
            _require(self.region_count == 0, "region_count is only valid for image envelopes")
        _require(type(self.source_bound) is bool and self.source_bound, "bound envelopes must be source-bound")
        _require(type(self.readonly) is bool and self.readonly, "bound envelopes must be readonly")
        _require(self.authority == "DENY_ALL", "binding cannot carry authority")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_BOUND_ENVELOPE}


def bind_envelope_to_registry(
    envelope: Any,
    stem: Any,
    towers: ModalityTowerRegistryV1,
    projectors: ProjectorRegistryV1,
) -> BoundModalityEnvelopeV1:
    """Bind one ModalityEnvelopeV1 to frozen source-bound producer registries.

    The envelope object is intentionally duck-typed so this bridge can be used
    from the existing stem-transfer contract without importing that file as a
    package. The expected fields are the ModalityEnvelopeV1 fields.
    """

    binding = bind_modality_registries(stem, towers, projectors)
    modality = envelope.modality
    tower = towers.tower_for(modality)
    projector = projectors.projector_for(modality)

    _require(envelope.stem_digest == stem.stem_digest, "envelope/Stem digest mismatch")
    _require(envelope.projector_digest == projector.projector_digest, "envelope/projector digest mismatch")
    _require(envelope.latent_width == projector.output_width, "envelope latent width does not match Stem width")
    _require(envelope.slots <= projector.slots, "envelope slot count exceeds projector budget")
    _require(envelope.readonly is True, "input envelope must be readonly")

    if modality in {"audio", "video"}:
        _require(tower.supports_temporal and envelope.temporal_span_ms is not None, f"{modality} temporal capability is missing")
    else:
        _require(envelope.temporal_span_ms is None, "non-temporal envelope carries a time span")
    if modality == "image":
        _require(tower.supports_regions, "image tower does not declare region support")
        _require(envelope.region_count <= tower.max_input_tokens, "image regions exceed tower budget")
    else:
        _require(envelope.region_count == 0, "only image envelopes may carry regions")

    return BoundModalityEnvelopeV1(
        modality=modality,
        stem_digest=stem.stem_digest,
        raw_digest=envelope.raw_digest,
        feature_digest=envelope.feature_digest,
        projector_digest=projector.projector_digest,
        tower_id=tower.tower_id,
        projector_id=projector.projector_id,
        tower_registry_digest=binding.tower_registry_digest,
        projector_registry_digest=binding.projector_registry_digest,
        latent_width=envelope.latent_width,
        slots=envelope.slots,
        temporal_span_ms=envelope.temporal_span_ms,
        region_count=envelope.region_count,
    )


def bound_envelope_manifest(bound: BoundModalityEnvelopeV1) -> dict[str, Any]:
    """Return a deterministic, non-authorizing receipt fragment."""

    return {
        "schema": "hepta.modality.bound-envelope-manifest.v1",
        "envelope": bound.to_dict(),
        "receipt_digest": hashlib.sha256(
            json.dumps(bound.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "authority": "DENY_ALL",
    }


__all__ = [
    "BoundModalityEnvelopeV1",
    "SCHEMA_BOUND_ENVELOPE",
    "RegistryError",
    "bind_envelope_to_registry",
    "bound_envelope_manifest",
]
