from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stem-transfer-cell-artifact-p0"))

from neuron_shared_encoder.modality_registry import (  # noqa: E402
    ModalityProjectorSpecV1,
    ModalityTowerRegistryV1,
    ModalityTowerSpecV1,
    ProjectorRegistryV1,
    SUPPORTED_MODALITIES,
    validate_multimodal_binding,
)
from stem_transfer_cell_artifact import ContractError, StemManifestV1  # noqa: E402


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


STEM = StemManifestV1(
    stem_id="stem.shared.v1",
    stem_digest=digest("stem"),
    tokenizer_digest=digest("tokenizer"),
    preprocessor_digest=digest("preprocessor"),
    adapter_basis_digest=digest("basis"),
    hidden_width=1024,
    modality_projectors=SUPPORTED_MODALITIES,
)


def tower(modality: str, **overrides):
    values = dict(
        tower_id=f"tower.{modality}.v1",
        modality=modality,
        tower_digest=digest(f"tower-{modality}"),
        preprocessor_digest=digest(f"pre-{modality}"),
        output_width=768,
        max_slots=64,
        parameter_count=1000,
    )
    if modality in {"audio", "video"}:
        values["temporal_resolution_hz"] = 25.0
    values.update(overrides)
    return ModalityTowerSpecV1(**values)


def towers(**overrides):
    result = tuple(tower(modality, **overrides.get(modality, {})) for modality in SUPPORTED_MODALITIES)
    return tuple(sorted(result, key=lambda item: item.tower_id))


def projector(modality: str, **overrides):
    values = dict(
        projector_id=modality,
        modality=modality,
        projector_digest=digest(f"projector-{modality}"),
        source_tower_id=f"tower.{modality}.v1",
        stem_digest=STEM.stem_digest,
        input_width=768,
        latent_width=STEM.hidden_width,
        max_slots=32,
        resident_params=100,
        active_params=80,
    )
    values.update(overrides)
    return ModalityProjectorSpecV1(**values)


def registries():
    tower_registry = ModalityTowerRegistryV1("towers.v1", STEM, towers())
    projector_registry = ProjectorRegistryV1(
        "projectors.v1",
        STEM,
        tower_registry.registry_digest,
        tuple(projector(modality) for modality in SUPPORTED_MODALITIES),
    )
    validate_multimodal_binding(tower_registry, projector_registry)
    return tower_registry, projector_registry


class ModalityRegistryTests(unittest.TestCase):
    def test_four_modality_registries_bind_to_same_stem(self):
        towers_registry, projectors_registry = registries()
        self.assertEqual(towers_registry.stem.stem_digest, projectors_registry.stem.stem_digest)
        self.assertEqual(set(towers_registry.tower_for(m).modality for m in SUPPORTED_MODALITIES), set(SUPPORTED_MODALITIES))
        self.assertEqual(projectors_registry.projector_for("image").latent_width, STEM.hidden_width)

    def test_registry_constructs_digest_bound_envelopes(self):
        _, projectors_registry = registries()
        envelope = projectors_registry.envelope(
            "video",
            raw_digest=digest("raw-video"),
            feature_digest=digest("features-video"),
            slots=8,
            temporal_span_ms=400.0,
        )
        self.assertEqual(envelope.projector_digest, projectors_registry.projector_for("video").projector_digest)
        self.assertEqual(envelope.stem_digest, STEM.stem_digest)
        self.assertTrue(envelope.readonly)

    def test_registry_rejects_duplicate_or_missing_modality(self):
        with self.assertRaises(ContractError):
            ModalityTowerRegistryV1("bad.v1", STEM, towers()[:-1] + (towers()[0],))
        with self.assertRaises(ContractError):
            ModalityTowerRegistryV1("bad.v1", STEM, tuple(tower(m) for m in ("audio", "image", "text", "text")))

    def test_registry_rejects_stem_without_all_modality_projectors(self):
        partial_stem = StemManifestV1(**{**STEM.__dict__, "modality_projectors": ("audio", "image", "text")})
        with self.assertRaises(ContractError):
            ModalityTowerRegistryV1("bad.v1", partial_stem, towers())

    def test_registry_rejects_unsorted_tower_ids(self):
        ordered = towers()
        with self.assertRaises(ContractError):
            ModalityTowerRegistryV1("bad.v1", STEM, tuple(reversed(ordered)))

    def test_registry_rejects_nonimmutable_tower(self):
        with self.assertRaises(ContractError):
            tower("text", frozen=False)
        with self.assertRaises(ContractError):
            tower("text", current_run_mutation=True)

    def test_registry_rejects_nonfinite_temporal_resolution(self):
        with self.assertRaises(ContractError):
            tower("audio", temporal_resolution_hz=float("nan"))
        with self.assertRaises(ContractError):
            tower("video", temporal_resolution_hz=float("inf"))

    def test_real_evidence_requires_receipt_without_renaming_evidence_class(self):
        with self.assertRaises(ContractError):
            tower("text", evidence_class="REAL_MODEL_LOCAL_QUALIFICATION")
        qualified = tower(
            "text",
            evidence_class="REAL_MODEL_LOCAL_QUALIFICATION",
            checkpoint_receipt_digest=digest("receipt"),
        )
        self.assertEqual(qualified.evidence_class, "REAL_MODEL_LOCAL_QUALIFICATION")

    def test_projector_ids_must_match_stem_manifest(self):
        tower_registry, _ = registries()
        bad = tuple(projector(m) for m in ("audio", "image", "text", "video"))
        bad = (ModalityProjectorSpecV1(**{**bad[0].__dict__, "projector_id": "wrong"}), *bad[1:])
        with self.assertRaises(ContractError):
            ProjectorRegistryV1("bad.v1", STEM, tower_registry.registry_digest, bad)

    def test_projector_requires_frozen_stem_width_and_tower_binding(self):
        tower_registry, _ = registries()
        with self.assertRaises(ContractError):
            ProjectorRegistryV1(
                "bad.v1",
                STEM,
                tower_registry.registry_digest,
                tuple(projector(m, latent_width=512) if m == "image" else projector(m) for m in SUPPORTED_MODALITIES),
            )
        with self.assertRaises(ContractError):
            ProjectorRegistryV1(
                "bad.v1",
                STEM,
                tower_registry.registry_digest,
                tuple(projector(m, stem_digest=digest("other")) if m == "audio" else projector(m) for m in SUPPORTED_MODALITIES),
            )

    def test_validate_binding_rejects_tower_digest_or_width_mismatch(self):
        _, projector_registry = registries()
        mismatched_tower_registry = ModalityTowerRegistryV1(
            "towers.bad.v1",
            STEM,
            tuple(tower(m, output_width=769) if m == "image" else tower(m) for m in SUPPORTED_MODALITIES),
        )
        with self.assertRaises(ContractError):
            validate_multimodal_binding(mismatched_tower_registry, projector_registry)

    def test_envelope_rejects_wrong_temporal_or_slot_contract(self):
        _, projectors_registry = registries()
        with self.assertRaises(ContractError):
            projectors_registry.envelope(
                "audio",
                raw_digest=digest("raw"),
                feature_digest=digest("feature"),
                slots=2,
            )
        with self.assertRaises(ContractError):
            projectors_registry.envelope(
                "image",
                raw_digest=digest("raw"),
                feature_digest=digest("feature"),
                slots=64,
                region_count=1,
            )

    def test_registries_cannot_grant_selection_or_runtime_authority(self):
        with self.assertRaises(ContractError):
            ModalityTowerRegistryV1("bad.v1", STEM, towers(), selection_authority=True)
        tower_registry, _ = registries()
        with self.assertRaises(ContractError):
            ProjectorRegistryV1(
                "bad.v1",
                STEM,
                tower_registry.registry_digest,
                tuple(projector(m) for m in SUPPORTED_MODALITIES),
                current_run_mutation=True,
            )


if __name__ == "__main__":
    unittest.main()
