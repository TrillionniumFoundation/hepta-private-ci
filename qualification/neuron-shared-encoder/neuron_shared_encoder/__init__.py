"""Research-only shared-encoder qualification bridge."""

from .modality_registry import (
    BoundModalityRegistriesV1,
    ModalityTowerRegistryV1,
    ModalityTowerSpecV1,
    ProjectorRegistryV1,
    ProjectorSpecV1,
    RegistryError,
    bind_modality_registries,
    registry_manifest,
)
from .registry_bridge import (
    BoundModalityEnvelopeV1,
    SCHEMA_BOUND_ENVELOPE,
    bind_envelope_to_registry,
    bound_envelope_manifest,
)

__all__ = [
    "BoundModalityEnvelopeV1",
    "BoundModalityRegistriesV1",
    "ModalityTowerRegistryV1",
    "ModalityTowerSpecV1",
    "ProjectorRegistryV1",
    "ProjectorSpecV1",
    "RegistryError",
    "SCHEMA_BOUND_ENVELOPE",
    "bind_envelope_to_registry",
    "bind_modality_registries",
    "bound_envelope_manifest",
    "registry_manifest",
]
