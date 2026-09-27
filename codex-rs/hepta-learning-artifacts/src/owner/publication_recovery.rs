//! Exact reconstruction of a durable publication; never issues live authority.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerPublicationCheckpointV1;
use crate::ArtifactPublicationIntentV1;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionSnapshotV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::storage::encode_head_witness;
use crate::validate_registry_head_witness;

pub(super) fn validate_request_against_checkpoint(
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<(), LearningArtifactOwnerServiceError> {
    if checkpoint.operation_id != request.operation_id
        || checkpoint.admission_digest != request.admission.admission_digest
        || checkpoint.withdrawal_scope_digest != request.admission.withdrawal_scope_digest
        || checkpoint.withdrawal_head_digest != request.admission.withdrawal_head_digest
        || checkpoint.expected_registry_predecessor_head
            != request.expected_registry_predecessor_head
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    ArtifactPublicationTransactionV1::from_snapshot(ArtifactPublicationTransactionSnapshotV1 {
        intent: ArtifactPublicationIntentV1 {
            operation_id: request.operation_id.clone(),
            admission: request.admission.clone(),
            expected_registry_predecessor_head: request.expected_registry_predecessor_head,
            intent_digest: checkpoint.intent_digest,
        },
        phase: checkpoint.phase,
        registry_receipt: checkpoint.registry_receipt,
        witness_receipt: checkpoint.witness_receipt,
        acknowledged_at: checkpoint.acknowledged_at,
        state_digest: checkpoint.state_digest,
    })?;
    if let Some(registry) = checkpoint.registry_receipt
        && (registry.binding != request.signed_current_head.binding
            || registry.head_digest != request.signed_current_head.witness.head_digest)
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    if let Some(receipt) = checkpoint.witness_receipt {
        let signed = &request.signed_current_head;
        let witness = &signed.witness;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: witness.registry_id.clone(),
            minimum_generation: witness.generation,
            expected_predecessor_head_digest: request.expected_registry_predecessor_head,
            minimum_authority_epoch: witness.authority_epoch,
            // A terminal receipt describes historical publication, not renewed
            // permission. Live publication checks still run in the owner host.
            now: checkpoint.acknowledged_at.unwrap_or(request.now),
        };
        let validated = validate_registry_head_witness(witness, &requirement)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let encoded = encode_head_witness(witness, signed.binding)
            .map_err(ArtifactOwnerHostError::from)?;
        let expected = RegistryHeadWitnessReceipt {
            binding: signed.binding,
            witness_digest: validated.witness_digest,
            file_digest: Digest32::of_bytes(&encoded),
            encoded_bytes: encoded.len(),
        };
        if expected != receipt {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
    }
    Ok(())
}

pub(super) fn rebuild_transaction(
    mut transaction: ArtifactPublicationTransactionV1,
    staged: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<ArtifactPublicationTransactionV1, LearningArtifactOwnerServiceError> {
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::PayloadDurable) {
        let manifest = &request.admission.validated_manifest.manifest;
        transaction.record_payload_durable(manifest.bytes_digest, manifest.encoded_size_bytes)?;
    }
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::RegistryDurable) {
        transaction.record_registry_durable(
            staged,
            checkpoint
                .registry_receipt
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::WitnessDurable) {
        let witness = &request.signed_current_head.witness;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: witness.registry_id.clone(),
            minimum_generation: witness.generation,
            expected_predecessor_head_digest: request.expected_registry_predecessor_head,
            minimum_authority_epoch: witness.authority_epoch,
            now: request.now,
        };
        transaction.record_witness_durable(
            witness,
            &requirement,
            checkpoint
                .witness_receipt
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
        transaction.acknowledge(
            withdrawals,
            checkpoint
                .acknowledged_at
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        )?;
    }
    if transaction.state_digest() != checkpoint.state_digest {
        return Err(LearningArtifactOwnerServiceError::CheckpointMismatch);
    }
    Ok(transaction)
}

pub(super) fn receipt_from_checkpoint(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
    let registry = checkpoint
        .registry_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let witness = checkpoint
        .witness_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    Ok(ArtifactPublicationReceiptV1 {
        operation_id: checkpoint.operation_id.clone(),
        admission_digest: checkpoint.admission_digest,
        registry_head_digest: registry.head_digest,
        witness_digest: witness.witness_digest,
        state_digest: checkpoint.state_digest,
        acknowledged_at: checkpoint
            .acknowledged_at
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        authority: AuthorityPosture::DENY_ALL,
    })
}

const fn phase_at_least(
    actual: ArtifactPublicationPhaseV1,
    expected: ArtifactPublicationPhaseV1,
) -> bool {
    phase_rank(actual) >= phase_rank(expected)
}

const fn phase_rank(phase: ArtifactPublicationPhaseV1) -> u8 {
    match phase {
        ArtifactPublicationPhaseV1::Prepared => 0,
        ArtifactPublicationPhaseV1::PayloadDurable => 1,
        ArtifactPublicationPhaseV1::RegistryDurable => 2,
        ArtifactPublicationPhaseV1::WitnessDurable => 3,
        ArtifactPublicationPhaseV1::Acknowledged => 4,
    }
}
