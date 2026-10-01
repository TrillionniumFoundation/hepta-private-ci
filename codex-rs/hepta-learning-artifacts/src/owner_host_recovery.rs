//! Bounded checkpoint discovery and immutable recovery identities.

use std::collections::BTreeSet;

use super::*;

const MAX_CHECKPOINT_RECORDS: usize = MAX_HEAD_RECORDS * 5;

pub(super) fn synchronize_artifact_path(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .and_then(|file| file.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    #[cfg(unix)]
    File::open(path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    Ok(())
}

pub(super) fn verified_checkpoints(
    host: &LearningArtifactOwnerHost,
) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
    let mut operations = BTreeSet::new();
    for (index, entry) in fs::read_dir(host.root.join("transactions"))?.enumerate() {
        if index >= MAX_CHECKPOINT_RECORDS {
            return Err(ArtifactOwnerHostError::Capacity);
        }
        let entry = entry?;
        let metadata = fs::symlink_metadata(entry.path())?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        if entry.path().extension().and_then(|value| value.to_str()) != Some("checkpoint") {
            continue;
        }
        let checkpoint =
            decode_checkpoint(&read_small_record(&entry.path(), MAX_SMALL_RECORD_BYTES)?)?;
        if entry.path() != host.checkpoint_path(&checkpoint.operation_id, checkpoint.phase) {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        operations.insert(checkpoint.operation_id);
        if operations.len() > MAX_HEAD_RECORDS {
            return Err(ArtifactOwnerHostError::Capacity);
        }
    }
    operations
        .iter()
        .map(|operation_id| {
            host.recover_publication(operation_id)?
                .map(|recovery| recovery.checkpoint)
                .ok_or(ArtifactOwnerHostError::CheckpointMissing)
        })
        .collect()
}

pub(super) fn checkpoint_for_write(
    host: &LearningArtifactOwnerHost,
    transaction: &ArtifactPublicationTransactionV1,
) -> Result<ArtifactOwnerPublicationCheckpointV1, ArtifactOwnerHostError> {
    let snapshot = transaction.snapshot();
    let path = host.checkpoint_path(
        &snapshot.intent.operation_id,
        ArtifactPublicationPhaseV1::Prepared,
    );
    let original_lease = match fs::symlink_metadata(&path) {
        Ok(_) => {
            let prepared = decode_checkpoint(&read_small_record(&path, MAX_SMALL_RECORD_BYTES)?)?;
            if prepared.operation_id != snapshot.intent.operation_id
                || prepared.phase != ArtifactPublicationPhaseV1::Prepared
                || prepared.intent_digest != snapshot.intent.intent_digest
                || prepared.admission_digest != snapshot.intent.admission.admission_digest
                || prepared.withdrawal_scope_digest
                    != snapshot.intent.admission.withdrawal_scope_digest
                || prepared.withdrawal_head_digest
                    != snapshot.intent.admission.withdrawal_head_digest
                || prepared.expected_registry_predecessor_head
                    != snapshot.intent.expected_registry_predecessor_head
            {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            prepared.original_writer_lease_digest
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if snapshot.phase != ArtifactPublicationPhaseV1::Prepared {
                return Err(ArtifactOwnerHostError::CheckpointMissing);
            }
            if verified_checkpoints(host)?.len() >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            host.verified_lease.lease_digest
        }
        Err(error) => return Err(error.into()),
    };
    Ok(checkpoint_from_snapshot(&snapshot, original_lease))
}

pub(super) fn validate_checkpoint_shape(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<(), ArtifactOwnerHostError> {
    let registry_expected =
        phase_code(checkpoint.phase) >= phase_code(ArtifactPublicationPhaseV1::RegistryDurable);
    let witness_expected =
        phase_code(checkpoint.phase) >= phase_code(ArtifactPublicationPhaseV1::WitnessDurable);
    let acknowledgement_expected = checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged;
    if checkpoint.intent_digest.is_zero()
        || checkpoint.admission_digest.is_zero()
        || checkpoint.withdrawal_scope_digest.is_zero()
        || checkpoint.withdrawal_head_digest.is_zero()
        || checkpoint.state_digest.is_zero()
        || checkpoint.original_writer_lease_digest.is_zero()
        || checkpoint.registry_receipt.is_some() != registry_expected
        || checkpoint.witness_receipt.is_some() != witness_expected
        || checkpoint.acknowledged_at.is_some() != acknowledgement_expected
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    if let Some(receipt) = checkpoint.registry_receipt
        && (receipt.binding.is_zero()
            || receipt.head_digest.is_zero()
            || receipt.file_digest.is_zero()
            || receipt.records == 0
            || receipt.records > MAX_HEAD_RECORDS
            || receipt.encoded_bytes == 0
            || receipt.encoded_bytes > 8 * 1024 * 1024)
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    if let Some(witness) = checkpoint.witness_receipt
        && (witness.binding.is_zero()
            || witness.witness_digest.is_zero()
            || witness.file_digest.is_zero()
            || witness.encoded_bytes == 0
            || witness.encoded_bytes > MAX_SMALL_RECORD_BYTES
            || checkpoint.registry_receipt.map(|receipt| receipt.binding) != Some(witness.binding))
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(())
}
