//! Snapshot decoding and checksum-linked WAL replay under the journal owner.

use std::collections::HashMap;
use std::io::Read as _;
use std::path::Path;

use serde::Deserialize;
use serde::Serialize;

use super::JournalFile;
use super::MAX_JOURNAL_BYTES;
use super::MAX_OPERATION_RECORDS;
use super::MAX_WAL_BYTES;
use super::MAX_WAL_FRAME_BYTES;
use super::OperationPhase;
use super::OperationRecord;
use super::WAL_SCHEMA;
use crate::error::ShellError;
use crate::model::OperationKey;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use crate::private_state::PrivateStateRoot;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct JournalWalEntry {
    schema: String,
    sequence: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    previous_checksum: Option<String>,
    record: OperationRecord,
    pub(super) checksum: String,
}

impl JournalWalEntry {
    pub(super) fn new(
        sequence: u64,
        previous_checksum: Option<String>,
        record: OperationRecord,
    ) -> Result<Self, ShellError> {
        let mut entry = Self {
            schema: WAL_SCHEMA.to_owned(),
            sequence,
            previous_checksum,
            record,
            checksum: String::new(),
        };
        entry.checksum = entry.computed_checksum()?;
        entry.validate()?;
        Ok(entry)
    }

    fn computed_checksum(&self) -> Result<String, ShellError> {
        Ok(sha256_hex(serde_json::to_vec(&(
            &self.schema,
            self.sequence,
            &self.previous_checksum,
            &self.record,
        ))?))
    }

    fn validate(&self) -> Result<(), ShellError> {
        if self.schema != WAL_SCHEMA || self.sequence == 0 {
            return Err(ShellError::State(
                "unsupported or zero-sequence native journal WAL entry".to_owned(),
            ));
        }
        if let Some(previous) = &self.previous_checksum {
            validate_digest(previous, "journal.wal_previous")?;
        }
        validate_digest(&self.checksum, "journal.wal_checksum")?;
        self.record.validate()?;
        if self.checksum != self.computed_checksum()? {
            return Err(ShellError::State(
                "native journal WAL entry checksum mismatch".to_owned(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug)]
pub(super) struct WalReplay {
    pub(super) sequence: u64,
    pub(super) frontier: Option<String>,
    pub(super) applied_entries: usize,
    pub(super) valid_bytes: u64,
    pub(super) total_bytes: u64,
    pub(super) partial_tail: bool,
}

pub(super) fn read_snapshot(
    root: &PrivateStateRoot,
    path: &Path,
) -> Result<JournalFile, ShellError> {
    let file = crate::journal_storage::open_private_file_in(
        root,
        path,
        crate::journal_storage::FileAccess::Read,
        /*preexisting*/ true,
    )?;
    let metadata = file.metadata()?;
    if metadata.len() > MAX_JOURNAL_BYTES {
        return Err(ShellError::State(format!(
            "operation journal exceeds {MAX_JOURNAL_BYTES} bytes"
        )));
    }
    let mut bytes = Vec::new();
    file.take(MAX_JOURNAL_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_JOURNAL_BYTES {
        return Err(ShellError::State(
            "operation journal read exceeded byte limit".to_owned(),
        ));
    }
    serde_json::from_slice(&bytes).map_err(ShellError::from)
}

pub(super) fn replay_wal(
    root: &PrivateStateRoot,
    path: &Path,
    operations: &mut Vec<OperationRecord>,
    snapshot_sequence: u64,
    snapshot_frontier: Option<String>,
) -> Result<WalReplay, ShellError> {
    let frames =
        crate::journal_storage::read_wal_frames(root, path, MAX_WAL_BYTES, MAX_WAL_FRAME_BYTES)?;
    let mut index = build_operation_index(operations)?;
    let mut sequence = snapshot_sequence;
    let mut frontier = snapshot_frontier.clone();
    let mut applied_entries = 0usize;
    if frames.frames.is_empty() {
        return Ok(WalReplay {
            sequence,
            frontier,
            applied_entries,
            valid_bytes: frames.valid_bytes,
            total_bytes: frames.total_bytes,
            partial_tail: frames.partial_tail,
        });
    }

    let first: JournalWalEntry = serde_json::from_slice(&frames.frames[0])?;
    first.validate()?;
    let replay_from_checkpoint = first.sequence == snapshot_sequence.saturating_add(1)
        && first.previous_checksum == snapshot_frontier;
    let replay_full_chain = first.sequence == 1 && first.previous_checksum.is_none();
    let replay_checkpoint_suffix = snapshot_sequence != 0 && first.sequence <= snapshot_sequence;
    if !replay_from_checkpoint && !replay_full_chain && !replay_checkpoint_suffix {
        return Err(ShellError::State(
            "native journal WAL does not continue or terminate at the durable checkpoint"
                .to_owned(),
        ));
    }
    let mut previous_sequence = if replay_from_checkpoint {
        snapshot_sequence
    } else {
        first.sequence - 1
    };
    let mut previous_checksum = if replay_from_checkpoint {
        snapshot_frontier.clone()
    } else {
        first.previous_checksum.clone()
    };
    let mut snapshot_seen = snapshot_sequence == 0 || replay_from_checkpoint;
    for bytes in frames.frames {
        let entry: JournalWalEntry = serde_json::from_slice(&bytes)?;
        entry.validate()?;
        if entry.sequence != previous_sequence.saturating_add(1)
            || entry.previous_checksum != previous_checksum
        {
            return Err(ShellError::State(
                "native journal WAL chain is discontinuous".to_owned(),
            ));
        }
        if entry.sequence == snapshot_sequence {
            if Some(entry.checksum.clone()) != snapshot_frontier {
                return Err(ShellError::State(
                    "native journal WAL disagrees with the durable checkpoint frontier".to_owned(),
                ));
            }
            snapshot_seen = true;
        }
        if entry.sequence > snapshot_sequence {
            if !snapshot_seen {
                return Err(ShellError::State(
                    "native journal WAL skipped its durable checkpoint".to_owned(),
                ));
            }
            apply_replayed_record(operations, &mut index, entry.record.clone())?;
            applied_entries = applied_entries.checked_add(1).ok_or_else(|| {
                ShellError::State("native journal WAL replay count overflow".to_owned())
            })?;
            sequence = entry.sequence;
            frontier = Some(entry.checksum.clone());
        }
        previous_sequence = entry.sequence;
        previous_checksum = Some(entry.checksum);
    }
    if !snapshot_seen {
        return Err(ShellError::State(
            "native journal WAL lacks the durable checkpoint frontier".to_owned(),
        ));
    }
    Ok(WalReplay {
        sequence,
        frontier,
        applied_entries,
        valid_bytes: frames.valid_bytes,
        total_bytes: frames.total_bytes,
        partial_tail: frames.partial_tail,
    })
}

fn apply_replayed_record(
    operations: &mut Vec<OperationRecord>,
    index: &mut HashMap<OperationKey, usize>,
    record: OperationRecord,
) -> Result<(), ShellError> {
    record.validate()?;
    if let Some(existing_index) = index.get(&record.key).copied() {
        validate_transition(&operations[existing_index], &record)?;
        operations[existing_index] = record;
    } else {
        if operations.len() >= MAX_OPERATION_RECORDS {
            return Err(ShellError::State(format!(
                "operation journal WAL replay exceeds {MAX_OPERATION_RECORDS} records"
            )));
        }
        let record_index = operations.len();
        index.insert(record.key.clone(), record_index);
        operations.push(record);
    }
    Ok(())
}

pub(super) fn build_operation_index(
    operations: &[OperationRecord],
) -> Result<HashMap<OperationKey, usize>, ShellError> {
    let mut index = HashMap::with_capacity(operations.len());
    for (position, record) in operations.iter().enumerate() {
        if index.insert(record.key.clone(), position).is_some() {
            return Err(ShellError::State(
                "duplicate operation identity in journal".to_owned(),
            ));
        }
    }
    Ok(index)
}

pub(super) fn validate_transition(
    existing: &OperationRecord,
    record: &OperationRecord,
) -> Result<(), ShellError> {
    if existing.endpoint_id != record.endpoint_id
        || existing.subject_id != record.subject_id
        || existing.displayed_revision != record.displayed_revision
        || existing.action != record.action
        || existing.payload_digest != record.payload_digest
        || existing.binding_digest != record.binding_digest
        || existing.grant_digest != record.grant_digest
    {
        return Err(ShellError::State(
            "operation identity was reused with changed semantics".to_owned(),
        ));
    }
    if existing == record {
        return Ok(());
    }
    if matches!(
        existing.phase,
        OperationPhase::Terminal | OperationPhase::ObservationClosed
    ) {
        return Err(ShellError::State(
            "terminal operation observation is immutable".to_owned(),
        ));
    }
    if !phase_transition_allowed(existing.phase, record.phase) {
        return Err(ShellError::State(format!(
            "operation phase cannot transition from {:?} to {:?}",
            existing.phase, record.phase
        )));
    }
    Ok(())
}

pub(crate) fn retirement_digest(
    endpoint_id: &str,
    key: &OperationKey,
) -> Result<String, ShellError> {
    validate_stable_id(endpoint_id, "retirement.endpoint_id")?;
    validate_stable_id(&key.session_id, "retirement.session_id")?;
    validate_stable_id(&key.operation_id, "retirement.operation_id")?;
    if key.session_generation == 0 {
        return Err(ShellError::State(
            "retired operation has zero session generation".to_owned(),
        ));
    }
    Ok(sha256_hex(serde_json::to_vec(&(
        "hepta.native-retired-operation.v1",
        endpoint_id,
        key,
    ))?))
}

fn phase_transition_allowed(from: OperationPhase, to: OperationPhase) -> bool {
    match from {
        OperationPhase::Prepared => matches!(
            to,
            OperationPhase::Prepared
                | OperationPhase::Invoking
                | OperationPhase::Indeterminate
                | OperationPhase::Terminal
        ),
        OperationPhase::Invoking => matches!(
            to,
            OperationPhase::Invoking | OperationPhase::Indeterminate | OperationPhase::Terminal
        ),
        OperationPhase::Indeterminate => {
            matches!(
                to,
                OperationPhase::Indeterminate
                    | OperationPhase::ObservationClosed
                    | OperationPhase::Terminal
            )
        }
        OperationPhase::Terminal => to == OperationPhase::Terminal,
        OperationPhase::ObservationClosed => to == OperationPhase::ObservationClosed,
    }
}

#[cfg(test)]
#[path = "journal_wal_tests.rs"]
mod wal_tests;
