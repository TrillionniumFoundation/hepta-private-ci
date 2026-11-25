use std::fs;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use tempfile::NamedTempFile;

use super::CellSplitCheckpointV1;
use super::CellSplitChildStateV1;
use super::CellSplitCommittedStateV1;
use super::CellSplitInFlightMessageV1;
use super::CellSplitMigrationError;
use super::CellSplitParentStateV1;
use super::CellSplitPhaseV1;

pub(super) const JOURNAL_VERSION: u64 = 1;

#[derive(Clone, Debug)]
pub(super) struct JournalState {
    pub(super) sequence: u64,
    pub(super) head: Digest32,
    pub(super) witness: Digest32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedEnvelope {
    pub(super) version: u64,
    pub(super) sequence: u64,
    pub(super) phase: String,
    pub(super) writer_fence: u64,
    pub(super) head: String,
    pub(super) state: PersistedCommittedState,
    pub(super) witness: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedCommittedState {
    pub(super) parent: PersistedParentState,
    pub(super) children: Vec<PersistedChildState>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedParentState {
    pub(super) checkpoint_generation: u64,
    pub(super) checkpoint_digest: String,
    pub(super) checkpoint_committed: bool,
    pub(super) selected_weights: String,
    pub(super) recurrent_state: Vec<u8>,
    pub(super) eligibility_state: Vec<u8>,
    pub(super) optimizer_state: Vec<u8>,
    pub(super) cache: Vec<u8>,
    pub(super) cache_generation: u64,
    pub(super) in_flight: Vec<PersistedMessage>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedMessage {
    pub(super) message_id: String,
    pub(super) source_generation: u64,
    pub(super) payload: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedChildState {
    pub(super) child_id: String,
    pub(super) candidate_weights: String,
    pub(super) selected_weights: String,
    pub(super) recurrent_state: Vec<u8>,
    pub(super) eligibility_state: Vec<u8>,
    pub(super) optimizer_state: Vec<u8>,
    pub(super) cache: Vec<u8>,
    pub(super) cache_generation: u64,
    pub(super) message_fence: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct PersistedSnapshot {
    pub(super) version: u64,
    pub(super) plan_digest: String,
    pub(super) predecessor_generation: u64,
    pub(super) candidate_generation: u64,
    pub(super) state: PersistedCommittedState,
}

pub(super) fn phase_name(phase: CellSplitPhaseV1) -> &'static str {
    match phase {
        CellSplitPhaseV1::Empty => "empty",
        CellSplitPhaseV1::Prepared => "prepared",
        CellSplitPhaseV1::Migrating => "migrating",
        CellSplitPhaseV1::Committed => "committed",
        CellSplitPhaseV1::RolledBack => "rolled_back",
        CellSplitPhaseV1::Quarantined => "quarantined",
    }
}

pub(super) fn decode_phase(value: &str) -> Result<CellSplitPhaseV1, CellSplitMigrationError> {
    match value {
        "empty" => Ok(CellSplitPhaseV1::Empty),
        "prepared" => Ok(CellSplitPhaseV1::Prepared),
        "migrating" => Ok(CellSplitPhaseV1::Migrating),
        "committed" => Ok(CellSplitPhaseV1::Committed),
        "rolled_back" => Ok(CellSplitPhaseV1::RolledBack),
        "quarantined" => Ok(CellSplitPhaseV1::Quarantined),
        _ => Err(CellSplitMigrationError::JournalCorrupt),
    }
}

pub(super) fn parse_digest(value: &str) -> Result<Digest32, CellSplitMigrationError> {
    value
        .parse()
        .map_err(|_| CellSplitMigrationError::JournalCorrupt)
}

pub(super) fn validate_envelope(
    envelope: &PersistedEnvelope,
) -> Result<(), CellSplitMigrationError> {
    if envelope.version != JOURNAL_VERSION {
        return Err(CellSplitMigrationError::JournalCorrupt);
    }
    let witness = envelope.witness.clone();
    let mut unsigned = envelope.clone();
    unsigned.witness.clear();
    let expected = Digest32::of_bytes(
        &serde_json::to_vec(&unsigned).map_err(|_| CellSplitMigrationError::JournalCorrupt)?,
    );
    if witness != expected.to_string() {
        return Err(CellSplitMigrationError::JournalCorrupt);
    }
    parse_digest(&envelope.head)?;
    parse_digest(&envelope.witness)?;
    decode_phase(&envelope.phase)?;
    Ok(())
}

pub(super) fn replace_envelope(
    path: &Path,
    expected_head: Digest32,
    envelope: &PersistedEnvelope,
) -> Result<(), CellSplitMigrationError> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|_| CellSplitMigrationError::JournalIo)?;
    let mut lock_name = path
        .file_name()
        .ok_or(CellSplitMigrationError::JournalIo)?
        .to_owned();
    lock_name.push(".lock");
    // Lock a stable sibling, not the journal inode that atomic replacement changes.
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(parent.join(lock_name))
        .map_err(|_| CellSplitMigrationError::JournalIo)?;
    lock.lock()
        .map_err(|_| CellSplitMigrationError::JournalIo)?;

    match fs::read(path) {
        Ok(bytes) => {
            let current: PersistedEnvelope = serde_json::from_slice(&bytes)
                .map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
            validate_envelope(&current)?;
            if parse_digest(&current.head)? != expected_head {
                return Err(CellSplitMigrationError::CompareAndSwap);
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            if expected_head != Digest32::ZERO {
                return Err(CellSplitMigrationError::CompareAndSwap);
            }
        }
        Err(_) => return Err(CellSplitMigrationError::JournalIo),
    }

    let bytes =
        serde_json::to_vec(envelope).map_err(|_| CellSplitMigrationError::JournalCorrupt)?;
    let mut temporary =
        NamedTempFile::new_in(parent).map_err(|_| CellSplitMigrationError::JournalIo)?;
    temporary
        .write_all(&bytes)
        .and_then(|()| temporary.as_file().sync_all())
        .map_err(|_| CellSplitMigrationError::JournalIo)?;
    temporary
        .persist(path)
        .map_err(|_| CellSplitMigrationError::JournalIo)?;
    Ok(())
}

pub(super) fn encode_state(
    state: &CellSplitCommittedStateV1,
) -> Result<PersistedCommittedState, CellSplitMigrationError> {
    Ok(PersistedCommittedState {
        parent: PersistedParentState {
            checkpoint_generation: state.parent.checkpoint.generation,
            checkpoint_digest: state.parent.checkpoint.digest.to_string(),
            checkpoint_committed: state.parent.checkpoint.committed,
            selected_weights: state.parent.selected_weights.to_string(),
            recurrent_state: state.parent.recurrent_state.clone(),
            eligibility_state: state.parent.eligibility_state.clone(),
            optimizer_state: state.parent.optimizer_state.clone(),
            cache: state.parent.cache.clone(),
            cache_generation: state.parent.cache_generation,
            in_flight: state
                .parent
                .in_flight
                .iter()
                .map(|message| PersistedMessage {
                    message_id: message.message_id.clone(),
                    source_generation: message.source_generation,
                    payload: message.payload.clone(),
                })
                .collect(),
        },
        children: state
            .children
            .iter()
            .map(|child| PersistedChildState {
                child_id: child.child_id.clone(),
                candidate_weights: child.candidate_weights.to_string(),
                selected_weights: child.selected_weights.to_string(),
                recurrent_state: child.recurrent_state.clone(),
                eligibility_state: child.eligibility_state.clone(),
                optimizer_state: child.optimizer_state.clone(),
                cache: child.cache.clone(),
                cache_generation: child.cache_generation,
                message_fence: child.message_fence.to_string(),
            })
            .collect(),
    })
}

pub(super) fn decode_state(
    state: &PersistedCommittedState,
) -> Result<CellSplitCommittedStateV1, CellSplitMigrationError> {
    Ok(CellSplitCommittedStateV1 {
        parent: CellSplitParentStateV1 {
            checkpoint: CellSplitCheckpointV1 {
                generation: state.parent.checkpoint_generation,
                digest: parse_digest(&state.parent.checkpoint_digest)?,
                committed: state.parent.checkpoint_committed,
            },
            selected_weights: parse_digest(&state.parent.selected_weights)?,
            recurrent_state: state.parent.recurrent_state.clone(),
            eligibility_state: state.parent.eligibility_state.clone(),
            optimizer_state: state.parent.optimizer_state.clone(),
            cache: state.parent.cache.clone(),
            cache_generation: state.parent.cache_generation,
            in_flight: state
                .parent
                .in_flight
                .iter()
                .map(|message| CellSplitInFlightMessageV1 {
                    message_id: message.message_id.clone(),
                    source_generation: message.source_generation,
                    payload: message.payload.clone(),
                })
                .collect(),
        },
        children: state
            .children
            .iter()
            .map(|child| {
                Ok(CellSplitChildStateV1 {
                    child_id: child.child_id.clone(),
                    candidate_weights: parse_digest(&child.candidate_weights)?,
                    selected_weights: parse_digest(&child.selected_weights)?,
                    recurrent_state: child.recurrent_state.clone(),
                    eligibility_state: child.eligibility_state.clone(),
                    optimizer_state: child.optimizer_state.clone(),
                    cache: child.cache.clone(),
                    cache_generation: child.cache_generation,
                    message_fence: parse_digest(&child.message_fence)?,
                })
            })
            .collect::<Result<Vec<_>, CellSplitMigrationError>>()?,
    })
}
