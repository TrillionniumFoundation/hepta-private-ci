//! Read-only reconciliation of one exact admitted publication target.

use super::*;
use crate::ArtifactPublicationStatusV1;
use crate::verify_artifact_admission_v3;

/// Durable storage facts, never selection or current runtime authorization.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactPublicationStatusV1 {
    /// Commits operation, admitted manifest/payload and registry predecessor.
    /// Time and renewed CURRENT signatures are not publication target identity.
    pub request_identity_digest: Digest32,
    pub status: ArtifactPublicationStatusV1,
}

impl LearningArtifactOwnerService {
    /// Read existing checkpoints without creating, repairing or advancing them.
    /// This may identify a completed write after qualification has expired.
    pub fn publication_status(
        &self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<Option<LearningArtifactPublicationStatusV1>, LearningArtifactOwnerServiceError>
    {
        verify_artifact_admission_v3(
            &request.admission,
            request.admission.withdrawal_head_digest,
            request.admission.admitted_at,
        )
        .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let manifest = &request.admission.validated_manifest.manifest;
        if u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let Some(recovery) = self.host.recover_publication(&request.operation_id)? else {
            return Ok(None);
        };
        validate_request_against_checkpoint(request, &recovery.checkpoint)?;
        let checkpoint = recovery.checkpoint;
        let mut identity = b"hepta.learning-artifacts.publication-target.v1\0".to_vec();
        identity.extend_from_slice(request.operation_id.as_str().as_bytes());
        identity.extend_from_slice(request.admission.admission_digest.as_array());
        identity.extend_from_slice(manifest.bytes_digest.as_array());
        identity.extend_from_slice(&manifest.encoded_size_bytes.to_be_bytes());
        identity.extend_from_slice(request.expected_registry_predecessor_head.as_array());
        Ok(Some(LearningArtifactPublicationStatusV1 {
            request_identity_digest: Digest32::of_bytes(&identity),
            status: ArtifactPublicationStatusV1 {
                operation_id: checkpoint.operation_id,
                phase: checkpoint.phase,
                admission_digest: checkpoint.admission_digest,
                withdrawal_scope_digest: checkpoint.withdrawal_scope_digest,
                withdrawal_head_digest: checkpoint.withdrawal_head_digest,
                registry_head_digest: checkpoint.registry_receipt.map(|value| value.head_digest),
                witness_digest: checkpoint.witness_receipt.map(|value| value.witness_digest),
                acknowledged_at: checkpoint.acknowledged_at,
                state_digest: checkpoint.state_digest,
                authority: AuthorityPosture::DENY_ALL,
            },
        }))
    }
}
