#!/usr/bin/env python3
"""Contract tests for binding ModalityEnvelopeV1 to frozen registries."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REGISTRY = load("modality_registry", ROOT / "neuron_shared_encoder" / "modality_registry.py")
BRIDGE = load("registry_bridge", ROOT / "neuron_shared_encoder" / "registry_bridge.py")
ARTIFACT = load(
    "stem_transfer_cell_artifact",
    ROOT.parent / "stem-transfer-cell-artifact-p0" / "stem_transfer_cell_artifact.py",
)

ModalityTowerRegistryV1 = REGISTRY.ModalityTowerRegistryV1
ModalityTowerSpecV1 = REGISTRY.ModalityTowerSpecV1
ProjectorRegistryV1 = REGISTRY.ProjectorRegistryV1
ProjectorSpecV1 = REGISTRY.ProjectorSpecV1
RegistryError = REGISTRY.RegistryError
StemManifestV1 = ARTIFACT.StemManifestV1
ModalityEnvelopeV1 = ARTIFACT.ModalityEnvelopeV1
BoundModalityEnvelopeV1 = BRIDGE.BoundModalityEnvelopeV1
bind_envelope_to_registry = BRIDGE.bind_envelope_to_registry
bound_envelope_manifest = BRIDGE.bound_envelope_manifest


def digest(letter: str) -> str:
    return letter * 64


STEM = StemManifestV1(
    stem_id="stem-a",
    stem_digest=digest("a"),
    tokenizer_digest=digest("b"),
    preprocessor_digest=digest("c"),
    adapter_basis_digest=digest("d"),
    hidden_width=384,
    modality_projectors=("audio-projector", "image-projector", "text-projector", "video-projector"),
)


def tower(modality: str, width: int, *, temporal: bool = False, regions: bool = False) -> ModalityTowerSpecV1:
    return ModalityTowerSpecV1(
        modality=modality,
        tower_id=f"{modality}-tower",
        tower_digest=digest({"audio": "1", "image": "2", "text": "3", "video": "4"}[modality]),
        preprocessor_digest=digest("e"),
        output_width=width,
        max_input_tokens=4096,
        supports_streaming=modality in {"audio", "video"},
        supports_regions=regions,
        supports_temporal=temporal,
    )


def projector(modality: str, input_width: int) -> ProjectorSpecV1:
    return ProjectorSpecV1(
        modality=modality,
        projector_id=f"{modality}-projector",
        projector_digest=digest({"audio": "5", "image": "6", "text": "7", "video": "8"}[modality]),
        input_width=input_width,
        output_width=384,
        slots=32,
        kind="perceiver" if modality in {"audio", "video"} else "linear",
    )


TOWERS = ModalityTowerRegistryV1(
    stem_digest=STEM.stem_digest,
    towers=(
        tower("audio", 768, temporal=True),
        tower("image", 768, regions=True),
        tower("text", 384),
        tower("video", 1024, temporal=True),
    ),
)

PROJECTORS = ProjectorRegistryV1(
    stem_digest=STEM.stem_digest,
    target_width=384,
    projectors=(
        projector("audio", 768),
        projector("image", 768),
        projector("text", 384),
        projector("video", 1024),
    ),
)


def envelope(modality: str, *, slots: int = 16, regions: int = 0):
    projector_digest = PROJECTORS.projector_for(modality).projector_digest
    temporal = 1000.0 if modality in {"audio", "video"} else None
    return ModalityEnvelopeV1(
        modality=modality,
        stem_digest=STEM.stem_digest,
        raw_digest=digest("9"),
        feature_digest=digest("f"),
        projector_digest=projector_digest,
        latent_width=384,
        slots=slots,
        temporal_span_ms=temporal,
        region_count=regions,
    )


class RegistryBridgeTests(unittest.TestCase):
    def test_audio_envelope_binds_to_frozen_registries(self) -> None:
        bound = bind_envelope_to_registry(envelope("audio"), STEM, TOWERS, PROJECTORS)
        self.assertIsInstance(bound, BoundModalityEnvelopeV1)
        self.assertEqual(bound.projector_id, "audio-projector")
        self.assertEqual(bound.tower_id, "audio-tower")
        self.assertEqual(bound.authority, "DENY_ALL")
        self.assertTrue(bound.source_bound and bound.readonly)

    def test_image_regions_are_checked_against_tower_budget(self) -> None:
        bound = bind_envelope_to_registry(envelope("image", regions=128), STEM, TOWERS, PROJECTORS)
        self.assertEqual(bound.region_count, 128)

    def test_receipt_fragment_is_non_authorizing_and_deterministic(self) -> None:
        bound = bind_envelope_to_registry(envelope("text"), STEM, TOWERS, PROJECTORS)
        first = bound_envelope_manifest(bound)
        second = bound_envelope_manifest(bound)
        self.assertEqual(first, second)
        self.assertEqual(first["authority"], "DENY_ALL")
        self.assertEqual(first["envelope"]["schema"], "hepta.modality.bound-envelope.v1")

    def test_projector_digest_mismatch_rejected(self) -> None:
        bad = replace(envelope("text"), projector_digest=digest("0"))
        with self.assertRaises(RegistryError):
            bind_envelope_to_registry(bad, STEM, TOWERS, PROJECTORS)

    def test_stem_digest_mismatch_rejected(self) -> None:
        bad = replace(envelope("text"), stem_digest=digest("1"))
        with self.assertRaises(RegistryError):
            bind_envelope_to_registry(bad, STEM, TOWERS, PROJECTORS)

    def test_slot_budget_rejected(self) -> None:
        with self.assertRaises(RegistryError):
            bind_envelope_to_registry(envelope("audio", slots=33), STEM, TOWERS, PROJECTORS)

    def test_latent_width_mismatch_rejected(self) -> None:
        bad = replace(envelope("text"), latent_width=256)
        with self.assertRaises(RegistryError):
            bind_envelope_to_registry(bad, STEM, TOWERS, PROJECTORS)

    def test_image_tower_must_declare_region_support(self) -> None:
        with self.assertRaises(RegistryError):
            ModalityTowerSpecV1(
                modality="image",
                tower_id="image-tower",
                tower_digest=digest("2"),
                preprocessor_digest=digest("e"),
                output_width=768,
                max_input_tokens=4096,
                supports_regions=False,
            )

    def test_bound_producer_identifier_must_be_stable(self) -> None:
        bound = bind_envelope_to_registry(envelope("text"), STEM, TOWERS, PROJECTORS)
        with self.assertRaises(RegistryError):
            replace(bound, tower_id="bad producer id").__post_init__()

    def test_authority_cannot_be_smuggled_into_bound_envelope(self) -> None:
        with self.assertRaises(RegistryError):
            BoundModalityEnvelopeV1(
                modality="text",
                stem_digest=STEM.stem_digest,
                raw_digest=digest("9"),
                feature_digest=digest("f"),
                projector_digest=PROJECTORS.projector_for("text").projector_digest,
                tower_id="text-tower",
                projector_id="text-projector",
                tower_registry_digest=TOWERS.registry_digest,
                projector_registry_digest=PROJECTORS.registry_digest,
                latent_width=384,
                slots=8,
                authority="PRODUCTION",
            )


if __name__ == "__main__":
    unittest.main()
