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
