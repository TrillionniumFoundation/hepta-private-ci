//! Existing controller signatures are input data, never a local issuer.

use std::path::PathBuf;

use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::super::refused;
use crate::AgentdError;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(in crate::production_launcher::post_a_q24) struct ArtifactFilesData {
    pub writer_lease: PathBuf,
    pub candidate_head: PathBuf,
    pub independent_selection: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WriterLeaseData {
    lease_id: String,
    producer_id: String,
    registry_id: String,
    withdrawal_scope_digest: [u8; 32],
    signer_id: String,
    signing_key_digest: [u8; 32],
    authority_epoch: u64,
    lease_generation: u64,
    issued_at: u64,
    expires_at: u64,
    signature: Vec<u8>,
}

impl WriterLeaseData {
    pub(super) fn original_signed_lease(&self) -> Result<SignedArtifactWriterLeaseV1, AgentdError> {
        Ok(SignedArtifactWriterLeaseV1 {
            lease_id: StableId::new(&self.lease_id).map_err(refused)?,
            producer_id: StableId::new(&self.producer_id).map_err(refused)?,
            registry_id: StableId::new(&self.registry_id).map_err(refused)?,
            withdrawal_scope_digest: Digest32::from_array(self.withdrawal_scope_digest),
            signer_id: StableId::new(&self.signer_id).map_err(refused)?,
            signing_key_digest: Digest32::from_array(self.signing_key_digest),
            authority_epoch: self.authority_epoch,
            lease_generation: self.lease_generation,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            signature: self
                .signature
                .as_slice()
                .try_into()
                .map_err(|_| refused("original Artifact writer signature must have 64 bytes"))?,
        })
    }
}
