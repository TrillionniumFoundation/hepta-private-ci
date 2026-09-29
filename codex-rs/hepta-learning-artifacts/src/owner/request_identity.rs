//! Request integrity preflight for both new publication and terminal replay.
//!
//! This verifier binds bytes, public admission fields and the signature to the
//! owner's configured head-signing keys. It does not grant current authority:
//! lease expiry, current signer policy and withdrawal freshness remain checked
//! by LearningArtifactOwnerHost on every non-terminal publication phase.

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

    pub(super) fn verify(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let admission = &request.admission;
        // Historical reconstruction is intentionally separate from the live
        // withdrawal check. Returning an old DENY_ALL receipt renews nothing.
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let manifest = &admission.validated_manifest.manifest;
        let signed = &request.signed_current_head;
        if request.now < admission.admitted_at
            || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || request.payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
            || signed.witness.registry_id != self.registry_id
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
        key.verify_strict(
            &signed.signing_bytes(),
            &Signature::from_bytes(&signed.signature),
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)
    }
}
