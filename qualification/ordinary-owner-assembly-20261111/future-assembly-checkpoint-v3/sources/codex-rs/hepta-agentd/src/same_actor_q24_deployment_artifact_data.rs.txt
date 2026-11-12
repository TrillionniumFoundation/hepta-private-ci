//! Supplied Artifact writer leases and manifests are data, not admission.
//! The existing signature verifier and withdrawal-bound admission consume the
//! exact original values; no key, lease, generation or predecessor is invented.

use codex_hepta_learning_artifacts::{
    ArtifactKind, LearningArtifactManifestV2, ProvenanceModeV1, SignedArtifactWriterLeaseV1,
};
use codex_hepta_types::{Digest32, Generation, StableId};
use serde::{Deserialize, Serialize};
use crate::AgentdError;
use super::learning_data::required_option;
use super::{deployment_error, deployment_refused};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalArtifactWriterData {
    pub lease_id: String,
    pub producer_id: String,
    pub registry_id: String,
    pub withdrawal_scope_digest: [u8; 32],
    pub signer_id: String,
    pub signing_key_digest: [u8; 32],
    pub authority_epoch: u64,
    pub lease_generation: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub signature: Vec<u8>,
}

impl OriginalArtifactWriterData {
    pub(super) fn original(&self) -> Result<SignedArtifactWriterLeaseV1, AgentdError> {
        Ok(SignedArtifactWriterLeaseV1 {
            lease_id: StableId::new(&self.lease_id).map_err(deployment_error)?,
            producer_id: StableId::new(&self.producer_id).map_err(deployment_error)?,
            registry_id: StableId::new(&self.registry_id).map_err(deployment_error)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            signer_id: StableId::new(&self.signer_id).map_err(deployment_error)?,
            signing_key_digest: Digest32::from_array(self.signing_key_digest),
            authority_epoch: self.authority_epoch, lease_generation: self.lease_generation,
            issued_at: self.issued_at, expires_at: self.expires_at,
            signature: self.signature.as_slice().try_into()
                .map_err(|_| deployment_refused("original Artifact lease signature must have 64 bytes"))?,
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalArtifactKindData { Model }

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalArtifactProvenanceData { DatasetDerived, DatasetIndependent }

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalArtifactManifestData {
    pub artifact_id: String,
    pub kind: OriginalArtifactKindData,
    pub generation: u64,
    pub provenance_mode: OriginalArtifactProvenanceData,
    pub source_dataset_digests: Vec<[u8; 32]>,
    pub lineage_digests: Vec<[u8; 32]>,
    pub predecessor_ids: Vec<String>,
    #[serde(deserialize_with = "required_option")]
    pub rollback_predecessor: Option<String>,
    pub bytes_digest: [u8; 32],
    pub encoded_size_bytes: u64,
    pub training_code_digest: [u8; 32],
    pub runtime_tuple_digest: [u8; 32],
    pub device_profile_digest: [u8; 32],
    pub objective_class_digest: [u8; 32],
    pub compatibility_digest: [u8; 32],
    pub schema_profile_digest: [u8; 32],
    pub normalization_digest: [u8; 32],
    pub producer_id: String,
    pub created_at: u64,
    pub expires_at: u64,
}

impl OriginalArtifactManifestData {
    pub(super) fn original(&self) -> Result<LearningArtifactManifestV2, AgentdError> {
        Ok(LearningArtifactManifestV2 {
            artifact_id: StableId::new(&self.artifact_id).map_err(deployment_error)?,
            kind: match self.kind { OriginalArtifactKindData::Model => ArtifactKind::Model },
            generation: Generation::new(self.generation).map_err(deployment_error)?,
            provenance_mode: match self.provenance_mode {
                OriginalArtifactProvenanceData::DatasetDerived => ProvenanceModeV1::DatasetDerived,
                OriginalArtifactProvenanceData::DatasetIndependent => ProvenanceModeV1::DatasetIndependent,
            },
            source_dataset_digests: self.source_dataset_digests.iter().copied().map(Digest32::from_array).collect(),
            lineage_digests: self.lineage_digests.iter().copied().map(Digest32::from_array).collect(),
            predecessor_ids: self.predecessor_ids.iter().map(StableId::new)
                .collect::<Result<_, _>>().map_err(deployment_error)?,
            rollback_predecessor: self.rollback_predecessor.as_ref().map(StableId::new)
                .transpose().map_err(deployment_error)?,
            bytes_digest: Digest32::from_array(self.bytes_digest),
            encoded_size_bytes: self.encoded_size_bytes,
            training_code_digest: Digest32::from_array(self.training_code_digest),
            runtime_tuple_digest: Digest32::from_array(self.runtime_tuple_digest),
            device_profile_digest: Digest32::from_array(self.device_profile_digest),
            objective_class_digest: Digest32::from_array(self.objective_class_digest),
            compatibility_digest: Digest32::from_array(self.compatibility_digest),
            schema_profile_digest: Digest32::from_array(self.schema_profile_digest),
            normalization_digest: Digest32::from_array(self.normalization_digest),
            producer_id: StableId::new(&self.producer_id).map_err(deployment_error)?,
            created_at: self.created_at, expires_at: self.expires_at,
        })
    }
}
