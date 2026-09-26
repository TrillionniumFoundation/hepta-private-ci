//! Durable exact-replay outbox for canonical intelligence learning facts.
//!
//! The outbox stores the complete canonical payload before the learning owner is
//! called. A process restart replays only the same payload and predecessor. It
//! never treats an ambiguous append as success and never authorizes a model or
//! external effect.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const OUTBOX_SCHEMA_VERSION: u32 = 1;
const MAX_OUTBOX_RECORDS: usize = 16_384;
const MAX_OUTBOX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_OUTBOX_LINE_BYTES: usize = 8 * 1024 * 1024;
const MAX_OUTBOX_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceLearningIntentKindV1 {
    Decision,
    Outcome,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IntelligenceLearningOutboxStateV1 {
    Prepared,
    Indeterminate,
    Acknowledged,
    Rejected,
    Revoked,
}

impl IntelligenceLearningOutboxStateV1 {
    #[must_use]
    pub const fn terminal(self) -> bool {
        matches!(Self::Acknowledged | Self::Rejected | Self::Revoked, self)
    }

    #[must_use]
    pub const fn reconcileable(self) -> bool {
        matches!(Self::Prepared | Self::Indeterminate, self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceLearningIntentV1 {
    pub intent_id: StableId,
    pub run_id: StableId,
    pub kind: IntelligenceLearningIntentKindV1,
    pub expected_predecessor: Digest32,
    pub run_snapshot_digest: Digest32,
    pub decision_digest: Digest32,
    pub selected_candidate_id: StableId,
    pub payload_digest: Digest32,
    pub payload: Vec<u8>,
}

impl IntelligenceLearningIntentV1 {
    pub fn validate(&self) -> Result<(), IntelligenceLearningOutboxError> {
        if self.expected_predecessor.is_zero()
            || self.run_snapshot_digest.is_zero()
            || self.decision_digest.is_zero()
            || self.payload_digest.is_zero()
            || self.payload.is_empty()
            || self.payload.len() > MAX_OUTBOX_PAYLOAD_BYTES
            || Digest32::of_bytes(&self.payload) != self.payload_digest
        {
            return Err(IntelligenceLearningOutboxError::InvalidIntent);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceLearningOutboxRecordV1 {
    pub revision: u64,
    pub state: IntelligenceLearningOutboxStateV1,
    pub intent: IntelligenceLearningIntentV1,
    pub terminal_evidence_digest: Option<Digest32>,
}

#[derive(Debug, thiserror::Error)]
pub enum IntelligenceLearningOutboxError {
    #[error("outbox path must be absolute")]
    RelativePath,
    #[error("outbox intent is invalid")]
    InvalidIntent,
    #[error("outbox journal is corrupt")]
    Corrupt,
    #[error("outbox capacity exceeded")]
    Capacity,
    #[error("outbox record is missing")]
    Missing,
    #[error("outbox semantic conflict")]
    Conflict,
    #[error("outbox revision is stale")]
    StaleRevision,
    #[error("outbox transition is invalid")]
    InvalidTransition,
    #[error("outbox writer is fenced after an ambiguous I/O result")]
    WriterFenced,
    #[error("outbox I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("outbox encoding failed: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum IntentKindWireV1 {
    Decision,
    Outcome,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum StateWireV1 {
    Prepared,
    Indeterminate,
    Acknowledged,
    Rejected,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalRowV1 {
    schema_version: u32,
    revision: u64,
    state: StateWireV1,
    intent_id: String,
    run_id: String,
    kind: IntentKindWireV1,
    expected_predecessor: String,
    run_snapshot_digest: String,
    decision_digest: String,
    selected_candidate_id: String,
    payload_digest: String,
    payload: Vec<u8>,
    terminal_evidence_digest: Option<String>,
}

pub struct IntelligenceLearningOutboxV1 {
    path: PathBuf,
    writer: File,
    records: BTreeMap<StableId, IntelligenceLearningOutboxRecordV1>,
    bytes: u64,
    writer_fenced: bool,
}

impl IntelligenceLearningOutboxV1 {
    pub fn open(path: PathBuf) -> Result<Self, IntelligenceLearningOutboxError> {
        if !path.is_absolute() {
            return Err(IntelligenceLearningOutboxError::RelativePath);
        }
        let parent = path.parent().ok_or(IntelligenceLearningOutboxError::RelativePath)?;
        std::fs::create_dir_all(parent)?;
        let existed = path.exists();
        let writer = open_private_append(&path)?;
        if !existed {
            writer.sync_all()?;
            sync_parent(parent)?;
        }
        let metadata = writer.metadata()?;
        if metadata.len() > MAX_OUTBOX_BYTES {
            return Err(IntelligenceLearningOutboxError::Capacity);
        }
        let mut records = BTreeMap::new();
        if metadata.len() > 0 {
            let reader = BufReader::new(File::open(&path)?);
            for line in reader.split(b'\n') {
                let line = line?;
                if line.is_empty() {
                    continue;
                }
                if line.len() > MAX_OUTBOX_LINE_BYTES {
                    return Err(IntelligenceLearningOutboxError::Corrupt);
                }
                let row: JournalRowV1 = serde_json::from_slice(&line)?;
                let record = record_from_row(row)?;
                apply_replayed_record(&mut records, record)?;
            }
        }
        Ok(Self {
            path,
            writer,
            records,
            bytes: metadata.len(),
            writer_fenced: false,
        })
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    #[must_use]
    pub fn backlog(&self) -> usize {
        self.records
            .values()
            .filter(|record| record.state.reconcileable())
            .count()
    }

    #[must_use]
    pub fn record(
        &self,
        intent_id: &StableId,
    ) -> Option<IntelligenceLearningOutboxRecordV1> {
        self.records.get(intent_id).cloned()
    }

    #[must_use]
    pub fn reconcileable(&self) -> Vec<IntelligenceLearningOutboxRecordV1> {
        self.records
            .values()
            .filter(|record| record.state.reconcileable())
            .cloned()
            .collect()
    }

    pub fn prepare(
        &mut self,
        intent: IntelligenceLearningIntentV1,
    ) -> Result<IntelligenceLearningOutboxRecordV1, IntelligenceLearningOutboxError> {
        self.require_writer()?;
        intent.validate()?;
        if let Some(existing) = self.records.get(&intent.intent_id) {
            if existing.intent == intent {
                return Ok(existing.clone());
            }
            return Err(IntelligenceLearningOutboxError::Conflict);
        }
        if self.records.len() >= MAX_OUTBOX_RECORDS {
            return Err(IntelligenceLearningOutboxError::Capacity);
        }
        let record = IntelligenceLearningOutboxRecordV1 {
            revision: 1,
            state: IntelligenceLearningOutboxStateV1::Prepared,
            intent,
            terminal_evidence_digest: None,
        };
        self.append(record.clone())?;
        self.records
            .insert(record.intent.intent_id.clone(), record.clone());
        Ok(record)
    }

    pub fn transition(
        &mut self,
        intent_id: &StableId,
        expected_revision: u64,
        state: IntelligenceLearningOutboxStateV1,
        evidence_digest: Digest32,
    ) -> Result<IntelligenceLearningOutboxRecordV1, IntelligenceLearningOutboxError> {
        self.require_writer()?;
        if evidence_digest.is_zero() || state == IntelligenceLearningOutboxStateV1::Prepared {
            return Err(IntelligenceLearningOutboxError::InvalidTransition);
        }
        let existing = self
            .records
            .get(intent_id)
            .cloned()
            .ok_or(IntelligenceLearningOutboxError::Missing)?;
        if existing.state == state
            && existing.terminal_evidence_digest == Some(evidence_digest)
        {
            return Ok(existing);
        }
        if existing.revision != expected_revision {
            return Err(IntelligenceLearningOutboxError::StaleRevision);
        }
        let allowed = match existing.state {
            IntelligenceLearningOutboxStateV1::Prepared => true,
            IntelligenceLearningOutboxStateV1::Indeterminate => {
                state != IntelligenceLearningOutboxStateV1::Prepared
            }
            IntelligenceLearningOutboxStateV1::Acknowledged
            | IntelligenceLearningOutboxStateV1::Rejected
            | IntelligenceLearningOutboxStateV1::Revoked => false,
        };
        if !allowed {
            return Err(IntelligenceLearningOutboxError::InvalidTransition);
        }
        let revision = existing
            .revision
            .checked_add(1)
            .ok_or(IntelligenceLearningOutboxError::Capacity)?;
        let next = IntelligenceLearningOutboxRecordV1 {
            revision,
            state,
            intent: existing.intent,
            terminal_evidence_digest: Some(evidence_digest),
        };
        self.append(next.clone())?;
        self.records.insert(intent_id.clone(), next.clone());
        Ok(next)
    }

    fn require_writer(&self) -> Result<(), IntelligenceLearningOutboxError> {
        if self.writer_fenced {
            Err(IntelligenceLearningOutboxError::WriterFenced)
        } else {
            Ok(())
        }
    }

    fn append(
        &mut self,
        record: IntelligenceLearningOutboxRecordV1,
    ) -> Result<(), IntelligenceLearningOutboxError> {
        let mut encoded = serde_json::to_vec(&row_from_record(&record))?;
        if encoded.len() > MAX_OUTBOX_LINE_BYTES {
            return Err(IntelligenceLearningOutboxError::Capacity);
        }
        encoded.push(b'\n');
        let encoded_len = u64::try_from(encoded.len())
            .map_err(|_| IntelligenceLearningOutboxError::Capacity)?;
        if self
            .bytes
            .checked_add(encoded_len)
            .is_none_or(|value| value > MAX_OUTBOX_BYTES)
        {
            return Err(IntelligenceLearningOutboxError::Capacity);
        }
        if let Err(error) = self.writer.write_all(&encoded).and_then(|()| self.writer.sync_data()) {
            self.writer_fenced = true;
            return Err(IntelligenceLearningOutboxError::Io(error));
        }
        self.bytes += encoded_len;
        Ok(())
    }
}

fn apply_replayed_record(
    records: &mut BTreeMap<StableId, IntelligenceLearningOutboxRecordV1>,
    record: IntelligenceLearningOutboxRecordV1,
) -> Result<(), IntelligenceLearningOutboxError> {
    record.intent.validate()?;
    match records.get(&record.intent.intent_id) {
        None if record.revision == 1
            && record.state == IntelligenceLearningOutboxStateV1::Prepared
            && record.terminal_evidence_digest.is_none() => {}
        Some(previous)
            if previous.intent == record.intent
                && record.revision == previous.revision.saturating_add(1)
                && record.state != IntelligenceLearningOutboxStateV1::Prepared
                && record.terminal_evidence_digest.is_some()
                && !previous.state.terminal() => {}
        _ => return Err(IntelligenceLearningOutboxError::Corrupt),
    }
    records.insert(record.intent.intent_id.clone(), record);
    Ok(())
}

fn row_from_record(record: &IntelligenceLearningOutboxRecordV1) -> JournalRowV1 {
    JournalRowV1 {
        schema_version: OUTBOX_SCHEMA_VERSION,
        revision: record.revision,
        state: state_to_wire(record.state),
        intent_id: record.intent.intent_id.to_string(),
        run_id: record.intent.run_id.to_string(),
        kind: match record.intent.kind {
            IntelligenceLearningIntentKindV1::Decision => IntentKindWireV1::Decision,
            IntelligenceLearningIntentKindV1::Outcome => IntentKindWireV1::Outcome,
        },
        expected_predecessor: record.intent.expected_predecessor.to_string(),
        run_snapshot_digest: record.intent.run_snapshot_digest.to_string(),
        decision_digest: record.intent.decision_digest.to_string(),
        selected_candidate_id: record.intent.selected_candidate_id.to_string(),
        payload_digest: record.intent.payload_digest.to_string(),
        payload: record.intent.payload.clone(),
        terminal_evidence_digest: record
            .terminal_evidence_digest
            .map(|digest| digest.to_string()),
    }
}

fn record_from_row(
    row: JournalRowV1,
) -> Result<IntelligenceLearningOutboxRecordV1, IntelligenceLearningOutboxError> {
    if row.schema_version != OUTBOX_SCHEMA_VERSION || row.revision == 0 {
        return Err(IntelligenceLearningOutboxError::Corrupt);
    }
    let terminal_evidence_digest = row
        .terminal_evidence_digest
        .map(|value| Digest32::from_str(&value))
        .transpose()
        .map_err(|_| IntelligenceLearningOutboxError::Corrupt)?;
    Ok(IntelligenceLearningOutboxRecordV1 {
        revision: row.revision,
        state: state_from_wire(row.state),
        intent: IntelligenceLearningIntentV1 {
            intent_id: StableId::new(row.intent_id)
                .map_err(|_| IntelligenceLearningOutboxError::Corrupt)?,
            run_id: StableId::new(row.run_id)
                .map_err(|_| IntelligenceLearningOutboxError::Corrupt)?,
            kind: match row.kind {
                IntentKindWireV1::Decision => IntelligenceLearningIntentKindV1::Decision,
                IntentKindWireV1::Outcome => IntelligenceLearningIntentKindV1::Outcome,
            },
            expected_predecessor: parse_digest(&row.expected_predecessor)?,
            run_snapshot_digest: parse_digest(&row.run_snapshot_digest)?,
            decision_digest: parse_digest(&row.decision_digest)?,
            selected_candidate_id: StableId::new(row.selected_candidate_id)
                .map_err(|_| IntelligenceLearningOutboxError::Corrupt)?,
            payload_digest: parse_digest(&row.payload_digest)?,
            payload: row.payload,
        },
        terminal_evidence_digest,
    })
}

fn state_to_wire(state: IntelligenceLearningOutboxStateV1) -> StateWireV1 {
    match state {
        IntelligenceLearningOutboxStateV1::Prepared => StateWireV1::Prepared,
        IntelligenceLearningOutboxStateV1::Indeterminate => StateWireV1::Indeterminate,
        IntelligenceLearningOutboxStateV1::Acknowledged => StateWireV1::Acknowledged,
        IntelligenceLearningOutboxStateV1::Rejected => StateWireV1::Rejected,
        IntelligenceLearningOutboxStateV1::Revoked => StateWireV1::Revoked,
    }
}

fn state_from_wire(state: StateWireV1) -> IntelligenceLearningOutboxStateV1 {
    match state {
        StateWireV1::Prepared => IntelligenceLearningOutboxStateV1::Prepared,
        StateWireV1::Indeterminate => IntelligenceLearningOutboxStateV1::Indeterminate,
        StateWireV1::Acknowledged => IntelligenceLearningOutboxStateV1::Acknowledged,
        StateWireV1::Rejected => IntelligenceLearningOutboxStateV1::Rejected,
        StateWireV1::Revoked => IntelligenceLearningOutboxStateV1::Revoked,
    }
}

fn parse_digest(value: &str) -> Result<Digest32, IntelligenceLearningOutboxError> {
    let digest = Digest32::from_str(value).map_err(|_| IntelligenceLearningOutboxError::Corrupt)?;
    if digest.is_zero() {
        return Err(IntelligenceLearningOutboxError::Corrupt);
    }
    Ok(digest)
}

#[cfg(unix)]
fn open_private_append(path: &Path) -> Result<File, std::io::Error> {
    use std::os::unix::fs::OpenOptionsExt;

    OpenOptions::new()
        .create(true)
        .read(true)
        .append(true)
        .mode(0o600)
        .open(path)
}

#[cfg(not(unix))]
fn open_private_append(path: &Path) -> Result<File, std::io::Error> {
    OpenOptions::new()
        .create(true)
        .read(true)
        .append(true)
        .open(path)
}

fn sync_parent(parent: &Path) -> Result<(), std::io::Error> {
    File::open(parent)?.sync_all()
}

#[cfg(test)]
#[path = "intelligence_learning_outbox_tests.rs"]
mod tests;
