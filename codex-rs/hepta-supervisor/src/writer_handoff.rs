//! Crash-recoverable authoritative-writer handoff journal.
//!
//! Stateful module replacement cannot be represented by an in-process graph
//! swap alone. This journal records a monotonic, fsync-backed handoff protocol
//! whose phases correspond to the architecture invariants: stop admission,
//! drain the predecessor outbox, fence the old writer, snapshot, migrate,
//! validate, fence the new writer, publish the route, then retire the old
//! writer. The journal never performs those effects itself; the owning
//! supervisor records a phase only after it has independently observed the
//! corresponding evidence. Replaying a step is idempotent and a torn final
//! append is truncated on recovery.

use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const MAGIC: &[u8] = b"HEPTA-WRITER-HANDOFF-V1\n";
const SCHEMA_VERSION: u16 = 1;
const MAX_RECORD_BYTES: usize = 64 * 1024;
const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WriterHandoffPhaseV1 {
    Prepared,
    AdmissionStopped,
    Drained,
    OldWriterFenced,
    Snapshotted,
    Migrated,
    Validated,
    NewWriterFenced,
    RoutePublished,
    Retired,
    Quarantined,
}

impl WriterHandoffPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::AdmissionStopped => 1,
            Self::Drained => 2,
            Self::OldWriterFenced => 3,
            Self::Snapshotted => 4,
            Self::Migrated => 5,
            Self::Validated => 6,
            Self::NewWriterFenced => 7,
            Self::RoutePublished => 8,
            Self::Retired => 9,
            Self::Quarantined => 10,
        }
    }

    const fn is_terminal(self) -> bool {
        matches!(self, Self::Retired | Self::Quarantined)
    }

    const fn at_or_after_drained(self) -> bool {
        matches!(
            self,
            Self::Drained
                | Self::OldWriterFenced
                | Self::Snapshotted
                | Self::Migrated
                | Self::Validated
                | Self::NewWriterFenced
                | Self::RoutePublished
                | Self::Retired
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterHandoffPlanV1 {
    pub operation_id: StableId,
    pub domain_id: StableId,
    pub source_writer: StableId,
    pub target_writer: StableId,
    pub old_generation: Generation,
    pub new_generation: Generation,
    pub authority_epoch: u64,
    pub migration_plan_digest: Digest32,
    pub schema_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
}

impl WriterHandoffPlanV1 {
    pub fn validate(&self) -> Result<(), WriterHandoffErrorV1> {
        if self.authority_epoch == 0 {
            return Err(WriterHandoffErrorV1::ZeroAuthorityEpoch);
        }
        if self.old_generation.next().ok() != Some(self.new_generation) {
            return Err(WriterHandoffErrorV1::NonSuccessorGeneration);
        }
        for (name, digest) in [
            ("migration plan", self.migration_plan_digest),
            ("schema", self.schema_digest),
            ("rollback predecessor", self.rollback_predecessor_digest),
        ] {
            if digest.is_zero() {
                return Err(WriterHandoffErrorV1::EmptyDigest(name));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterHandoffAdvanceV1 {
    pub phase: WriterHandoffPhaseV1,
    pub evidence_digest: Digest32,
    /// Required exactly when entering `Drained`; retained thereafter.
    pub outbox_watermark: Option<u64>,
    /// Must be zero once the predecessor is declared drained.
    pub unknown_effect_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterHandoffCheckpointV1 {
    pub plan: WriterHandoffPlanV1,
    pub revision: u64,
    pub phase: WriterHandoffPhaseV1,
    pub outbox_watermark: Option<u64>,
    pub unknown_effect_count: u32,
    pub evidence_digest: Digest32,
    pub previous_receipt_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl WriterHandoffCheckpointV1 {
    pub fn old_writer_admission_open(&self) -> bool {
        self.phase == WriterHandoffPhaseV1::Prepared
    }

    pub fn new_writer_admission_open(&self) -> bool {
        matches!(
            self.phase,
            WriterHandoffPhaseV1::RoutePublished | WriterHandoffPhaseV1::Retired
        )
    }

    pub fn old_writer_valid(&self) -> bool {
        matches!(
            self.phase,
            WriterHandoffPhaseV1::Prepared
                | WriterHandoffPhaseV1::AdmissionStopped
                | WriterHandoffPhaseV1::Drained
        )
    }

    pub fn new_writer_valid(&self) -> bool {
        matches!(
            self.phase,
            WriterHandoffPhaseV1::NewWriterFenced
                | WriterHandoffPhaseV1::RoutePublished
                | WriterHandoffPhaseV1::Retired
        )
    }

    pub fn rollback_predecessor(&self) -> Digest32 {
        self.plan.rollback_predecessor_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WriterHandoffErrorV1 {
    ZeroAuthorityEpoch,
    NonSuccessorGeneration,
    EmptyDigest(&'static str),
    InvalidTransition {
        from: WriterHandoffPhaseV1,
        to: WriterHandoffPhaseV1,
    },
    MissingOutboxWatermark,
    OutboxWatermarkChanged,
    UnknownEffectsRemain(u32),
    AlreadyInitialized,
    MissingHeader,
    MissingCheckpoint,
    RecordTooLarge,
    JournalTooLarge,
    Corrupt,
    Poisoned,
    Indeterminate,
    Io(std::io::ErrorKind),
}

impl fmt::Display for WriterHandoffErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for WriterHandoffErrorV1 {}

impl From<std::io::Error> for WriterHandoffErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Debug)]
pub struct DurableWriterHandoffJournalV1 {
    file: File,
    checkpoint: WriterHandoffCheckpointV1,
    durable_length: u64,
    poisoned: bool,
}

impl DurableWriterHandoffJournalV1 {
    /// Create a new journal on an explicitly supplied, exclusively owned file.
    pub fn create(mut file: File, plan: WriterHandoffPlanV1) -> Result<Self, WriterHandoffErrorV1> {
        plan.validate()?;
        if file.metadata()?.len() != 0 {
            return Err(WriterHandoffErrorV1::AlreadyInitialized);
        }
        let mut checkpoint = WriterHandoffCheckpointV1 {
            evidence_digest: plan.migration_plan_digest,
            plan,
            revision: 1,
            phase: WriterHandoffPhaseV1::Prepared,
            outbox_watermark: None,
            unknown_effect_count: 0,
            previous_receipt_digest: Digest32::ZERO,
            receipt_digest: Digest32::ZERO,
        };
        checkpoint.receipt_digest = checkpoint_digest(&checkpoint);
        let record = encode_checkpoint(&checkpoint)?;
        let next_length = MAGIC.len() as u64 + record.len() as u64 + 1;
        if next_length > MAX_JOURNAL_BYTES {
            return Err(WriterHandoffErrorV1::JournalTooLarge);
        }
        file.seek(SeekFrom::Start(0))?;
        file.write_all(MAGIC)
            .and_then(|()| file.write_all(&record))
            .and_then(|()| file.write_all(b"\n"))
            .and_then(|()| file.sync_all())
            .map_err(|_| WriterHandoffErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            checkpoint,
            durable_length: next_length,
            poisoned: false,
        })
    }

    /// Recover the latest completely fsynced checkpoint. A torn final append
    /// is discarded; corruption in any complete record fails closed.
    pub fn recover(mut file: File) -> Result<Self, WriterHandoffErrorV1> {
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        if !bytes.starts_with(MAGIC) {
            return Err(WriterHandoffErrorV1::MissingHeader);
        }
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(WriterHandoffErrorV1::JournalTooLarge);
        }

        let mut cursor = MAGIC.len();
        let mut previous: Option<WriterHandoffCheckpointV1> = None;
        while cursor < bytes.len() {
            let Some(relative_newline) = bytes[cursor..].iter().position(|byte| *byte == b'\n')
            else {
                break;
            };
            let end = cursor + relative_newline;
            if end == cursor || end - cursor > MAX_RECORD_BYTES {
                return Err(WriterHandoffErrorV1::Corrupt);
            }
            let checkpoint = decode_checkpoint(&bytes[cursor..end])?;
            validate_recovered_checkpoint(previous.as_ref(), &checkpoint)?;
            previous = Some(checkpoint);
            cursor = end + 1;
        }
        let checkpoint = previous.ok_or(WriterHandoffErrorV1::MissingCheckpoint)?;
        if cursor != bytes.len() {
            file.set_len(cursor as u64)
                .and_then(|()| file.sync_all())
                .map_err(|_| WriterHandoffErrorV1::Indeterminate)?;
        }
        file.seek(SeekFrom::Start(cursor as u64))?;
        Ok(Self {
            file,
            checkpoint,
            durable_length: cursor as u64,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn checkpoint(&self) -> &WriterHandoffCheckpointV1 {
        &self.checkpoint
    }

    /// Persist one observed handoff phase. Exact retries of the currently
    /// committed checkpoint are idempotent and never append another record.
    pub fn advance(
        &mut self,
        step: WriterHandoffAdvanceV1,
    ) -> Result<WriterHandoffCheckpointV1, WriterHandoffErrorV1> {
        if self.poisoned {
            return Err(WriterHandoffErrorV1::Poisoned);
        }
        if step.phase == self.checkpoint.phase
            && step.evidence_digest == self.checkpoint.evidence_digest
            && step.outbox_watermark == self.checkpoint.outbox_watermark
            && step.unknown_effect_count == self.checkpoint.unknown_effect_count
        {
            return Ok(self.checkpoint.clone());
        }
        let next = next_checkpoint(&self.checkpoint, step)?;
        let record = encode_checkpoint(&next)?;
        let next_length = self
            .durable_length
            .checked_add(record.len() as u64 + 1)
            .ok_or(WriterHandoffErrorV1::JournalTooLarge)?;
        if next_length > MAX_JOURNAL_BYTES {
            return Err(WriterHandoffErrorV1::JournalTooLarge);
        }
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(WriterHandoffErrorV1::Corrupt);
        }
        self.file
            .write_all(&record)
            .and_then(|()| self.file.write_all(b"\n"))
            .and_then(|()| self.file.sync_all())
            .map_err(|_| WriterHandoffErrorV1::Indeterminate)?;
        self.durable_length = next_length;
        self.checkpoint = next.clone();
        self.poisoned = false;
        Ok(next)
    }
}

fn next_checkpoint(
    current: &WriterHandoffCheckpointV1,
    step: WriterHandoffAdvanceV1,
) -> Result<WriterHandoffCheckpointV1, WriterHandoffErrorV1> {
    current.plan.validate()?;
    if current.phase.is_terminal() {
        return Err(WriterHandoffErrorV1::InvalidTransition {
            from: current.phase,
            to: step.phase,
        });
    }
    if step.evidence_digest.is_zero() {
        return Err(WriterHandoffErrorV1::EmptyDigest("handoff evidence"));
    }
    if !valid_transition(current.phase, step.phase) {
        return Err(WriterHandoffErrorV1::InvalidTransition {
            from: current.phase,
            to: step.phase,
        });
    }

    let mut outbox_watermark = current.outbox_watermark;
    if step.phase == WriterHandoffPhaseV1::Drained {
        let watermark = step
            .outbox_watermark
            .ok_or(WriterHandoffErrorV1::MissingOutboxWatermark)?;
        if step.unknown_effect_count != 0 {
            return Err(WriterHandoffErrorV1::UnknownEffectsRemain(
                step.unknown_effect_count,
            ));
        }
        outbox_watermark = Some(watermark);
    } else if current.phase.at_or_after_drained() && step.phase != WriterHandoffPhaseV1::Quarantined
    {
        if step.unknown_effect_count != 0 {
            return Err(WriterHandoffErrorV1::UnknownEffectsRemain(
                step.unknown_effect_count,
            ));
        }
        if let Some(candidate) = step.outbox_watermark
            && Some(candidate) != current.outbox_watermark
        {
            return Err(WriterHandoffErrorV1::OutboxWatermarkChanged);
        }
    } else if step.outbox_watermark.is_some() {
        return Err(WriterHandoffErrorV1::OutboxWatermarkChanged);
    }

    let revision = current
        .revision
        .checked_add(1)
        .ok_or(WriterHandoffErrorV1::Corrupt)?;
    let mut next = WriterHandoffCheckpointV1 {
        plan: current.plan.clone(),
        revision,
        phase: step.phase,
        outbox_watermark,
        unknown_effect_count: step.unknown_effect_count,
        evidence_digest: step.evidence_digest,
        previous_receipt_digest: current.receipt_digest,
        receipt_digest: Digest32::ZERO,
    };
    next.receipt_digest = checkpoint_digest(&next);
    Ok(next)
}

const fn valid_transition(from: WriterHandoffPhaseV1, to: WriterHandoffPhaseV1) -> bool {
    if to == WriterHandoffPhaseV1::Quarantined {
        return !from.is_terminal();
    }
    matches!(
        (from, to),
        (
            WriterHandoffPhaseV1::Prepared,
            WriterHandoffPhaseV1::AdmissionStopped
        ) | (
            WriterHandoffPhaseV1::AdmissionStopped,
            WriterHandoffPhaseV1::Drained
        ) | (
            WriterHandoffPhaseV1::Drained,
            WriterHandoffPhaseV1::OldWriterFenced
        ) | (
            WriterHandoffPhaseV1::OldWriterFenced,
            WriterHandoffPhaseV1::Snapshotted
        ) | (
            WriterHandoffPhaseV1::Snapshotted,
            WriterHandoffPhaseV1::Migrated
        ) | (
            WriterHandoffPhaseV1::Migrated,
            WriterHandoffPhaseV1::Validated
        ) | (
            WriterHandoffPhaseV1::Validated,
            WriterHandoffPhaseV1::NewWriterFenced
        ) | (
            WriterHandoffPhaseV1::NewWriterFenced,
            WriterHandoffPhaseV1::RoutePublished
        ) | (
            WriterHandoffPhaseV1::RoutePublished,
            WriterHandoffPhaseV1::Retired
        )
    )
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedCheckpointV1 {
    schema_version: u16,
    operation_id: String,
    domain_id: String,
    source_writer: String,
    target_writer: String,
    old_generation: u64,
    new_generation: u64,
    authority_epoch: u64,
    migration_plan_digest: String,
    schema_digest: String,
    rollback_predecessor_digest: String,
    revision: u64,
    phase: WriterHandoffPhaseV1,
    outbox_watermark: Option<u64>,
    unknown_effect_count: u32,
    evidence_digest: String,
    previous_receipt_digest: String,
    receipt_digest: String,
}

fn encode_checkpoint(
    checkpoint: &WriterHandoffCheckpointV1,
) -> Result<Vec<u8>, WriterHandoffErrorV1> {
    let persisted = PersistedCheckpointV1::from(checkpoint);
    let bytes = serde_json::to_vec(&persisted).map_err(|_| WriterHandoffErrorV1::Corrupt)?;
    if bytes.len() > MAX_RECORD_BYTES {
        return Err(WriterHandoffErrorV1::RecordTooLarge);
    }
    Ok(bytes)
}

fn decode_checkpoint(bytes: &[u8]) -> Result<WriterHandoffCheckpointV1, WriterHandoffErrorV1> {
    let persisted: PersistedCheckpointV1 =
        serde_json::from_slice(bytes).map_err(|_| WriterHandoffErrorV1::Corrupt)?;
    persisted.try_into()
}

impl From<&WriterHandoffCheckpointV1> for PersistedCheckpointV1 {
    fn from(value: &WriterHandoffCheckpointV1) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            operation_id: value.plan.operation_id.to_string(),
            domain_id: value.plan.domain_id.to_string(),
            source_writer: value.plan.source_writer.to_string(),
            target_writer: value.plan.target_writer.to_string(),
            old_generation: value.plan.old_generation.get(),
            new_generation: value.plan.new_generation.get(),
            authority_epoch: value.plan.authority_epoch,
            migration_plan_digest: value.plan.migration_plan_digest.to_string(),
            schema_digest: value.plan.schema_digest.to_string(),
            rollback_predecessor_digest: value.plan.rollback_predecessor_digest.to_string(),
            revision: value.revision,
            phase: value.phase,
            outbox_watermark: value.outbox_watermark,
            unknown_effect_count: value.unknown_effect_count,
            evidence_digest: value.evidence_digest.to_string(),
            previous_receipt_digest: value.previous_receipt_digest.to_string(),
            receipt_digest: value.receipt_digest.to_string(),
        }
    }
}

impl TryFrom<PersistedCheckpointV1> for WriterHandoffCheckpointV1 {
    type Error = WriterHandoffErrorV1;

    fn try_from(value: PersistedCheckpointV1) -> Result<Self, Self::Error> {
        if value.schema_version != SCHEMA_VERSION {
            return Err(WriterHandoffErrorV1::Corrupt);
        }
        let plan = WriterHandoffPlanV1 {
            operation_id: StableId::new(value.operation_id)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            domain_id: StableId::new(value.domain_id).map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            source_writer: StableId::new(value.source_writer)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            target_writer: StableId::new(value.target_writer)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            old_generation: Generation::new(value.old_generation)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            new_generation: Generation::new(value.new_generation)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            authority_epoch: value.authority_epoch,
            migration_plan_digest: Digest32::from_str(&value.migration_plan_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            schema_digest: Digest32::from_str(&value.schema_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            rollback_predecessor_digest: Digest32::from_str(&value.rollback_predecessor_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
        };
        plan.validate()?;
        let checkpoint = WriterHandoffCheckpointV1 {
            plan,
            revision: value.revision,
            phase: value.phase,
            outbox_watermark: value.outbox_watermark,
            unknown_effect_count: value.unknown_effect_count,
            evidence_digest: Digest32::from_str(&value.evidence_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            previous_receipt_digest: Digest32::from_str(&value.previous_receipt_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
            receipt_digest: Digest32::from_str(&value.receipt_digest)
                .map_err(|_| WriterHandoffErrorV1::Corrupt)?,
        };
        if checkpoint.receipt_digest != checkpoint_digest(&checkpoint) {
            return Err(WriterHandoffErrorV1::Corrupt);
        }
        Ok(checkpoint)
    }
}

fn validate_recovered_checkpoint(
    previous: Option<&WriterHandoffCheckpointV1>,
    checkpoint: &WriterHandoffCheckpointV1,
) -> Result<(), WriterHandoffErrorV1> {
    checkpoint.plan.validate()?;
    if checkpoint.evidence_digest.is_zero() || checkpoint.receipt_digest.is_zero() {
        return Err(WriterHandoffErrorV1::Corrupt);
    }
    match previous {
        None => {
            if checkpoint.revision != 1
                || checkpoint.phase != WriterHandoffPhaseV1::Prepared
                || checkpoint.previous_receipt_digest != Digest32::ZERO
                || checkpoint.outbox_watermark.is_some()
                || checkpoint.unknown_effect_count != 0
            {
                return Err(WriterHandoffErrorV1::Corrupt);
            }
        }
        Some(previous) => {
            if checkpoint.plan != previous.plan
                || checkpoint.revision != previous.revision + 1
                || checkpoint.previous_receipt_digest != previous.receipt_digest
                || !valid_transition(previous.phase, checkpoint.phase)
            {
                return Err(WriterHandoffErrorV1::Corrupt);
            }
            if checkpoint.phase == WriterHandoffPhaseV1::Drained {
                if checkpoint.outbox_watermark.is_none() || checkpoint.unknown_effect_count != 0 {
                    return Err(WriterHandoffErrorV1::Corrupt);
                }
            } else if previous.phase.at_or_after_drained()
                && checkpoint.phase != WriterHandoffPhaseV1::Quarantined
                && (checkpoint.outbox_watermark != previous.outbox_watermark
                    || checkpoint.unknown_effect_count != 0)
            {
                return Err(WriterHandoffErrorV1::Corrupt);
            }
        }
    }
    Ok(())
}

fn checkpoint_digest(checkpoint: &WriterHandoffCheckpointV1) -> Digest32 {
    let mut bytes = Vec::with_capacity(512);
    bytes.extend_from_slice(b"hepta.writer-handoff.checkpoint.v1");
    push_text(&mut bytes, checkpoint.plan.operation_id.as_str());
    push_text(&mut bytes, checkpoint.plan.domain_id.as_str());
    push_text(&mut bytes, checkpoint.plan.source_writer.as_str());
    push_text(&mut bytes, checkpoint.plan.target_writer.as_str());
    bytes.extend_from_slice(&checkpoint.plan.old_generation.get().to_be_bytes());
    bytes.extend_from_slice(&checkpoint.plan.new_generation.get().to_be_bytes());
    bytes.extend_from_slice(&checkpoint.plan.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(checkpoint.plan.migration_plan_digest.as_array());
    bytes.extend_from_slice(checkpoint.plan.schema_digest.as_array());
    bytes.extend_from_slice(checkpoint.plan.rollback_predecessor_digest.as_array());
    bytes.extend_from_slice(&checkpoint.revision.to_be_bytes());
    bytes.push(checkpoint.phase.tag());
    match checkpoint.outbox_watermark {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&checkpoint.unknown_effect_count.to_be_bytes());
    bytes.extend_from_slice(checkpoint.evidence_digest.as_array());
    bytes.extend_from_slice(checkpoint.previous_receipt_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let len = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use std::fs::OpenOptions;

    use tempfile::TempDir;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn plan() -> WriterHandoffPlanV1 {
        WriterHandoffPlanV1 {
            operation_id: id("handoff.memory.v1"),
            domain_id: id("memory.cognitive"),
            source_writer: id("memory.writer"),
            target_writer: id("memory.writer"),
            old_generation: Generation::new(7).expect("generation"),
            new_generation: Generation::new(8).expect("generation"),
            authority_epoch: 11,
            migration_plan_digest: digest("migration-plan"),
            schema_digest: digest("schema"),
            rollback_predecessor_digest: digest("rollback"),
        }
    }

    fn file(temp: &TempDir) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(temp.path().join("writer-handoff.log"))
            .expect("open journal")
    }

    fn step(phase: WriterHandoffPhaseV1, label: &str) -> WriterHandoffAdvanceV1 {
        WriterHandoffAdvanceV1 {
            phase,
            evidence_digest: digest(label),
            outbox_watermark: None,
            unknown_effect_count: 0,
        }
    }

    #[test]
    fn durable_handoff_reopens_at_exact_committed_phase() {
        let temp = TempDir::new().expect("temp");
        let mut journal =
            DurableWriterHandoffJournalV1::create(file(&temp), plan()).expect("create journal");
        journal
            .advance(step(
                WriterHandoffPhaseV1::AdmissionStopped,
                "admission-stopped",
            ))
            .expect("stop admission");
        let mut drained = step(WriterHandoffPhaseV1::Drained, "drained");
        drained.outbox_watermark = Some(42);
        journal.advance(drained).expect("drain");
        journal
            .advance(step(
                WriterHandoffPhaseV1::OldWriterFenced,
                "old-writer-fenced",
            ))
            .expect("fence old writer");
        let expected = journal.checkpoint().clone();
        drop(journal);

        let recovered = DurableWriterHandoffJournalV1::recover(file(&temp)).expect("recover");
        assert_eq!(recovered.checkpoint(), &expected);
        assert!(!recovered.checkpoint().old_writer_valid());
        assert!(!recovered.checkpoint().new_writer_valid());
        assert_eq!(recovered.checkpoint().outbox_watermark, Some(42));
    }

    #[test]
    fn handoff_refuses_to_fence_before_drain_and_unknown_effects() {
        let temp = TempDir::new().expect("temp");
        let mut journal =
            DurableWriterHandoffJournalV1::create(file(&temp), plan()).expect("create journal");
        assert!(matches!(
            journal.advance(step(WriterHandoffPhaseV1::OldWriterFenced, "illegal-fence",)),
            Err(WriterHandoffErrorV1::InvalidTransition { .. })
        ));
        journal
            .advance(step(
                WriterHandoffPhaseV1::AdmissionStopped,
                "admission-stopped",
            ))
            .expect("stop admission");
        let mut drained = step(WriterHandoffPhaseV1::Drained, "drained");
        drained.outbox_watermark = Some(3);
        drained.unknown_effect_count = 1;
        assert_eq!(
            journal.advance(drained),
            Err(WriterHandoffErrorV1::UnknownEffectsRemain(1))
        );
    }

    #[test]
    fn torn_tail_is_removed_before_resume() {
        let temp = TempDir::new().expect("temp");
        let journal =
            DurableWriterHandoffJournalV1::create(file(&temp), plan()).expect("create journal");
        let expected = journal.checkpoint().clone();
        drop(journal);

        let mut raw = file(&temp);
        raw.seek(SeekFrom::End(0)).expect("seek");
        raw.write_all(b"{\"torn\":").expect("write torn tail");
        raw.sync_all().expect("sync torn tail");
        drop(raw);

        let recovered = DurableWriterHandoffJournalV1::recover(file(&temp)).expect("recover");
        assert_eq!(recovered.checkpoint(), &expected);
        let len = recovered.file.metadata().expect("metadata").len();
        assert_eq!(len, recovered.durable_length);
    }

    #[test]
    fn full_handoff_has_no_dual_writer_window() {
        let temp = TempDir::new().expect("temp");
        let mut journal =
            DurableWriterHandoffJournalV1::create(file(&temp), plan()).expect("create journal");
        for phase in [
            WriterHandoffPhaseV1::AdmissionStopped,
            WriterHandoffPhaseV1::Drained,
            WriterHandoffPhaseV1::OldWriterFenced,
            WriterHandoffPhaseV1::Snapshotted,
            WriterHandoffPhaseV1::Migrated,
            WriterHandoffPhaseV1::Validated,
            WriterHandoffPhaseV1::NewWriterFenced,
            WriterHandoffPhaseV1::RoutePublished,
            WriterHandoffPhaseV1::Retired,
        ] {
            let mut next = step(phase, &format!("{phase:?}"));
            if phase == WriterHandoffPhaseV1::Drained {
                next.outbox_watermark = Some(9);
            }
            let checkpoint = journal.advance(next).expect("advance");
            assert!(!(checkpoint.old_writer_valid() && checkpoint.new_writer_valid()));
        }
        assert_eq!(journal.checkpoint().phase, WriterHandoffPhaseV1::Retired);
        assert!(journal.checkpoint().new_writer_admission_open());
    }
}
