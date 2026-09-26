//! Private replay and request-binding functions. No additional writer authority.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerPublicationCheckpointV1;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryHeadRequirementV1;
use crate::admission_v3::verify_artifact_admission_v3;
use crate::validate_registry_head_witness;

pub(super) fn validate_request_identity(
    request: &LearningArtifactPublishRequestV1,
) -> Result<(), LearningArtifactOwnerServiceError> {
    let admission = &request.admission;
    verify_artifact_admission_v3(
        admission,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    )
    .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
    let manifest = &admission.validated_manifest.manifest;
    if request.now < admission.admitted_at
        || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
        || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    Ok(())
}

/// This returns only a private digest. Historical validation is allowed only
/// after finding an acknowledged checkpoint, which must bind that exact digest.
/// Live publication still passes the owner's current trust/lease/frontier checks.
pub(super) fn verify_request_head(
    trust: &ArtifactOwnerTrustV1,
    request: &LearningArtifactPublishRequestV1,
    historical: bool,
) -> Result<Digest32, LearningArtifactOwnerServiceError> {
    let signed = &request.signed_current_head;
    let witness = &signed.witness;
    let now = if historical { witness.issued_at } else { request.now };
    let mismatch = || LearningArtifactOwnerServiceError::RequestMismatch;
    if witness.registry_id != trust.registry_id
        || signed.withdrawal_scope_digest != trust.withdrawal_scope_digest
    {
        return Err(mismatch());
    }
    let signer = trust
        .head_signers
        .iter()
        .find(|signer| signer.signer_id == witness.signer_id)
        .ok_or_else(mismatch)?;
    if witness.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
        || witness.authority_epoch < signer.minimum_authority_epoch
        || witness.authority_epoch > signer.maximum_authority_epoch
        || witness.issued_at < signer.valid_from
        || now < signer.valid_from
        || now > signer.expires_at
        || signer.revoked_at.is_some_and(|revoked| revoked <= now)
    {
        return Err(mismatch());
    }
    let key = VerifyingKey::from_bytes(&signer.verifying_key).map_err(|_| mismatch())?;
    key.verify_strict(&signed.signing_bytes(), &Signature::from_bytes(&signed.signature))
        .map_err(|_| mismatch())?;
    let requirement = RegistryHeadRequirementV1 {
        registry_id: trust.registry_id.clone(),
        minimum_generation: witness.generation,
        expected_predecessor_head_digest: request.expected_registry_predecessor_head,
        minimum_authority_epoch: if historical {
            witness.authority_epoch
        } else {
            trust.minimum_authority_epoch
        },
        now,
    };
    Ok(validate_registry_head_witness(witness, &requirement)
        .map_err(|_| mismatch())?
        .witness_digest)
}

pub(super) fn validate_request_against_checkpoint(
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    witness_digest: Digest32,
) -> Result<(), LearningArtifactOwnerServiceError> {
    if checkpoint.operation_id != request.operation_id
        || checkpoint.admission_digest != request.admission.admission_digest
        || checkpoint.withdrawal_scope_digest != request.admission.withdrawal_scope_digest
        || checkpoint.withdrawal_head_digest != request.admission.withdrawal_head_digest
        || checkpoint.expected_registry_predecessor_head
            != request.expected_registry_predecessor_head
        || checkpoint.witness_receipt.is_some_and(|receipt| {
            receipt.witness_digest != witness_digest
        })
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
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
    if phase_rank(checkpoint.phase) >= phase_rank(ArtifactPublicationPhaseV1::PayloadDurable) {
        let manifest = &request.admission.validated_manifest.manifest;
        transaction.record_payload_durable(manifest.bytes_digest, manifest.encoded_size_bytes)?;
    }
    if phase_rank(checkpoint.phase) >= phase_rank(ArtifactPublicationPhaseV1::RegistryDurable) {
        transaction.record_registry_durable(
            staged,
            checkpoint.registry_receipt.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if phase_rank(checkpoint.phase) >= phase_rank(ArtifactPublicationPhaseV1::WitnessDurable) {
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
            checkpoint.witness_receipt.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
        transaction.acknowledge(
            withdrawals,
            checkpoint.acknowledged_at.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
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
    let registry = checkpoint.registry_receipt.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let witness = checkpoint.witness_receipt.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    Ok(ArtifactPublicationReceiptV1 {
        operation_id: checkpoint.operation_id.clone(),
        admission_digest: checkpoint.admission_digest,
        registry_head_digest: registry.head_digest,
        witness_digest: witness.witness_digest,
        state_digest: checkpoint.state_digest,
        acknowledged_at: checkpoint.acknowledged_at.ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        authority: AuthorityPosture::DENY_ALL,
    })
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
