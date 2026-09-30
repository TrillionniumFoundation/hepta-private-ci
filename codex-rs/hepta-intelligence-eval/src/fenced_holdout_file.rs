//! Concrete locked-file CAS backend for the fenced final-holdout owner.
//!
//! One process keeps an exclusive OS file lock for the lifetime of this store.
//! On a shared filesystem whose locks and fsync are linearizable across hosts,
//! the same format can coordinate host failover. Recovery accepts an
//! independently retained minimum anchor and fails closed on rollback.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutCasRecordV1;
use crate::FinalHoldoutCasStoreError;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalV1;
use crate::HoldoutWriterFenceV1;
use crate::closure::decode_holdout_plan;
use crate::closure::encode_holdout_plan;

const MAGIC: &[u8; 8] = b"HEPTFC01";
const HEADER: usize = 72;
const MAX_BYTES: u64 = 32 * 1024 * 1024;
const MAX_FRAME: usize = 4096;
const MAX_RECORDS: usize = 1_000_000;
const EVENT_FENCE: u8 = 0;
const EVENT_PLAN: u8 = 1;

#[path = "fenced_holdout_replay.rs"]
mod replay;
use replay::replay_event;
use replay::transition_payload;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LockedFileCasErrorV1 {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    MissingHeader,
    Corrupt,
    Rollback,
    Capacity,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for LockedFileCasErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LockedFileCasErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LockedFileCasCapacityV1 {
    pub bytes_used: u64,
    pub bytes_limit: u64,
    pub bytes_remaining: u64,
    pub record_count: u64,
    pub record_limit: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LockedFileCasCompactionReceiptV1 {
    pub binding: Digest32,
    pub before_bytes: u64,
    pub after_bytes: u64,
    pub record_count: u64,
    pub fence_generation: u64,
    pub state_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl LockedFileCasCompactionReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), LockedFileCasErrorV1> {
        if self.binding.is_zero()
            || self.after_bytes < HEADER as u64
            || self.after_bytes > self.before_bytes
            || self.receipt_digest.is_zero()
            || self.receipt_digest != compaction_receipt_digest(self)
        {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        if self.fence_generation == 0 {
            if self.record_count != 0 || !self.state_digest.is_zero() {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
        } else if self.state_digest.is_zero() {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        Ok(())
    }
}

pub struct LockedFileFinalHoldoutCasStoreV1 {
    file: File,
    binding: Digest32,
    state: Option<FinalHoldoutCasRecordV1>,
    journal: FinalHoldoutJournalV1,
    length: u64,
    poisoned: bool,
}

impl LockedFileFinalHoldoutCasStoreV1 {
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, LockedFileCasErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(LockedFileCasErrorV1::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| LockedFileCasErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            state: None,
            journal: FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
                .map_err(|_| LockedFileCasErrorV1::Capacity)?,
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(
        mut file: File,
        binding: Digest32,
        minimum: Option<FinalHoldoutCasAnchorV1>,
    ) -> Result<Self, LockedFileCasErrorV1> {
        acquire(&file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != length {
            return Err(LockedFileCasErrorV1::Corrupt);
        }
        if bytes.len() < HEADER {
            return Err(LockedFileCasErrorV1::MissingHeader);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
        {
            return Err(LockedFileCasErrorV1::Corrupt);
        }

        let mut state: Option<FinalHoldoutCasRecordV1> = None;
        let mut journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
            .map_err(|_| LockedFileCasErrorV1::Capacity)?;
        let mut minimum_witnessed = minimum.is_none();
        let mut cursor = HEADER;
        while cursor < bytes.len() {
            let raw = bytes
                .get(cursor..cursor + 4)
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
            if !(1..=MAX_FRAME).contains(&count) {
                return Err(LockedFileCasErrorV1::Capacity);
            }
            cursor += 4;
            let payload = bytes
                .get(cursor..cursor + count)
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            cursor += count;
            let checksum = bytes
                .get(cursor..cursor + 32)
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            cursor += 32;
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            state = Some(replay_event(
                binding,
                state.as_ref(),
                &mut journal,
                payload,
            )?);
            if minimum.is_some_and(|anchor| {
                state
                    .as_ref()
                    .is_some_and(|record| record_anchor(record) == anchor)
            }) {
                minimum_witnessed = true;
            }
        }
        validate_minimum(state.as_ref(), minimum, minimum_witnessed)?;
        file.sync_all()
            .map_err(|_| LockedFileCasErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            state,
            journal,
            length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> Option<FinalHoldoutCasAnchorV1> {
        self.state.as_ref().map(record_anchor)
    }

    #[must_use]
    pub const fn byte_len(&self) -> u64 {
        self.length
    }

    #[must_use]
    pub fn capacity(&self) -> LockedFileCasCapacityV1 {
        let record_count = self
            .state
            .as_ref()
            .map_or(0, |record| record.journal.records.len() as u64);
        LockedFileCasCapacityV1 {
            bytes_used: self.length,
            bytes_limit: MAX_BYTES,
            bytes_remaining: MAX_BYTES.saturating_sub(self.length),
            record_count,
            record_limit: MAX_RECORDS as u64,
        }
    }

    /// Rewrite the current authoritative state into a new empty file.
    ///
    /// Compaction never mutates or truncates the source file. It drops obsolete
    /// historical fence transitions, preserves every final-holdout plan record,
    /// replays them through the normal CAS path and proves the final state digest
    /// and anchor are identical before returning the compacted store.
    pub fn compact_into(
        &mut self,
        target: File,
    ) -> Result<(Self, LockedFileCasCompactionReceiptV1), LockedFileCasErrorV1> {
        if self.poisoned {
            return Err(LockedFileCasErrorV1::Indeterminate);
        }
        if self
            .file
            .metadata()
            .map_err(|_| LockedFileCasErrorV1::Indeterminate)?
            .len()
            != self.length
        {
            self.poisoned = true;
            return Err(LockedFileCasErrorV1::Indeterminate);
        }
        let before_bytes = self.length;
        let source_state = self.state.clone();
        let mut compacted = Self::create(target, self.binding)?;

        if let Some(source) = source_state.as_ref() {
            let mut journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let initial = FinalHoldoutCasRecordV1::new(
                self.binding,
                source.fence.clone(),
                journal.snapshot(),
            )
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            compacted
                .compare_and_swap(self.binding, None, &initial)
                .map_err(map_store_error)?;
            let mut current_digest = initial.state_digest;
            for source_record in &source.journal.records {
                let receipt = journal
                    .consume(journal.head_digest(), &source_record.plan)
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
                let replayed_record = journal
                    .records()
                    .last()
                    .ok_or(LockedFileCasErrorV1::Corrupt)?;
                if receipt.disposition != crate::HoldoutUseDispositionV1::Recorded
                    || replayed_record != source_record
                {
                    return Err(LockedFileCasErrorV1::Corrupt);
                }
                let next = FinalHoldoutCasRecordV1::new(
                    self.binding,
                    source.fence.clone(),
                    journal.snapshot(),
                )
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
                compacted
                    .compare_and_swap(self.binding, Some(current_digest), &next)
                    .map_err(map_store_error)?;
                current_digest = next.state_digest;
            }
            let compacted_state = compacted
                .load(self.binding)
                .map_err(map_store_error)?
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            if &compacted_state != source || compacted.anchor() != self.anchor() {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
        }

        let record_count = source_state
            .as_ref()
            .map_or(0, |record| record.journal.records.len() as u64);
        let fence_generation = source_state
            .as_ref()
            .map_or(0, |record| record.fence.generation);
        let state_digest = source_state
            .as_ref()
            .map_or(Digest32::ZERO, |record| record.state_digest);
        let mut receipt = LockedFileCasCompactionReceiptV1 {
            binding: self.binding,
            before_bytes,
            after_bytes: compacted.length,
            record_count,
            fence_generation,
            state_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = compaction_receipt_digest(&receipt);
        receipt.validate_integrity()?;
        Ok((compacted, receipt))
    }
}

impl FinalHoldoutCasStoreV1 for LockedFileFinalHoldoutCasStoreV1 {
    fn canonical_journal_cache(&self, binding: Digest32) -> Option<FinalHoldoutJournalV1> {
        if self.poisoned || binding != self.binding || self.state.is_none() {
            return None;
        }
        Some(self.journal.clone())
    }

    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        if self.poisoned {
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        if binding != self.binding {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        if self
            .file
            .metadata()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?
            .len()
            != self.length
        {
            self.poisoned = true;
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        Ok(self.state.clone())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        if self.poisoned {
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        if binding != self.binding || next.binding != binding {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        if self
            .file
            .metadata()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?
            .len()
            != self.length
        {
            self.poisoned = true;
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        next.validate(binding)
            .map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        let current_digest = self.state.as_ref().map(|record| record.state_digest);
        if current_digest != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        if self.state.as_ref().is_some_and(|current| current == next) {
            return Ok(());
        }
        let payload = transition_payload(self.state.as_ref(), next)
            .map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        if payload.len() > MAX_FRAME {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        // Public record fields are not proof that the journal transition is
        // canonical. Persist only the exact state that these bytes will replay.
        let mut candidate = self.journal.clone();
        let replayed = replay_event(binding, self.state.as_ref(), &mut candidate, &payload)
            .map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        if &replayed != next {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        let next_length = self
            .length
            .checked_add(4)
            .and_then(|value| value.checked_add(payload.len() as u64))
            .and_then(|value| value.checked_add(32))
            .filter(|value| *value <= MAX_BYTES)
            .ok_or(FinalHoldoutCasStoreError::Rejected)?;
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(&payload);
        frame.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        let write = self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all());
        if write.is_err() {
            self.poisoned = true;
            return Err(FinalHoldoutCasStoreError::Indeterminate);
        }
        self.state = Some(replayed);
        self.journal = candidate;
        self.length = next_length;
        Ok(())
    }
}

fn validate_minimum(
    state: Option<&FinalHoldoutCasRecordV1>,
    minimum: Option<FinalHoldoutCasAnchorV1>,
    witnessed: bool,
) -> Result<(), LockedFileCasErrorV1> {
    let Some(minimum) = minimum else {
        return Ok(());
    };
    let state = state.ok_or(LockedFileCasErrorV1::Rollback)?;
    let current = record_anchor(state);
    if !witnessed
        || current.fence_generation < minimum.fence_generation
        || current.record_count < minimum.record_count
    {
        return Err(LockedFileCasErrorV1::Rollback);
    }
    Ok(())
}

fn record_anchor(record: &FinalHoldoutCasRecordV1) -> FinalHoldoutCasAnchorV1 {
    FinalHoldoutCasAnchorV1 {
        fence_generation: record.fence.generation,
        record_count: record.journal.records.len() as u64,
        state_digest: record.state_digest,
    }
}

fn compaction_receipt_digest(receipt: &LockedFileCasCompactionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.holdout-compaction.v1".to_vec();
    bytes.extend_from_slice(receipt.binding.as_array());
    bytes.extend_from_slice(&receipt.before_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.after_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.record_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.fence_generation.to_be_bytes());
    bytes.extend_from_slice(receipt.state_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn map_store_error(error: FinalHoldoutCasStoreError) -> LockedFileCasErrorV1 {
    match error {
        FinalHoldoutCasStoreError::Conflict | FinalHoldoutCasStoreError::Rejected => {
            LockedFileCasErrorV1::Corrupt
        }
        FinalHoldoutCasStoreError::Indeterminate => LockedFileCasErrorV1::Indeterminate,
    }
}

fn acquire(file: &File, binding: Digest32) -> Result<(), LockedFileCasErrorV1> {
    if binding.is_zero() {
        return Err(LockedFileCasErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(LockedFileCasErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => LockedFileCasErrorV1::Busy,
        TryLockError::Error(error) => LockedFileCasErrorV1::Io(error.kind()),
    })
}

fn io_error(error: io::Error) -> LockedFileCasErrorV1 {
    LockedFileCasErrorV1::Io(error.kind())
}

#[cfg(test)]
mod compaction_tests {
    use super::*;
    use tempfile::NamedTempFile;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn compaction_drops_obsolete_fences_and_preserves_final_anchor() {
        let source_file = NamedTempFile::new().expect("source file");
        let target_file = NamedTempFile::new().expect("target file");
        let binding = digest("compaction-binding");
        let mut source = LockedFileFinalHoldoutCasStoreV1::create(
            source_file.reopen().expect("open source"),
            binding,
        )
        .expect("create source");
        let journal = FinalHoldoutJournalV1::with_record_limit(8).expect("journal");
        let first = FinalHoldoutCasRecordV1::new(
            binding,
            HoldoutWriterFenceV1 {
                owner_id: id("owner-a"),
                generation: 1,
                lease_digest: digest("lease-a"),
            },
            journal.snapshot(),
        )
        .expect("first record");
        source
            .compare_and_swap(binding, None, &first)
            .expect("first fence");
        let second = FinalHoldoutCasRecordV1::new(
            binding,
            HoldoutWriterFenceV1 {
                owner_id: id("owner-b"),
                generation: 2,
                lease_digest: digest("lease-b"),
            },
            journal.snapshot(),
        )
        .expect("second record");
        source
            .compare_and_swap(binding, Some(first.state_digest), &second)
            .expect("takeover fence");
        let source_anchor = source.anchor().expect("source anchor");
        let before = source.byte_len();

        let (compacted, receipt) = source
            .compact_into(target_file.reopen().expect("open target"))
            .expect("compact");
        assert!(receipt.after_bytes < receipt.before_bytes);
        assert_eq!(receipt.before_bytes, before);
        assert_eq!(compacted.anchor(), Some(source_anchor));
        assert_eq!(receipt.state_digest, source_anchor.state_digest);
        receipt.validate_integrity().expect("receipt integrity");
        let compacted_len = compacted.byte_len();
        drop(compacted);

        let recovered = LockedFileFinalHoldoutCasStoreV1::recover(
            target_file.reopen().expect("reopen target"),
            binding,
            Some(source_anchor),
        )
        .expect("recover compacted");
        assert_eq!(recovered.byte_len(), compacted_len);
        assert_eq!(recovered.anchor(), Some(source_anchor));
    }
}

#[cfg(test)]
#[path = "fenced_holdout_file_tests.rs"]
mod tests;
