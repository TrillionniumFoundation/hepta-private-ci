//! Bounded process input mapping. Raw fields are not verified capabilities.

use super::cognitive_process_wire::*;
use serde::Deserialize;
use serde::Serialize;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ArtifactManifestRaw {
    pub artifact_id: Id,
    pub kind: ArtifactKindRaw,
    pub generation: GenerationWire,
    pub predecessor_id: Option<Id>,
    pub content_digest: Digest,
    pub objective_digest: Digest,
    pub support_digest: Digest,
    pub producer_id: Id,
    pub compatibility_digest: Digest,
    pub encoded_size_bytes: u64,
}

impl From<ArtifactManifestRaw> for codex_hepta_learning_artifacts::ArtifactManifest {
    fn from(raw: ArtifactManifestRaw) -> Self {
        Self {
            artifact_id: raw.artifact_id.into(),
            kind: raw.kind.into(),
            generation: raw.generation.into(),
            predecessor_id: raw.predecessor_id.map(std::convert::Into::into),
            content_digest: raw.content_digest.into(),
            objective_digest: raw.objective_digest.into(),
            support_digest: raw.support_digest.into(),
            producer_id: raw.producer_id.into(),
            compatibility_digest: raw.compatibility_digest.into(),
            encoded_size_bytes: raw.encoded_size_bytes,
        }
    }
}

impl From<codex_hepta_learning_artifacts::ArtifactManifest> for ArtifactManifestRaw {
    fn from(raw: codex_hepta_learning_artifacts::ArtifactManifest) -> Self {
        Self {
            artifact_id: raw.artifact_id.into(),
            kind: raw.kind.into(),
            generation: raw.generation.into(),
            predecessor_id: raw.predecessor_id.map(std::convert::Into::into),
            content_digest: raw.content_digest.into(),
            objective_digest: raw.objective_digest.into(),
            support_digest: raw.support_digest.into(),
            producer_id: raw.producer_id.into(),
            compatibility_digest: raw.compatibility_digest.into(),
            encoded_size_bytes: raw.encoded_size_bytes,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct LearningArtifactManifestV2Raw {
    pub artifact_id: Id,
    pub kind: ArtifactKindRaw,
    pub generation: GenerationWire,
    pub provenance_mode: ProvenanceModeV1Raw,
    pub source_dataset_digests: Vec<Digest>,
    pub lineage_digests: Vec<Digest>,
    pub predecessor_ids: Vec<Id>,
    pub rollback_predecessor: Option<Id>,
    pub bytes_digest: Digest,
    pub encoded_size_bytes: u64,
    pub training_code_digest: Digest,
    pub runtime_tuple_digest: Digest,
    pub device_profile_digest: Digest,
    pub objective_class_digest: Digest,
    pub compatibility_digest: Digest,
    pub schema_profile_digest: Digest,
    pub normalization_digest: Digest,
    pub producer_id: Id,
    pub created_at: u64,
    pub expires_at: u64,
}

impl From<LearningArtifactManifestV2Raw>
    for codex_hepta_learning_artifacts::LearningArtifactManifestV2
{
    fn from(raw: LearningArtifactManifestV2Raw) -> Self {
        Self {
            artifact_id: raw.artifact_id.into(),
            kind: raw.kind.into(),
            generation: raw.generation.into(),
            provenance_mode: raw.provenance_mode.into(),
            source_dataset_digests: raw
                .source_dataset_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            lineage_digests: raw
                .lineage_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            predecessor_ids: raw
                .predecessor_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            rollback_predecessor: raw.rollback_predecessor.map(std::convert::Into::into),
            bytes_digest: raw.bytes_digest.into(),
            encoded_size_bytes: raw.encoded_size_bytes,
            training_code_digest: raw.training_code_digest.into(),
            runtime_tuple_digest: raw.runtime_tuple_digest.into(),
            device_profile_digest: raw.device_profile_digest.into(),
            objective_class_digest: raw.objective_class_digest.into(),
            compatibility_digest: raw.compatibility_digest.into(),
            schema_profile_digest: raw.schema_profile_digest.into(),
            normalization_digest: raw.normalization_digest.into(),
            producer_id: raw.producer_id.into(),
            created_at: raw.created_at,
            expires_at: raw.expires_at,
        }
    }
}

impl From<codex_hepta_learning_artifacts::LearningArtifactManifestV2>
    for LearningArtifactManifestV2Raw
{
    fn from(raw: codex_hepta_learning_artifacts::LearningArtifactManifestV2) -> Self {
        Self {
            artifact_id: raw.artifact_id.into(),
            kind: raw.kind.into(),
            generation: raw.generation.into(),
            provenance_mode: raw.provenance_mode.into(),
            source_dataset_digests: raw
                .source_dataset_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            lineage_digests: raw
                .lineage_digests
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            predecessor_ids: raw
                .predecessor_ids
                .into_iter()
                .map(std::convert::Into::into)
                .collect(),
            rollback_predecessor: raw.rollback_predecessor.map(std::convert::Into::into),
            bytes_digest: raw.bytes_digest.into(),
            encoded_size_bytes: raw.encoded_size_bytes,
            training_code_digest: raw.training_code_digest.into(),
            runtime_tuple_digest: raw.runtime_tuple_digest.into(),
            device_profile_digest: raw.device_profile_digest.into(),
            objective_class_digest: raw.objective_class_digest.into(),
            compatibility_digest: raw.compatibility_digest.into(),
            schema_profile_digest: raw.schema_profile_digest.into(),
            normalization_digest: raw.normalization_digest.into(),
            producer_id: raw.producer_id.into(),
            created_at: raw.created_at,
            expires_at: raw.expires_at,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RegistrySnapshotReceiptRaw {
    pub binding: Digest,
    pub head_digest: Digest,
    pub file_digest: Digest,
    pub records: usize,
    pub encoded_bytes: usize,
}

impl From<RegistrySnapshotReceiptRaw> for codex_hepta_learning_artifacts::RegistrySnapshotReceipt {
    fn from(raw: RegistrySnapshotReceiptRaw) -> Self {
        Self {
            binding: raw.binding.into(),
            head_digest: raw.head_digest.into(),
            file_digest: raw.file_digest.into(),
            records: raw.records,
            encoded_bytes: raw.encoded_bytes,
        }
    }
}

impl From<codex_hepta_learning_artifacts::RegistrySnapshotReceipt> for RegistrySnapshotReceiptRaw {
    fn from(raw: codex_hepta_learning_artifacts::RegistrySnapshotReceipt) -> Self {
        Self {
            binding: raw.binding.into(),
            head_digest: raw.head_digest.into(),
            file_digest: raw.file_digest.into(),
            records: raw.records,
            encoded_bytes: raw.encoded_bytes,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PinnedCandidateSpecRaw {
    pub registry_receipt: RegistrySnapshotReceiptRaw,
    pub manifest: ArtifactManifestRaw,
}

impl From<PinnedCandidateSpecRaw> for codex_hepta_learning_artifacts::PinnedCandidateSpec {
    fn from(raw: PinnedCandidateSpecRaw) -> Self {
        Self {
            registry_receipt: raw.registry_receipt.into(),
            manifest: raw.manifest.into(),
        }
    }
}

impl From<codex_hepta_learning_artifacts::PinnedCandidateSpec> for PinnedCandidateSpecRaw {
    fn from(raw: codex_hepta_learning_artifacts::PinnedCandidateSpec) -> Self {
        Self {
            registry_receipt: raw.registry_receipt.into(),
            manifest: raw.manifest.into(),
        }
    }
}

#[derive(Debug, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TabularPayloadPinV1Raw {
    pub payload_digest: Digest,
    pub artifact_digest: Digest,
    pub objective_digest: Digest,
    pub dataset_digest: Digest,
    pub sensor_core_digest: Digest,
    pub training_profile_digest: Digest,
    pub generation: GenerationWire,
}

impl From<TabularPayloadPinV1Raw> for codex_hepta_bellman_operator::TabularPayloadPinV1 {
    fn from(raw: TabularPayloadPinV1Raw) -> Self {
        Self {
            payload_digest: raw.payload_digest.into(),
            artifact_digest: raw.artifact_digest.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            sensor_core_digest: raw.sensor_core_digest.into(),
            training_profile_digest: raw.training_profile_digest.into(),
            generation: raw.generation.into(),
        }
    }
}

impl From<codex_hepta_bellman_operator::TabularPayloadPinV1> for TabularPayloadPinV1Raw {
    fn from(raw: codex_hepta_bellman_operator::TabularPayloadPinV1) -> Self {
        Self {
            payload_digest: raw.payload_digest.into(),
            artifact_digest: raw.artifact_digest.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            sensor_core_digest: raw.sensor_core_digest.into(),
            training_profile_digest: raw.training_profile_digest.into(),
            generation: raw.generation.into(),
        }
    }
}
