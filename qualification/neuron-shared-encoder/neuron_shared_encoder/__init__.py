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
from .stem_qualification import (
    CheckpointRefV1,
    SCHEMA_COMPONENT,
    SCHEMA_RESOURCE,
    ComponentResourceBundleV1,
    ComponentResourceReceiptV1,
    MetricIntervalV1,
    SourceDisjointSplitV1,
    StemQualificationError,
    StemQualificationRunV1,
    qualify_from_receipt,
)
from .registry_bridge import (
    BoundModalityEnvelopeV1,
    SCHEMA_BOUND_ENVELOPE,
    bind_envelope_to_registry,
    bound_envelope_manifest,
)

__all__ = [
    "BoundModalityEnvelopeV1",
    "CheckpointRefV1",
    "SCHEMA_COMPONENT",
    "SCHEMA_RESOURCE",
    "ComponentResourceBundleV1",
    "ComponentResourceReceiptV1",
    "BoundModalityRegistriesV1",
    "MetricIntervalV1",
    "ModalityTowerRegistryV1",
    "ModalityTowerSpecV1",
    "ProjectorRegistryV1",
    "ProjectorSpecV1",
    "RegistryError",
    "SCHEMA_BOUND_ENVELOPE",
    "SourceDisjointSplitV1",
    "StemQualificationError",
    "StemQualificationRunV1",
    "bind_envelope_to_registry",
    "bind_modality_registries",
    "bound_envelope_manifest",
    "qualify_from_receipt",
    "registry_manifest",
]
