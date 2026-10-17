#!/usr/bin/env python3
"""Negative and positive tests for the source-bound modality registries."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("modality_registry", ROOT / "neuron_shared_encoder" / "modality_registry.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BoundModalityRegistriesV1 = MODULE.BoundModalityRegistriesV1
ModalityTowerRegistryV1 = MODULE.ModalityTowerRegistryV1
ModalityTowerSpecV1 = MODULE.ModalityTowerSpecV1
ProjectorRegistryV1 = MODULE.ProjectorRegistryV1
ProjectorSpecV1 = MODULE.ProjectorSpecV1
RegistryError = MODULE.RegistryError
bind_modality_registries = MODULE.bind_modality_registries
registry_manifest = MODULE.registry_manifest


def digest(letter: str) -> str:
    return letter * 64


class FakeStem:
    stem_digest = digest("a")
    hidden_width = 384
    modality_projectors = ("audio-projector", "image-projector", "text-projector", "video-projector")


def tower(modality: str, width: int, *, temporal: bool = False, regions: bool = False) -> ModalityTowerSpecV1:
    return ModalityTowerSpecV1(
        modality=modality,
        tower_id=f"{modality}-tower",
        tower_digest=digest(modality[0]),
        preprocessor_digest=digest("p"),
        output_width=width,
        max_input_tokens=4096,
        supports_streaming=modality in {"audio", "video"},
        supports_regions=regions,
        supports_temporal=temporal,
    )


def projector(modality: str, input_width: int, *, kind: str = "mlp") -> ProjectorSpecV1:
    return ProjectorSpecV1(
        modality=modality,
        projector_id=f"{modality}-projector",
        projector_digest=digest(modality[0]),
        input_width=input_width,
        output_width=384,
        slots=32,
        kind=kind,
    )


def valid_towers() -> ModalityTowerRegistryV1:
    return ModalityTowerRegistryV1(
        stem_digest=FakeStem.stem_digest,
        towers=(
            tower("audio", 768, temporal=True),
            tower("image", 768, regions=True),
            tower("text", 384),
            tower("video", 1024, temporal=True),
        ),
    )


def valid_projectors() -> ProjectorRegistryV1:
    return ProjectorRegistryV1(
        stem_digest=FakeStem.stem_digest,
        target_width=384,
        projectors=(
            projector("audio", 768, kind="perceiver"),
            projector("image", 768),
            projector("text", 384, kind="linear"),
            projector("video", 1024, kind="gated_cross_attention"),
        ),
    )


class ModalityRegistryTests(unittest.TestCase):
    def test_valid_binding_is_readonly_and_denied(self) -> None:
        bound = bind_modality_registries(FakeStem(), valid_towers(), valid_projectors())
        self.assertIsInstance(bound, BoundModalityRegistriesV1)
        self.assertEqual(bound.modalities, ("audio", "image", "text", "video"))
        self.assertEqual(bound.authority, "DENY_ALL")
        self.assertTrue(bound.source_bound)

    def test_registry_digest_is_deterministic(self) -> None:
        self.assertEqual(valid_towers().registry_digest, valid_towers().registry_digest)
        self.assertEqual(valid_projectors().registry_digest, valid_projectors().registry_digest)

    def test_manifest_is_non_authorizing(self) -> None:
        towers = valid_towers()
        projectors = valid_projectors()
        bound = bind_modality_registries(FakeStem(), towers, projectors)
        manifest = registry_manifest(towers, projectors, binding=bound)
        self.assertEqual(manifest["authority"], "DENY_ALL")
        self.assertEqual(manifest["binding"]["authority"], "DENY_ALL")
        self.assertEqual(manifest["binding"]["stem_digest"], FakeStem.stem_digest)

    def test_duplicate_tower_modality_rejected(self) -> None:
        towers = valid_towers()
        with self.assertRaises(RegistryError):
            ModalityTowerRegistryV1(FakeStem.stem_digest, (towers.towers[0], towers.towers[0]))

    def test_unfrozen_tower_rejected(self) -> None:
        with self.assertRaises(RegistryError):
            tower_obj = replace(tower("text", 384), frozen=False)
            ModalityTowerRegistryV1(FakeStem.stem_digest, (tower_obj,))

    def test_unbound_projector_rejected(self) -> None:
        with self.assertRaises(RegistryError):
            ProjectorSpecV1(
                modality="text",
                projector_id="text-projector",
                projector_digest=digest("b"),
                input_width=384,
                output_width=384,
                slots=32,
                kind="linear",
                source_bound=False,
            )

    def test_width_mismatch_rejected_at_binding(self) -> None:
        bad_projectors = replace(
            valid_projectors(),
            projectors=(
                projector("audio", 777, kind="perceiver"),
                projector("image", 768),
                projector("text", 384, kind="linear"),
                projector("video", 1024, kind="gated_cross_attention"),
            ),
        )
        with self.assertRaises(RegistryError):
            bind_modality_registries(FakeStem(), valid_towers(), bad_projectors)

    def test_missing_stem_projector_registration_rejected(self) -> None:
        stem = FakeStem()
        stem.modality_projectors = ("text-projector",)
        with self.assertRaises(RegistryError):
            bind_modality_registries(stem, valid_towers(), valid_projectors())

    def test_temporal_capability_is_required(self) -> None:
        with self.assertRaises(RegistryError):
            tower("video", 1024, temporal=False)

    def test_projector_output_must_match_stem_width(self) -> None:
        with self.assertRaises(RegistryError):
            ProjectorRegistryV1(
                stem_digest=FakeStem.stem_digest,
                target_width=384,
                projectors=(replace(projector("text", 384), output_width=256),),
            )


if __name__ == "__main__":
    unittest.main()
