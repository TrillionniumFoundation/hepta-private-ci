//! One canonical request identity for live publication and historical replay.
//! Trusted time on retry is observation, not a new operation identity.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerTrustV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::verify_artifact_admission_v3;

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
    ) -> Result<Digest32, LearningArtifactOwnerServiceError> {
        let manifest = &request.admission.validated_manifest.manifest;
        if request.now < request.admission.admitted_at
            || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || request.payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        self.verify_metadata(
            &request.operation_id,
            &request.admission,
            &request.signed_current_head,
            request.expected_registry_predecessor_head,
        )
    }

    /// Reconstruct integrity from retained metadata without loading payload bytes.
    /// Historical validation does not renew a lease, signer grant or withdrawal.
    pub(super) fn verify_metadata(
        &self,
        operation_id: &StableId,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        signed: &SignedCurrentArtifactHeadV1,
        predecessor: Digest32,
    ) -> Result<Digest32, LearningArtifactOwnerServiceError> {
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        if signed.witness.registry_id != self.registry_id
            || signed.withdrawal_scope_digest != admission.withdrawal_scope_digest
            || signed.witness.predecessor_head_digest != predecessor
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let key_bytes = self
            .head_keys
            .get(&signed.witness.signer_id)
            .ok_or(LearningArtifactOwnerServiceError::RequestMismatch)?;
        if Digest32::of_bytes(key_bytes) != signed.witness.signing_key_digest {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let key = VerifyingKey::from_bytes(key_bytes)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let signing_bytes = signed.signing_bytes();
        key.verify_strict(&signing_bytes, &Signature::from_bytes(&signed.signature))
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let manifest = &admission.validated_manifest.manifest;
        let mut bytes = b"hepta.learning-artifacts.request-identity.v1".to_vec();
        let operation = operation_id.as_str().as_bytes();
        bytes.extend_from_slice(&(operation.len() as u64).to_be_bytes());
        bytes.extend_from_slice(operation);
        bytes.extend_from_slice(admission.admission_digest.as_array());
        bytes.extend_from_slice(predecessor.as_array());
        bytes.extend_from_slice(manifest.bytes_digest.as_array());
        bytes.extend_from_slice(&manifest.encoded_size_bytes.to_be_bytes());
        bytes.extend_from_slice(&(signing_bytes.len() as u64).to_be_bytes());
        bytes.extend_from_slice(&signing_bytes);
        bytes.extend_from_slice(&signed.signature);
        Ok(Digest32::of_bytes(&bytes))
    }
}
