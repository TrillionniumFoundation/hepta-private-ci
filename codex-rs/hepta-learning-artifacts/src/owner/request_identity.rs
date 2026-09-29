//! Canonical request integrity for new publication, recovery and terminal replay.
//!
//! The resulting digest deliberately excludes the caller's observation time so
//! an exact historical retry may be read later. It includes every semantic input
//! that may change the durable publication: operation, complete admission,
//! payload identity, predecessor and the exact signed CURRENT witness.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerTrustV1;
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

    pub(super) fn verify_and_digest(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<Digest32, LearningArtifactOwnerServiceError> {
        let admission = &request.admission;
        // Historical reconstruction is intentionally separate from the live
        // withdrawal check. Returning an old DENY_ALL receipt renews nothing.
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestIdentityConflict)?;
        let manifest = &admission.validated_manifest.manifest;
        let signed = &request.signed_current_head;
        if request.now < admission.admitted_at
            || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || request.payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
            || signed.witness.registry_id != self.registry_id
        {
            return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict);
        }
        let key_bytes = self
            .head_keys
            .get(&signed.witness.signer_id)
            .ok_or(LearningArtifactOwnerServiceError::RequestIdentityConflict)?;
        if Digest32::of_bytes(key_bytes) != signed.witness.signing_key_digest {
            return Err(LearningArtifactOwnerServiceError::RequestIdentityConflict);
        }
        let key = VerifyingKey::from_bytes(key_bytes)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestIdentityConflict)?;
        key.verify_strict(
            &signed.signing_bytes(),
            &Signature::from_bytes(&signed.signature),
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestIdentityConflict)?;

        let mut signed_head_bytes = b"hepta.learning-artifacts.signed-current-head.identity.v1".to_vec();
        signed_head_bytes.extend_from_slice(&signed.signing_bytes());
        signed_head_bytes.extend_from_slice(&signed.signature);
        let signed_head_digest = Digest32::of_bytes(&signed_head_bytes);

        let mut identity = b"hepta.learning-artifacts.publication-request.identity.v1".to_vec();
        push_id(&mut identity, &request.operation_id);
        identity.extend_from_slice(admission.admission_digest.as_array());
        identity.extend_from_slice(admission.validated_manifest.manifest_digest.as_array());
        identity.extend_from_slice(admission.withdrawal_scope_digest.as_array());
        identity.extend_from_slice(admission.withdrawal_head_digest.as_array());
        identity.extend_from_slice(&(request.payload.len() as u64).to_be_bytes());
        identity.extend_from_slice(manifest.bytes_digest.as_array());
        identity.extend_from_slice(request.expected_registry_predecessor_head.as_array());
        identity.extend_from_slice(signed_head_digest.as_array());
        Ok(Digest32::of_bytes(&identity))
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
