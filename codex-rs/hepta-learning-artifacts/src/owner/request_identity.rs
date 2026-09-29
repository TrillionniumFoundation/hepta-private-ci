//! Canonical request integrity preflight for new publication and terminal replay.
//!
//! The same checks execute before a new checkpoint, recovery continuation and
//! historical terminal receipt replay. Historical verification grants no live
//! authority; current lease, signer and withdrawal checks remain owner-hosted.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerTrustV1;
use crate::verify_artifact_admission_v3;

const MAX_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;

pub(super) struct RequestIdentityVerifier {
    registry_id: StableId,
    head_keys: BTreeMap<StableId, [u8; 32]>,
}

impl RequestIdentityVerifier {
    pub(super) fn new(trust: &ArtifactOwnerTrustV1) -> Self {
        Self {
            registry_id: trust.registry_id.clone(),
            head_keys: trust
                .head_signers
                .iter()
                .map(|signer| (signer.signer_id.clone(), signer.verifying_key))
                .collect(),
        }
    }

    pub(super) fn verify(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let admission = &request.admission;
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::IdentityConflict)?;
        let manifest = &admission.validated_manifest.manifest;
        let signed = &request.signed_current_head;
        if request.payload.len() > MAX_PAYLOAD_BYTES {
            return Err(LearningArtifactOwnerServiceError::CapacityExceeded);
        }
        if request.now < admission.admitted_at
            || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
            || signed.witness.registry_id != self.registry_id
        {
            return Err(LearningArtifactOwnerServiceError::IdentityConflict);
        }
        let key_bytes = self
            .head_keys
            .get(&signed.witness.signer_id)
            .ok_or(LearningArtifactOwnerServiceError::StaleOwner)?;
        if Digest32::of_bytes(key_bytes) != signed.witness.signing_key_digest {
            return Err(LearningArtifactOwnerServiceError::IdentityConflict);
        }
        let key = VerifyingKey::from_bytes(key_bytes)
            .map_err(|_| LearningArtifactOwnerServiceError::IdentityConflict)?;
        key.verify_strict(
            &signed.signing_bytes(),
            &Signature::from_bytes(&signed.signature),
        )
        .map_err(|_| LearningArtifactOwnerServiceError::IdentityConflict)
    }
}
