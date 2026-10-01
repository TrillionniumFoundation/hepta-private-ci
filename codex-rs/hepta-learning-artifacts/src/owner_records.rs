//! Atomic immutable records used by the fenced artifact owner.
//!
//! A partial write remains under a temporary name. Only a completely synced
//! record can become a checkpoint or signed CURRENT head, using a no-replace
//! hard link. The trusted root must exclude hostile path replacement.

use std::collections::BTreeSet;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use super::*;

static NEXT_RECORD: AtomicU64 = AtomicU64::new(1);
// Five canonical checkpoints per operation plus one pending-record allowance.
const MAX_OWNER_RECORDS: usize = MAX_HEAD_RECORDS * 6;

pub(super) fn validate_checkpoint(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    admission: WithdrawalBoundArtifactAdmissionV3,
    previous: Option<&ArtifactOwnerPublicationCheckpointV1>,
) -> Result<(), ArtifactOwnerHostError> {
    // Read the complete admission independently of the checkpoint. Replaying
    // only phase names and receipt fields would let a corrupt terminal state
    // become a trusted retry receipt without checking its commitment.
    if checkpoint.original_writer_lease_digest.is_zero()
        || checkpoint.registry_receipt.is_some_and(|receipt| {
            receipt.binding.is_zero()
                || receipt.head_digest.is_zero()
                || receipt.file_digest.is_zero()
                || receipt.records == 0
                || receipt.records > crate::limits::MAX_DURABLE_ARTIFACT_RECORDS
                || receipt.encoded_bytes == 0
        })
        || checkpoint.witness_receipt.is_some_and(|receipt| {
            receipt.binding.is_zero()
                || receipt.witness_digest.is_zero()
                || receipt.file_digest.is_zero()
                || receipt.encoded_bytes == 0
                || checkpoint
                    .registry_receipt
                    .is_none_or(|registry| receipt.binding != registry.binding)
        })
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    if let Some(previous) = previous
        && (previous.registry_receipt.is_some()
            && previous.registry_receipt != checkpoint.registry_receipt
            || previous.witness_receipt.is_some()
                && previous.witness_receipt != checkpoint.witness_receipt)
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    if let Some(acknowledged_at) = checkpoint.acknowledged_at {
        crate::verify_artifact_admission_v3(
            &admission,
            admission.withdrawal_head_digest,
            acknowledged_at,
        )
        .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
    }
    ArtifactPublicationTransactionV1::from_snapshot(ArtifactPublicationTransactionSnapshotV1 {
        intent: crate::ArtifactPublicationIntentV1 {
            operation_id: checkpoint.operation_id.clone(),
            admission,
            expected_registry_predecessor_head: checkpoint.expected_registry_predecessor_head,
            intent_digest: checkpoint.intent_digest,
        },
        phase: checkpoint.phase,
        registry_receipt: checkpoint.registry_receipt,
        witness_receipt: checkpoint.witness_receipt,
        acknowledged_at: checkpoint.acknowledged_at,
        state_digest: checkpoint.state_digest,
    })
    .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
    Ok(())
}

pub(super) fn all_checkpoints(
    owner: &LearningArtifactOwnerHost,
) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
    let mut checkpoints = Vec::new();
    for (index, entry) in fs::read_dir(owner.root.join("transactions"))?.enumerate() {
        if index >= MAX_OWNER_RECORDS {
            return Err(ArtifactOwnerHostError::Capacity);
        }
        let path = entry?.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        if path.extension().and_then(|value| value.to_str()) != Some("checkpoint") {
            continue;
        }
        let checkpoint = decode_checkpoint(&read_small_record(&path, MAX_SMALL_RECORD_BYTES)?)?;
        if path != owner.checkpoint_path(&checkpoint.operation_id, checkpoint.phase)
            || checkpoint.withdrawal_scope_digest != owner.verifier.trust.withdrawal_scope_digest
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        checkpoints.push(checkpoint);
    }
    // Registry recovery and CURRENT reads also consume this inventory. They
    // must not bypass complete per-operation checkpoint validation. Registry
    // associations are checked against the one requested/CURRENT snapshot;
    // reading every historical snapshot here would replay history quadratically.
    let mut operations = BTreeSet::new();
    for checkpoint in &checkpoints {
        operations.insert(&checkpoint.operation_id);
    }
    for operation in operations {
        owner
            .recover_checkpoint_chain(operation)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
    }
    Ok(checkpoints)
}

pub(super) fn recovery_required_operations(
    owner: &LearningArtifactOwnerHost,
) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
    let mut latest = BTreeMap::<StableId, ArtifactOwnerPublicationCheckpointV1>::new();
    for checkpoint in all_checkpoints(owner)? {
        let previous = latest.entry(checkpoint.operation_id.clone());
        match previous {
            std::collections::btree_map::Entry::Vacant(entry) => {
                entry.insert(checkpoint);
            }
            std::collections::btree_map::Entry::Occupied(mut entry) => {
                if phase_code(checkpoint.phase) > phase_code(entry.get().phase) {
                    entry.insert(checkpoint);
                }
            }
        }
    }
    Ok(latest
        .into_values()
        .filter(|checkpoint| checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged)
        .collect())
}

struct PendingRecord(PathBuf);

impl Drop for PendingRecord {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

pub(super) fn write_record(path: &Path, bytes: &[u8]) -> Result<(), ArtifactOwnerHostError> {
    write_record_with_limit(path, bytes, MAX_SMALL_RECORD_BYTES)
}

pub(super) fn write_record_with_limit(
    path: &Path,
    bytes: &[u8],
    limit: usize,
) -> Result<(), ArtifactOwnerHostError> {
    if bytes.len() > limit {
        return Err(ArtifactOwnerHostError::Capacity);
    }
    let parent = path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?;
    let (pending, mut file) = loop {
        let sequence = NEXT_RECORD.fetch_add(1, Ordering::Relaxed);
        let pending = parent.join(format!("owner-{}-{sequence}.pending", std::process::id()));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        match options.open(&pending) {
            Ok(file) => break (PendingRecord(pending), file),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    };
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    drop(file);
    match fs::hard_link(&pending.0, path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            if read_small_record(path, limit)? != bytes {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
        }
        Err(error) => return Err(error.into()),
    }
    sync_parent(path)?;
    Ok(())
}

pub(super) fn sync_parent(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    // Other targets retain the existing requirement for host qualification of
    // their directory durability primitive.
    #[cfg(unix)]
    {
        let parent = path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| ArtifactOwnerHostError::Indeterminate)?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

impl LearningArtifactOwnerHost {
    // Pure publication snapshots are publicly constructible and confer no
    // owner authority. Each mutation must start from this owner's exact durable
    // checkpoint, under a live lease for the admission's producer and scope.
    pub(super) fn require_current_transaction(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
        now: u64,
    ) -> Result<(), ArtifactOwnerHostError> {
        let writer = self.require_current_writer(now)?;
        let admission = &transaction.intent().admission;
        if admission.validated_manifest.manifest.producer_id != writer.producer_id
            || admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
        {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let recovery = self
            .recover_publication(&transaction.intent().operation_id)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        let expected = checkpoint_from_snapshot(
            &transaction.snapshot(),
            recovery.checkpoint.original_writer_lease_digest,
        );
        if expected != recovery.checkpoint {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        Ok(())
    }

    /// Verify an exact historical signed publication head for a terminal retry.
    pub(crate) fn verify_terminal_publication_head(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        let registry = checkpoint
            .registry_receipt
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
        let witness = checkpoint
            .witness_receipt
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: signed.witness.generation,
            expected_predecessor_head_digest: checkpoint.expected_registry_predecessor_head,
            minimum_authority_epoch: signed.witness.authority_epoch,
            now: signed.witness.issued_at,
        };
        let verified = self
            .verifier
            .verify_signed_head(signed, &requirement, false)?;
        if signed.binding != registry.binding
            || signed.witness.head_digest != registry.head_digest
            || verified.witness_digest != witness.witness_digest
            || signed.binding != witness.binding
            || read_small_record(
                &self.signed_head_record_path(signed),
                MAX_SMALL_RECORD_BYTES,
            )? != encode_signed_head(signed)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(())
    }
}
