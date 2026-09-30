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
    Ok(checkpoints)
}

pub(super) fn recovery_required_operations(
    owner: &LearningArtifactOwnerHost,
) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
    let operations = all_checkpoints(owner)?
        .into_iter()
        .map(|checkpoint| checkpoint.operation_id)
        .collect::<BTreeSet<_>>();
    let mut recovery = Vec::new();
    for operation in operations {
        let latest = owner
            .recover_publication(&operation)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        if latest.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged {
            recovery.push(latest.checkpoint);
        }
    }
    Ok(recovery)
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
            minimum_generation: self.verifier.trust.minimum_registry_generation,
            expected_predecessor_head_digest: checkpoint.expected_registry_predecessor_head,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
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
