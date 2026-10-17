"""Research-only registries for modality towers and Stem projectors.

The registry is an immutable description of the adapters that may feed a
shared Stem.  It does not load a checkpoint, train a tower, select a modality
implementation, or grant runtime authority.  Every envelope constructed by
the registry is bound to the same Stem digest and to a registered projector.
Evidence labels describe the receipt class only; they are not multimodal
efficacy claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


def _load_contracts():
    try:
        from stem_transfer_cell_artifact import (  # type: ignore
            ContractError,
            ModalityEnvelopeV1,
            StemManifestV1,
        )
        return ContractError, ModalityEnvelopeV1, StemManifestV1
    except ModuleNotFoundError:
        contract_path = Path(__file__).resolve().parents[2] / "stem-transfer-cell-artifact-p0" / "stem_transfer_cell_artifact.py"
        spec = importlib.util.spec_from_file_location("stem_transfer_cell_artifact", contract_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load Stem contract: {contract_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.ContractError, module.ModalityEnvelopeV1, module.StemManifestV1


ContractError, ModalityEnvelopeV1, StemManifestV1 = _load_contracts()

SCHEMA_TOWER = "hepta.modality.tower-spec.v1"
SCHEMA_TOWER_REGISTRY = "hepta.modality.tower-registry.v1"
SCHEMA_PROJECTOR = "hepta.modality.projector-spec.v1"
SCHEMA_PROJECTOR_REGISTRY = "hepta.modality.projector-registry.v1"
SUPPORTED_MODALITIES = ("audio", "image", "text", "video")
IMMUTABLE_POLICY = "immutable_current_generation"
EVIDENCE_CLASSES = (
    "UNVERIFIED",
    "SYNTHETIC_SMOKE",
    "HISTORICAL_REPLAY",
    "REAL_MODEL_LOCAL_QUALIFICATION",
    "REAL_SHADOW",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_HEX64.fullmatch(value)), f"{name} must be a lowercase sha256")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and bool(_IDENT.fullmatch(value)), f"{name} is not a stable identifier")


def _integer(name: str, value: Any, minimum: int = 0, maximum: int | None = None) -> None:
    _require(type(value) is int and value >= minimum, f"{name} must be an integer >= {minimum}")
    if maximum is not None:
        _require(value <= maximum, f"{name} exceeds its upper bound")


def _finite_nonnegative(name: str, value: Any) -> None:
    _require(type(value) in (int, float), f"{name} must be numeric")
    _require(float(value) >= 0.0, f"{name} must be non-negative")


def _boolean(name: str, value: Any) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModalityTowerSpecV1:
    """Immutable descriptor for one raw-modality tower."""

    tower_id: str
    modality: str
    tower_digest: str
    preprocessor_digest: str
    output_width: int
    max_slots: int
    parameter_count: int
    evidence_class: str = "UNVERIFIED"
    checkpoint_receipt_digest: str | None = None
    temporal_resolution_hz: float | None = None
    frozen: bool = True
    readonly_output: bool = True
    freeze_policy: str = IMMUTABLE_POLICY
    current_run_mutation: bool = False

    def __post_init__(self) -> None:
        _identifier("tower_id", self.tower_id)
        _require(self.modality in SUPPORTED_MODALITIES, "unsupported modality tower")
        for name, value in (("tower_digest", self.tower_digest), ("preprocessor_digest", self.preprocessor_digest)):
            _digest(name, value)
        _integer("output_width", self.output_width, 1, 16384)
        _integer("max_slots", self.max_slots, 1, 4096)
        _integer("parameter_count", self.parameter_count, 1)
        _require(self.evidence_class in EVIDENCE_CLASSES, "unknown tower evidence class")
        if self.checkpoint_receipt_digest is not None:
            _digest("checkpoint_receipt_digest", self.checkpoint_receipt_digest)
        if self.evidence_class in {"REAL_MODEL_LOCAL_QUALIFICATION", "REAL_SHADOW"}:
            _require(self.checkpoint_receipt_digest is not None, "real tower evidence requires a receipt digest")
        if self.modality in {"audio", "video"}:
            _require(self.temporal_resolution_hz is not None, "audio/video towers require temporal resolution")
            _finite_nonnegative("temporal_resolution_hz", self.temporal_resolution_hz)
            _require(float(self.temporal_resolution_hz) > 0.0, "temporal resolution must be positive")
        else:
            _require(self.temporal_resolution_hz is None, "text/image towers cannot carry temporal resolution")
        _boolean("frozen", self.frozen)
        _boolean("readonly_output", self.readonly_output)
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(self.frozen, "registered towers must be frozen in the current generation")
        _require(self.readonly_output, "tower output must be readonly")
        _require(self.freeze_policy == IMMUTABLE_POLICY, "tower freeze policy must be immutable")
        _require(not self.current_run_mutation, "tower registry cannot mutate the current run")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_TOWER}


@dataclass(frozen=True)
class ModalityProjectorSpecV1:
    """Digest-bound projector from a tower feature space into the Stem width."""

    projector_id: str
    modality: str
    projector_digest: str
    source_tower_id: str
    stem_digest: str
    input_width: int
    latent_width: int
    max_slots: int
    resident_params: int
    active_params: int
    evidence_class: str = "UNVERIFIED"
    checkpoint_receipt_digest: str | None = None
    frozen: bool = True
    readonly_output: bool = True
    freeze_policy: str = IMMUTABLE_POLICY
    current_run_mutation: bool = False
    next_snapshot_only: bool = True

    def __post_init__(self) -> None:
        _identifier("projector_id", self.projector_id)
        _require(self.modality in SUPPORTED_MODALITIES, "unsupported modality projector")
        _identifier("source_tower_id", self.source_tower_id)
        for name, value in (("projector_digest", self.projector_digest), ("stem_digest", self.stem_digest)):
            _digest(name, value)
        _integer("input_width", self.input_width, 1, 16384)
        _integer("latent_width", self.latent_width, 1, 16384)
        _integer("max_slots", self.max_slots, 1, 4096)
        _integer("resident_params", self.resident_params, 1)
        _integer("active_params", self.active_params, 1)
        _require(self.active_params <= self.resident_params, "active projector parameters exceed resident parameters")
        _require(self.evidence_class in EVIDENCE_CLASSES, "unknown projector evidence class")
        if self.checkpoint_receipt_digest is not None:
            _digest("checkpoint_receipt_digest", self.checkpoint_receipt_digest)
        if self.evidence_class in {"REAL_MODEL_LOCAL_QUALIFICATION", "REAL_SHADOW"}:
            _require(self.checkpoint_receipt_digest is not None, "real projector evidence requires a receipt digest")
        _boolean("frozen", self.frozen)
        _boolean("readonly_output", self.readonly_output)
        _boolean("current_run_mutation", self.current_run_mutation)
        _boolean("next_snapshot_only", self.next_snapshot_only)
        _require(self.frozen, "registered projectors must be frozen in the current generation")
        _require(self.readonly_output, "projector output must be readonly")
        _require(self.freeze_policy == IMMUTABLE_POLICY, "projector freeze policy must be immutable")
        _require(not self.current_run_mutation, "projector registry cannot mutate the current run")
        _require(self.next_snapshot_only, "projector changes can only enter a future snapshot")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "schema": SCHEMA_PROJECTOR}


@dataclass(frozen=True)
class ModalityTowerRegistryV1:
    """All modality towers available to one frozen shared Stem."""

    registry_id: str
    stem: StemManifestV1
    towers: tuple[ModalityTowerSpecV1, ...]
    status: str = "SHADOW_ONLY"
    selection_authority: bool = False
    current_run_mutation: bool = False

    def __post_init__(self) -> None:
        _identifier("registry_id", self.registry_id)
        _require(self.status == "SHADOW_ONLY", "tower registry cannot be promoted")
        _boolean("selection_authority", self.selection_authority)
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(not self.selection_authority, "tower registry cannot select a production tower")
        _require(not self.current_run_mutation, "tower registry cannot mutate the current run")
        _require(tuple(self.stem.modality_projectors) == tuple(sorted(self.stem.modality_projectors)), "Stem projector IDs must be sorted")
        _require(len(self.towers) == len(SUPPORTED_MODALITIES), "multimodal registry requires all four modality towers")
        modalities = tuple(tower.modality for tower in self.towers)
        _require(len(set(modalities)) == len(modalities), "tower modalities must be unique")
        _require(set(modalities) == set(SUPPORTED_MODALITIES), "tower registry must cover text/image/video/audio")
        ids = tuple(tower.tower_id for tower in self.towers)
        _require(len(set(ids)) == len(ids), "tower IDs must be unique")
        _require(tuple(sorted(ids)) == ids, "tower IDs must be sorted for deterministic serialization")

    @property
    def tower_ids(self) -> tuple[str, ...]:
        return tuple(tower.tower_id for tower in self.towers)

    def tower_for(self, modality: str) -> ModalityTowerSpecV1:
        _require(modality in SUPPORTED_MODALITIES, "unsupported modality")
        for tower in self.towers:
            if tower.modality == modality:
                return tower
        raise ContractError(f"no tower registered for modality: {modality}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_TOWER_REGISTRY,
            "registry_id": self.registry_id,
            "stem": self.stem.to_dict(),
            "towers": [tower.to_dict() for tower in self.towers],
            "status": self.status,
            "selection_authority": self.selection_authority,
            "current_run_mutation": self.current_run_mutation,
        }

    @property
    def registry_digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class ProjectorRegistryV1:
    """Projectors that map registered towers into the frozen Stem latent width."""

    registry_id: str
    stem: StemManifestV1
    tower_registry_digest: str
    projectors: tuple[ModalityProjectorSpecV1, ...]
    status: str = "SHADOW_ONLY"
    selection_authority: bool = False
    current_run_mutation: bool = False

    def __post_init__(self) -> None:
        _identifier("registry_id", self.registry_id)
        _digest("tower_registry_digest", self.tower_registry_digest)
        _require(self.status == "SHADOW_ONLY", "projector registry cannot be promoted")
        _boolean("selection_authority", self.selection_authority)
        _boolean("current_run_mutation", self.current_run_mutation)
        _require(not self.selection_authority, "projector registry cannot select a production projector")
        _require(not self.current_run_mutation, "projector registry cannot mutate the current run")
        _require(len(self.projectors) == len(SUPPORTED_MODALITIES), "multimodal registry requires four projectors")
        ids = tuple(projector.projector_id for projector in self.projectors)
        _require(tuple(self.stem.modality_projectors) == ids, "projector IDs must exactly match the Stem manifest")
        modalities = tuple(projector.modality for projector in self.projectors)
        _require(set(modalities) == set(SUPPORTED_MODALITIES), "projector registry must cover all modalities")
        _require(len(set(modalities)) == len(modalities), "projector modalities must be unique")
        for projector in self.projectors:
            _require(projector.stem_digest == self.stem.stem_digest, "projector Stem digest mismatch")
            _require(projector.latent_width == self.stem.hidden_width, "projector latent width must equal Stem width")

    @property
    def projector_ids(self) -> tuple[str, ...]:
        return tuple(projector.projector_id for projector in self.projectors)

    def projector_for(self, modality: str) -> ModalityProjectorSpecV1:
        _require(modality in SUPPORTED_MODALITIES, "unsupported modality")
        for projector in self.projectors:
            if projector.modality == modality:
                return projector
        raise ContractError(f"no projector registered for modality: {modality}")

    def validate_tower_registry(self, registry: ModalityTowerRegistryV1) -> None:
        _require(registry.stem.stem_digest == self.stem.stem_digest, "tower registry Stem digest mismatch")
        _require(registry.registry_digest == self.tower_registry_digest, "tower registry digest mismatch")
        for projector in self.projectors:
            tower = registry.tower_for(projector.modality)
            _require(tower.tower_id == projector.source_tower_id, "projector source tower mismatch")
            _require(tower.output_width == projector.input_width, "projector input width does not match tower output")
            _require(tower.max_slots >= projector.max_slots, "projector slot budget exceeds tower output budget")

    def envelope(
        self,
        modality: str,
        *,
        raw_digest: str,
        feature_digest: str,
        slots: int,
        temporal_span_ms: float | None = None,
        region_count: int = 0,
    ) -> ModalityEnvelopeV1:
        """Construct a digest-bound readonly envelope after registry validation."""
        projector = self.projector_for(modality)
        _digest("raw_digest", raw_digest)
        _digest("feature_digest", feature_digest)
        _integer("slots", slots, 1)
        _require(slots <= projector.max_slots, "envelope slots exceed projector capacity")
        _integer("region_count", region_count, 0)
        return ModalityEnvelopeV1(
            modality=modality,
            stem_digest=self.stem.stem_digest,
            raw_digest=raw_digest,
            feature_digest=feature_digest,
            projector_digest=projector.projector_digest,
            latent_width=projector.latent_width,
            slots=slots,
            temporal_span_ms=temporal_span_ms,
            region_count=region_count,
            readonly=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_PROJECTOR_REGISTRY,
            "registry_id": self.registry_id,
            "stem": self.stem.to_dict(),
            "tower_registry_digest": self.tower_registry_digest,
            "projectors": [projector.to_dict() for projector in self.projectors],
            "status": self.status,
            "selection_authority": self.selection_authority,
            "current_run_mutation": self.current_run_mutation,
        }

    @property
    def registry_digest(self) -> str:
        return _canonical_digest(self.to_dict())


def validate_multimodal_binding(
    tower_registry: ModalityTowerRegistryV1,
    projector_registry: ProjectorRegistryV1,
) -> None:
    """Validate both registries and their immutable Stem/tower binding."""
    _require(tower_registry.stem.stem_digest == projector_registry.stem.stem_digest, "registry Stem digests differ")
    projector_registry.validate_tower_registry(tower_registry)


__all__ = [
    "EVIDENCE_CLASSES",
    "IMMUTABLE_POLICY",
    "ModalityProjectorSpecV1",
    "ModalityTowerRegistryV1",
    "ModalityTowerSpecV1",
    "ProjectorRegistryV1",
    "SCHEMA_PROJECTOR",
    "SCHEMA_PROJECTOR_REGISTRY",
    "SCHEMA_TOWER",
    "SCHEMA_TOWER_REGISTRY",
    "SUPPORTED_MODALITIES",
    "validate_multimodal_binding",
]
