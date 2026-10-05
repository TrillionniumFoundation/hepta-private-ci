//! Canonical bounded records for the owner state-publication saga.

use std::collections::BTreeSet;

use super::*;

const MAGIC: &str = "HEPTA-ARTIFACT-STATE-CHECKPOINT-V1";
const PHASES: [StatePhase; 4] = [
    StatePhase::Prepared,
    StatePhase::SnapshotsDurable,
    StatePhase::WitnessDurable,
    StatePhase::Acknowledged,
];

pub(super) fn path(
    host: &LearningArtifactOwnerHost,
    operation: &StableId,
    phase: StatePhase,
) -> PathBuf {
    host.root.join("state-transactions").join(format!(
        "{}-{}.checkpoint",
        Digest32::of_bytes(operation.as_str().as_bytes()),
        phase.code()
    ))
}

pub(super) fn withdrawal_path(receipt: DatasetWithdrawalSnapshotReceiptV1) -> PathBuf {
    PathBuf::from("withdrawals").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ))
}

pub(super) fn persist_withdrawal(
    host: &LearningArtifactOwnerHost,
    receipt: DatasetWithdrawalSnapshotReceiptV1,
    withdrawal: &DatasetWithdrawalRegistry,
) -> Result<(), ArtifactOwnerHostError> {
    let relative = withdrawal_path(receipt);
    match write_dataset_withdrawal_snapshot_beneath(
        &host.root,
        &relative,
        withdrawal,
        receipt.binding,
    ) {
        Ok(actual) if actual == receipt => {}
        Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
        Err(crate::ArtifactStorageError::AlreadyExists) => {
            read_dataset_withdrawal_snapshot(File::open(host.root.join(&relative))?, receipt)?;
        }
        Err(error) => return Err(error.into()),
    }
    recovery::synchronize_artifact_path(&host.root.join(relative))
}

pub(super) fn encode(checkpoint: &StateCheckpoint) -> Vec<u8> {
    let registry = checkpoint.registry_receipt;
    let withdrawal = checkpoint.withdrawal_receipt;
    let witness = checkpoint.witness_receipt;
    let predecessor = checkpoint.predecessor_withdrawal_receipt;
    let signed = encode_signed_head(&checkpoint.signed_head);
    format!(
        "{MAGIC}\n{}\n{}\n{}\n{}\n{}\n{},{},{},{},{}\n{},{},{},{},{},{}\n{},{},{},{},{},{}\n{},{},{},{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}",
        checkpoint.operation_id, checkpoint.phase.code(), checkpoint.request_digest,
        checkpoint.expected_registry_predecessor_head, checkpoint.expected_withdrawal_predecessor_head,
        registry.binding, registry.head_digest, registry.file_digest, registry.records, registry.encoded_bytes,
        withdrawal.binding, withdrawal.scope_digest, withdrawal.head_digest, withdrawal.file_digest, withdrawal.records, withdrawal.encoded_bytes,
        predecessor.binding, predecessor.scope_digest, predecessor.head_digest, predecessor.file_digest, predecessor.records, predecessor.encoded_bytes,
        witness.binding, witness.witness_digest, witness.file_digest, witness.encoded_bytes,
        checkpoint.signed_head_digest, checkpoint.original_writer_lease_digest,
        checkpoint.acknowledged_at.map_or_else(|| "-".to_owned(), |at| at.to_string()),
        checkpoint.authorized_at, checkpoint.authorization_expires_at, encode_hex(&checkpoint.state_authorization_signature),
        String::from_utf8_lossy(&signed),
    ).into_bytes()
}

fn decode(bytes: &[u8]) -> Result<StateCheckpoint, ArtifactOwnerHostError> {
    let text =
        std::str::from_utf8(bytes).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
    let fields = text.lines().collect::<Vec<_>>();
    if fields.len() != 29 || fields[0] != MAGIC {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    let phase = match fields[2] {
        "0" => StatePhase::Prepared,
        "1" => StatePhase::SnapshotsDurable,
        "2" => StatePhase::WitnessDurable,
        "3" => StatePhase::Acknowledged,
        _ => return Err(ArtifactOwnerHostError::CheckpointMismatch),
    };
    let withdrawal = fields[7].split(',').collect::<Vec<_>>();
    if withdrawal.len() != 6 {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    let predecessor = fields[8].split(',').collect::<Vec<_>>();
    if predecessor.len() != 6 {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    let signed = fields[16..].join("\n") + "\n";
    let checkpoint = StateCheckpoint {
        operation_id: StableId::new(fields[1])
            .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
        phase,
        request_digest: parse_digest(fields[3])?,
        expected_registry_predecessor_head: parse_digest(fields[4])?,
        expected_withdrawal_predecessor_head: parse_digest(fields[5])?,
        registry_receipt: parse_registry_receipt(fields[6])?
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?,
        withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1 {
            binding: parse_digest(withdrawal[0])?,
            scope_digest: parse_digest(withdrawal[1])?,
            head_digest: parse_digest(withdrawal[2])?,
            file_digest: parse_digest(withdrawal[3])?,
            records: parse_usize(withdrawal[4])?,
            encoded_bytes: parse_usize(withdrawal[5])?,
        },
        predecessor_withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1 {
            binding: parse_digest(predecessor[0])?,
            scope_digest: parse_digest(predecessor[1])?,
            head_digest: parse_digest(predecessor[2])?,
            file_digest: parse_digest(predecessor[3])?,
            records: parse_usize(predecessor[4])?,
            encoded_bytes: parse_usize(predecessor[5])?,
        },
        witness_receipt: parse_witness_receipt(fields[9])?
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?,
        signed_head_digest: parse_digest(fields[10])?,
        original_writer_lease_digest: parse_digest(fields[11])?,
        acknowledged_at: parse_optional_u64(fields[12])?,
        authorized_at: parse_u64(fields[13])?,
        authorization_expires_at: parse_u64(fields[14])?,
        state_authorization_signature: decode_signature(fields[15])?,
        signed_head: decode_signed_head(signed.as_bytes())?,
    };
    let mut signed_bytes = checkpoint.signed_head.signing_bytes();
    signed_bytes.extend_from_slice(&checkpoint.signed_head.signature);
    if encode(&checkpoint) != bytes
        || checkpoint.request_digest.is_zero()
        || checkpoint.original_writer_lease_digest.is_zero()
        || checkpoint.signed_head_digest != Digest32::of_bytes(&signed_bytes)
        || checkpoint.registry_receipt.records == 0
        || checkpoint.registry_receipt.records > MAX_HEAD_RECORDS
        || checkpoint.registry_receipt.encoded_bytes == 0
        || checkpoint.registry_receipt.encoded_bytes > 8 * 1024 * 1024
        || checkpoint.withdrawal_receipt.records > MAX_HEAD_RECORDS
        || checkpoint.withdrawal_receipt.encoded_bytes == 0
        || checkpoint.withdrawal_receipt.encoded_bytes > 8 * 1024 * 1024
        || checkpoint.witness_receipt.encoded_bytes == 0
        || checkpoint.witness_receipt.encoded_bytes > MAX_SMALL_RECORD_BYTES
        || checkpoint.is_acknowledged() != checkpoint.acknowledged_at.is_some()
        || checkpoint.acknowledged_at.is_some_and(|at| {
            at < checkpoint.authorized_at
                || at < checkpoint.signed_head.witness.issued_at
                || at > checkpoint.authorization_expires_at
        })
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(checkpoint)
}

pub(super) fn recover(
    host: &LearningArtifactOwnerHost,
    operation: &StableId,
) -> Result<Option<StateCheckpoint>, ArtifactOwnerHostError> {
    let mut latest: Option<StateCheckpoint> = None;
    let mut missing = false;
    for phase in PHASES {
        let path = path(host, operation, phase);
        if !path.exists() {
            missing = true;
            continue;
        }
        if missing {
            return Err(ArtifactOwnerHostError::CheckpointGap);
        }
        let checkpoint = decode(&read_small_record(&path, MAX_SMALL_RECORD_BYTES)?)?;
        if checkpoint.operation_id != *operation || checkpoint.phase != phase {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        host.authenticate_state_checkpoint(&checkpoint, checkpoint.authorized_at, false)?;
        host.verify_state_effects(&checkpoint)?;
        if let Some(previous) = &latest {
            let mut normalized = checkpoint.clone();
            normalized.phase = previous.phase;
            normalized.acknowledged_at = previous.acknowledged_at;
            if normalized != *previous {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
        }
        latest = Some(checkpoint);
    }
    Ok(latest)
}

pub(super) fn all(
    host: &LearningArtifactOwnerHost,
) -> Result<Vec<StateCheckpoint>, ArtifactOwnerHostError> {
    let mut operations = BTreeSet::new();
    for (index, entry) in fs::read_dir(host.root.join("state-transactions"))?.enumerate() {
        if index >= MAX_HEAD_RECORDS * 4 {
            return Err(ArtifactOwnerHostError::Capacity);
        }
        let entry = entry?;
        let metadata = fs::symlink_metadata(entry.path())?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        if entry.path().extension().and_then(|value| value.to_str()) != Some("checkpoint") {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let checkpoint = decode(&read_small_record(&entry.path(), MAX_SMALL_RECORD_BYTES)?)?;
        if path(host, &checkpoint.operation_id, checkpoint.phase) != entry.path() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        operations.insert(checkpoint.operation_id);
        if operations.len() > MAX_HEAD_RECORDS {
            return Err(ArtifactOwnerHostError::Capacity);
        }
    }
    operations
        .iter()
        .map(|operation| recover(host, operation)?.ok_or(ArtifactOwnerHostError::CheckpointMissing))
        .collect()
}

pub(super) fn persist(
    host: &LearningArtifactOwnerHost,
    checkpoint: &StateCheckpoint,
) -> Result<(), ArtifactOwnerHostError> {
    let path = path(host, &checkpoint.operation_id, checkpoint.phase);
    if checkpoint.phase == StatePhase::Prepared
        && !path.exists()
        && all(host)?.len() >= MAX_HEAD_RECORDS
    {
        return Err(ArtifactOwnerHostError::Capacity);
    }
    write_create_only_or_exact(&path, &encode(checkpoint))
}
