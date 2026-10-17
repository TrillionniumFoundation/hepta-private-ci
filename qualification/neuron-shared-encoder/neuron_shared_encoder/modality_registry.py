"""Research-only modality tower/projector registries for a frozen shared Stem.

This module records which frozen modality towers and source-bound projectors may
feed a shared Stem. It performs no model loading, training, selection,
activation, or decoder execution. Registry acceptance is an identity and shape
contract only; efficacy remains the responsibility of the qualification gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_TOWER = "hepta.modality.tower-registry.v1"
SCHEMA_PROJECTOR = "hepta.modality.projector-registry.v1"
FREEZE_POLICY = "immutable_frozen_registry"
MODALITIES = ("audio", "image", "text", "video")
_QUANTIZATIONS = frozenset({"fp32", "bf16", "fp16", "int8", "int4", "q24"})
_PROJECTOR_KINDS = frozenset({"linear", "mlp", "perceiver", "gated_cross_attention"})
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RegistryError(ValueError):
    """Raised when an immutable modality registry is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _integer(name: str, value: Any, *, minimum: int, maximum: int) -> None:
    _require(type(value) is int, f"{name} must be an integer")
    _require(minimum <= value <= maximum, f"{name} is outside its bounds")


def _finite(name: str, value: float) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest_object(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModalityTowerSpecV1:
    modality: str
    tower_id: str
    tower_digest: str
    preprocessor_digest: str
    output_width: int
    max_input_tokens: int
    quantization: str = "bf16"
    frozen: bool = True
    source_bound: bool = True
    supports_streaming: bool = False
    supports_regions: bool = False
    supports_temporal: bool = False

    def __post_init__(self) -> None:
        _require(self.modality in MODALITIES, "unsupported modality")
        _identifier("tower_id", self.tower_id)
        _digest("tower_digest", self.tower_digest)
        _digest("preprocessor_digest", self.preprocessor_digest)
        _integer("output_width", self.output_width, minimum=1, maximum=8192)
        _integer("max_input_tokens", self.max_input_tokens, minimum=1, maximum=10_000_000)
        _require(self.quantization in _QUANTIZATIONS, "unsupported tower quantization")
        _require(type(self.frozen) is bool and self.frozen, "modality towers must be frozen for this registry")
        _require(type(self.source_bound) is bool and self.source_bound, "modality towers must be source-bound")
        _require(type(self.supports_streaming) is bool, "supports_streaming must be boolean")
        _require(type(self.supports_regions) is bool, "supports_regions must be boolean")
        _require(type(self.supports_temporal) is bool, "supports_temporal must be boolean")
        if self.modality in {"audio", "video"}:
            _require(self.supports_temporal, "audio and video towers must declare temporal support")
        if self.modality == "image":
            _require(self.supports_regions, "image towers must declare region support")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_TOWER}


@dataclass(frozen=True)
class ProjectorSpecV1:
    modality: str
    projector_id: str
    projector_digest: str
    input_width: int
    output_width: int
    slots: int
    kind: str
    trainable_in_alignment: bool = True
    zero_init_gate: bool = True
    private_residual: bool = True
    source_bound: bool = True

    def __post_init__(self) -> None:
        _require(self.modality in MODALITIES, "unsupported modality")
        _identifier("projector_id", self.projector_id)
        _digest("projector_digest", self.projector_digest)
        _integer("input_width", self.input_width, minimum=1, maximum=8192)
        _integer("output_width", self.output_width, minimum=1, maximum=8192)
        _integer("slots", self.slots, minimum=1, maximum=256)
        _require(self.kind in _PROJECTOR_KINDS, "unsupported projector kind")
        for name, value in (
            ("trainable_in_alignment", self.trainable_in_alignment),
            ("zero_init_gate", self.zero_init_gate),
            ("private_residual", self.private_residual),
            ("source_bound", self.source_bound),
        ):
            _require(type(value) is bool, f"{name} must be boolean")
        _require(self.source_bound, "projectors must bind source identity")
        _require(self.zero_init_gate, "new cross-modal projectors must start with a zero gate")
        if self.kind == "gated_cross_attention":
            _require(self.zero_init_gate, "gated cross-attention requires zero initialization")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_PROJECTOR}


def _sorted_unique(items: Sequence[str], name: str) -> tuple[str, ...]:
    values = tuple(items)
    _require(tuple(sorted(set(values))) == values, f"{name} must be sorted and unique")
    return values


@dataclass(frozen=True)
class ModalityTowerRegistryV1:
    stem_digest: str
    towers: tuple[ModalityTowerSpecV1, ...]
    generation: int = 0
    freeze_policy: str = FREEZE_POLICY

    def __post_init__(self) -> None:
        _digest("stem_digest", self.stem_digest)
        _integer("generation", self.generation, minimum=0, maximum=2**31 - 1)
        _require(self.freeze_policy == FREEZE_POLICY, "tower registry must be immutable")
        _require(type(self.towers) is tuple, "towers must be an immutable tuple")
        _require(all(isinstance(tower, ModalityTowerSpecV1) for tower in self.towers), "towers contain an invalid spec")
        _require(0 < len(self.towers) <= len(MODALITIES), "invalid tower count")
        modalities = tuple(tower.modality for tower in self.towers)
        _require(tuple(sorted(set(modalities))) == modalities, "tower modalities must be sorted and unique")
        ids = tuple(tower.tower_id for tower in self.towers)
        _require(len(set(ids)) == len(ids), "tower IDs must be unique")
        _require(all(tower.frozen and tower.source_bound for tower in self.towers), "all towers must be frozen and source-bound")

    @property
    def modalities(self) -> tuple[str, ...]:
        return tuple(tower.modality for tower in self.towers)

    @property
    def registry_digest(self) -> str:
        return _digest_object(self.to_dict())

    def tower_for(self, modality: str) -> ModalityTowerSpecV1:
        _require(modality in self.modalities, f"tower is not registered for {modality}")
        return next(tower for tower in self.towers if tower.modality == modality)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_TOWER,
            "stem_digest": self.stem_digest,
            "towers": [tower.to_dict() for tower in self.towers],
            "generation": self.generation,
            "freeze_policy": self.freeze_policy,
        }


@dataclass(frozen=True)
class ProjectorRegistryV1:
    stem_digest: str
    target_width: int
    projectors: tuple[ProjectorSpecV1, ...]
    generation: int = 0
    freeze_policy: str = FREEZE_POLICY

    def __post_init__(self) -> None:
        _digest("stem_digest", self.stem_digest)
        _integer("target_width", self.target_width, minimum=1, maximum=8192)
        _integer("generation", self.generation, minimum=0, maximum=2**31 - 1)
        _require(self.freeze_policy == FREEZE_POLICY, "projector registry must be immutable")
        _require(type(self.projectors) is tuple, "projectors must be an immutable tuple")
        _require(all(isinstance(projector, ProjectorSpecV1) for projector in self.projectors), "projectors contain an invalid spec")
        _require(0 < len(self.projectors) <= len(MODALITIES), "invalid projector count")
        modalities = tuple(projector.modality for projector in self.projectors)
        _require(tuple(sorted(set(modalities))) == modalities, "projector modalities must be sorted and unique")
        ids = tuple(projector.projector_id for projector in self.projectors)
        _require(len(set(ids)) == len(ids), "projector IDs must be unique")
        for projector in self.projectors:
            _require(projector.output_width == self.target_width, "projector output must equal Stem width")
            _require(projector.source_bound and projector.zero_init_gate, "projector safety flags are required")

    @property
    def modalities(self) -> tuple[str, ...]:
        return tuple(projector.modality for projector in self.projectors)

    @property
    def registry_digest(self) -> str:
        return _digest_object(self.to_dict())

    def projector_for(self, modality: str) -> ProjectorSpecV1:
        _require(modality in self.modalities, f"projector is not registered for {modality}")
        return next(projector for projector in self.projectors if projector.modality == modality)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_PROJECTOR,
            "stem_digest": self.stem_digest,
            "target_width": self.target_width,
            "projectors": [projector.to_dict() for projector in self.projectors],
            "generation": self.generation,
            "freeze_policy": self.freeze_policy,
        }


@dataclass(frozen=True)
class BoundModalityRegistriesV1:
    stem_digest: str
    stem_hidden_width: int
    tower_registry_digest: str
    projector_registry_digest: str
    modalities: tuple[str, ...]
    source_bound: bool = True
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        _digest("stem_digest", self.stem_digest)
        _integer("stem_hidden_width", self.stem_hidden_width, minimum=1, maximum=8192)
        _digest("tower_registry_digest", self.tower_registry_digest)
        _digest("projector_registry_digest", self.projector_registry_digest)
        _require(tuple(sorted(set(self.modalities))) == self.modalities, "bound modalities must be sorted and unique")
        _require(0 < len(self.modalities) <= len(MODALITIES), "invalid bound modality count")
        _require(type(self.source_bound) is bool and self.source_bound, "bound registry must be source-bound")
        _require(self.authority == "DENY_ALL", "registry binding cannot carry authority")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": "hepta.modality.registry-binding.v1"}


def bind_modality_registries(
    stem: Any,
    towers: ModalityTowerRegistryV1,
    projectors: ProjectorRegistryV1,
) -> BoundModalityRegistriesV1:
    """Bind frozen tower/projector registries to one shared Stem manifest.

    The function checks identity and width compatibility only. It does not load
    a model or certify semantic alignment, generation quality, or efficacy.
    """

    for field in ("stem_digest", "hidden_width", "modality_projectors", "current_generation"):
        _require(hasattr(stem, field), f"Stem is missing {field}")
    _require(stem.stem_digest == towers.stem_digest == projectors.stem_digest, "registry/Stem digest mismatch")
    stem_generation = getattr(stem, "current_generation", None)
    _require(type(stem_generation) is int, "Stem must declare current_generation")
    _require(towers.generation == projectors.generation == stem_generation, "registry generation mismatch")
    _require(stem.hidden_width == projectors.target_width, "projector width does not match Stem width")
    _require(towers.modalities == projectors.modalities, "tower/projector modality sets differ")
    registered_projectors = tuple(stem.modality_projectors)
    _require(
        all(projector.projector_id in registered_projectors for projector in projectors.projectors),
        "projector is missing from StemManifest registry",
    )
    for modality in towers.modalities:
        tower = towers.tower_for(modality)
        projector = projectors.projector_for(modality)
        _require(tower.output_width == projector.input_width, f"{modality} tower/projector width mismatch")
        if modality in {"audio", "video"}:
            _require(tower.supports_temporal, f"{modality} tower must support temporal spans")
    return BoundModalityRegistriesV1(
        stem_digest=stem.stem_digest,
        stem_hidden_width=stem.hidden_width,
        tower_registry_digest=towers.registry_digest,
        projector_registry_digest=projectors.registry_digest,
        modalities=towers.modalities,
    )


def registry_manifest(
    towers: ModalityTowerRegistryV1,
    projectors: ProjectorRegistryV1,
    *,
    binding: BoundModalityRegistriesV1 | None = None,
) -> dict[str, Any]:
    """Return a deterministic, non-authorizing manifest for a qualification receipt."""
    _require(towers.stem_digest == projectors.stem_digest, "registry Stem digest mismatch")
    result: dict[str, Any] = {
        "schema": "hepta.modality.registry-manifest.v1",
        "tower_registry": towers.to_dict(),
        "projector_registry": projectors.to_dict(),
        "registry_digest": _digest_object({"towers": towers.to_dict(), "projectors": projectors.to_dict()}),
        "authority": "DENY_ALL",
    }
    if binding is not None:
        _require(binding.stem_digest == towers.stem_digest, "binding Stem digest mismatch")
        _require(binding.tower_registry_digest == towers.registry_digest, "binding tower registry digest mismatch")
        _require(binding.projector_registry_digest == projectors.registry_digest, "binding projector registry digest mismatch")
        result["binding"] = binding.to_dict()
    return result


__all__ = [
    "BoundModalityRegistriesV1",
    "ModalityTowerRegistryV1",
    "ModalityTowerSpecV1",
    "ProjectorRegistryV1",
    "ProjectorSpecV1",
    "RegistryError",
    "bind_modality_registries",
    "registry_manifest",
]
