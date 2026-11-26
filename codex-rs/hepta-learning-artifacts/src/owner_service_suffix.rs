//! Replay checks for the same journal's complete immutable registry suffix.
use super::*;
use crate::ArtifactPublicationIntentV1;

pub(super) fn replay_acknowledged_suffix(
    host: &LearningArtifactOwnerHost,
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    state_changes: &[ArtifactEvent],
) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
    crate::verify_artifact_admission_v3(
        &request.admission,
        request.admission.withdrawal_head_digest,
        request.admission.admitted_at,
    )
    .map_err(ArtifactPublicationError::from)?;
    let receipt = checkpoint
        .registry_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let registry = host.recover_registry_by_head(receipt.head_digest)?;
    let intent = ArtifactPublicationIntentV1 {
        operation_id: request.operation_id.clone(),
        admission: request.admission.clone(),
        expected_registry_predecessor_head: request.expected_registry_predecessor_head,
        intent_digest: checkpoint.intent_digest,
    };
    let start = crate::publication_registry_suffix::validate_registry_suffix(&intent, &registry)?;
    if registry.records()[start + 1..]
        .iter()
        .map(|record| &record.event)
        .ne(state_changes.iter())
        || request.signed_current_head.witness.head_digest != receipt.head_digest
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    receipt_from_checkpoint(checkpoint)
}
