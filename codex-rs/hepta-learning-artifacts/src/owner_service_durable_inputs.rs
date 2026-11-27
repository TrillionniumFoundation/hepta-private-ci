//! Validate actual immutable objects before advancing a recovered publication.

use std::fs::File;
use std::path::Path;

use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerPublicationCheckpointV1;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactRegistry;
use crate::RegistryHeadRequirementV1;
use crate::read_candidate_payload;
use crate::read_registry_head_witness;
use crate::read_registry_snapshot;

pub(super) fn verify_durable_inputs(
    root: &Path,
    staged: &ArtifactRegistry,
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<(), LearningArtifactOwnerServiceError> {
    if checkpoint.phase == ArtifactPublicationPhaseV1::Prepared {
        return Ok(());
    }
    let manifest = &request.admission.validated_manifest.manifest;
    let payload = root.join("payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.bytes_digest
    ));
    read_candidate_payload(
        File::open(payload).map_err(ArtifactOwnerHostError::from)?,
        staged,
        &manifest.artifact_id,
    )
    .map_err(ArtifactOwnerHostError::from)?;
    if checkpoint.phase == ArtifactPublicationPhaseV1::PayloadDurable {
        return Ok(());
    }
    let receipt = checkpoint
        .registry_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let path = root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let reopened = read_registry_snapshot(
        File::open(path).map_err(ArtifactOwnerHostError::from)?,
        receipt,
    )
    .map_err(ArtifactOwnerHostError::from)?;
    if reopened.snapshot() != staged.snapshot() {
        return Err(LearningArtifactOwnerServiceError::CheckpointMismatch);
    }
    if checkpoint.phase == ArtifactPublicationPhaseV1::RegistryDurable {
        return Ok(());
    }
    let receipt = checkpoint
        .witness_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let witness = &request.signed_current_head.witness;
    let path = root.join("witnesses").join(format!(
        "{}-{}.witness",
        witness.generation.get(),
        receipt.witness_digest
    ));
    let requirement = RegistryHeadRequirementV1 {
        registry_id: witness.registry_id.clone(),
        minimum_generation: witness.generation,
        expected_predecessor_head_digest: request.expected_registry_predecessor_head,
        minimum_authority_epoch: witness.authority_epoch,
        now: request.now,
    };
    let reopened = read_registry_head_witness(
        File::open(path).map_err(ArtifactOwnerHostError::from)?,
        receipt,
        &requirement,
    )
    .map_err(ArtifactOwnerHostError::from)?;
    if reopened != *witness {
        return Err(LearningArtifactOwnerServiceError::CheckpointMismatch);
    }
    Ok(())
}
