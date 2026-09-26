//! Crash-safe full-checkpoint file backend for final-holdout CAS state.
//!
//! Every committed frame contains one complete validated CAS record. Recovery
//! can therefore start from the latest valid checkpoint rather than replaying
//! every semantic event. A compacted file contains only the current checkpoint;
//! the independently retained minimum anchor prevents stale-backup rollback.

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
use crate::HoldoutUseDispositionV1;
use crate::HoldoutWriterFenceV1;
use crate::closure::decode_holdout_plan;
use crate::closure::encode_holdout_plan;

const MAGIC: &[u8; 8] = b"HEPTCK01";
const DOMAIN: &[u8] = b"hepta.intelligence-eval.holdout-checkpoint.v1\0";
const HEADER: usize = 72;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;
const MAX_CHECKPOINTS: usize = 100_000;
const MAX_RECORDS: usize = 100_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HoldoutCheckpointStorageMetricsV1 {
    pub file_bytes: u64,
    pub checkpoint_count: u64,
    pub holdout_record_count: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FinalHoldoutCompactionReceiptV1 {
    pub state_digest: Digest32,
    pub before_bytes: u64,
    pub after_bytes: u64,
    pub before_checkpoints: u64,
    pub after_checkpoints: u64,
    pub holdout_record_count: u64,
    pub receipt_digest: Digest32,
}

impl FinalHoldoutCompactionReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), CheckpointFileCasErrorV1> {
        if self.state_digest.is_zero()
            || self.after_checkpoints != 1
            || self.before_checkpoints < self.after_checkpoints
            || self.after_bytes > self.before_bytes
            || self.receipt_digest != compaction_receipt_digest(self)
        {
            return Err(CheckpointFileCasErrorV1::Corrupt);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CheckpointFileCasErrorV1 {
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

impl fmt::Display for CheckpointFileCasErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CheckpointFileCasErrorV1 {}

/// Append-only checkpoint store with lifetime OS-file exclusion.
pub struct LockedCheckpointFinalHoldoutCasStoreV1 {
    file: File,
    binding: Digest32,
    state: Option<FinalHoldoutCasRecordV1>,
    length: u64,
    checkpoint_count: usize,
    poisoned: bool,
}

impl LockedCheckpointFinalHoldoutCasStoreV1 {
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, CheckpointFileCasErrorV1> {
        acquire(&file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(CheckpointFileCasErrorV1::AlreadyInitialized);
        }
        let header = header(binding);
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| CheckpointFileCasErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            state: None,
            length: HEADER as u64,
            checkpoint_count: 0,
            poisoned: false,
        })
    }

    pub fn recover(
        mut file: File,
        binding: Digest32,
        minimum: Option<FinalHoldoutCasAnchorV1>,
    ) -> Result<Self, CheckpointFileCasErrorV1> {
        acquire(&file, binding)?;
        let physical_length = file.metadata().map_err(io_error)?.len();
        if physical_length > MAX_FILE_BYTES {
            return Err(CheckpointFileCasErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut file)
            .take(MAX_FILE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(io_error)?;
        if bytes.len() as u64 != physical_length {
            return Err(CheckpointFileCasErrorV1::Corrupt);
        }
        validate_header(&bytes, binding)?;

        let mut cursor = HEADER;
        let mut last_good = HEADER;
        let mut state: Option<FinalHoldoutCasRecordV1> = None;
        let mut checkpoint_count = 0_usize;
        let mut truncated_tail = false;
        while cursor < bytes.len() {
            let Some(raw_len) = bytes.get(cursor..cursor + 4) else {
                truncated_tail = true;
                break;
            };
            let count = u32::from_be_bytes(
                raw_len
                    .try_into()
                    .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?,
            ) as usize;
            if !(1..=MAX_FRAME_BYTES).contains(&count) {
                return Err(CheckpointFileCasErrorV1::Capacity);
            }
            let payload_start = cursor + 4;
            let Some(payload) = bytes.get(payload_start..payload_start + count) else {
                truncated_tail = true;
                break;
            };
            let checksum_start = payload_start + count;
            let Some(checksum) = bytes.get(checksum_start..checksum_start + 32) else {
                truncated_tail = true;
                break;
            };
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(CheckpointFileCasErrorV1::Corrupt);
            }
            let next = decode_checkpoint(binding, payload)?;
            if let Some(current) = state.as_ref() {
                validate_transition(current, &next)?;
            }
            state = Some(next);
            checkpoint_count = checkpoint_count
                .checked_add(1)
                .ok_or(CheckpointFileCasErrorV1::Capacity)?;
            if checkpoint_count > MAX_CHECKPOINTS {
                return Err(CheckpointFileCasErrorV1::Capacity);
            }
            cursor = checksum_start + 32;
            last_good = cursor;
        }

        validate_minimum(state.as_ref(), minimum)?;
        let length = if truncated_tail {
            file.set_len(last_good as u64)
                .and_then(|()| file.sync_all())
                .map_err(|_| CheckpointFileCasErrorV1::Indeterminate)?;
            last_good as u64
        } else {
            physical_length
        };
        file.sync_all()
            .map_err(|_| CheckpointFileCasErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            state,
            length,
            checkpoint_count,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn metrics(&self) -> HoldoutCheckpointStorageMetricsV1 {
        HoldoutCheckpointStorageMetricsV1 {
            file_bytes: self.length,
            checkpoint_count: self.checkpoint_count as u64,
            holdout_record_count: self
                .state
                .as_ref()
                .map_or(0, |record| record.journal.records.len() as u64),
        }
    }

    #[must_use]
    pub fn anchor(&self) -> Option<FinalHoldoutCasAnchorV1> {
        self.state.as_ref().map(record_anchor)
    }

    /// Rewrite the current authoritative state into one fresh checkpoint file.
    /// The caller must durably install the returned file/anchor as one host
    /// transaction before retiring the predecessor.
    pub fn compact_into(
        &self,
        destination: File,
    ) -> Result<
        (
            LockedCheckpointFinalHoldoutCasStoreV1,
            FinalHoldoutCompactionReceiptV1,
        ),
        CheckpointFileCasErrorV1,
    > {
        let state = self
            .state
            .as_ref()
            .ok_or(CheckpointFileCasErrorV1::Binding)?;
        let before = self.metrics();
        let mut compacted = Self::create(destination, self.binding)?;
        compacted
            .compare_and_swap(self.binding, None, state)
            .map_err(map_store_error)?;
        let after = compacted.metrics();
        let mut receipt = FinalHoldoutCompactionReceiptV1 {
            state_digest: state.state_digest,
            before_bytes: before.file_bytes,
            after_bytes: after.file_bytes,
            before_checkpoints: before.checkpoint_count,
            after_checkpoints: after.checkpoint_count,
            holdout_record_count: after.holdout_record_count,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = compaction_receipt_digest(&receipt);
        receipt.validate_integrity()?;
        Ok((compacted, receipt))
    }

    #[must_use]
    pub fn into_file(self) -> File {
        self.file
    }
}

impl FinalHoldoutCasStoreV1 for LockedCheckpointFinalHoldoutCasStoreV1 {
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
        if let Some(current) = self.state.as_ref() {
            validate_transition(current, next).map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        }
        if self.checkpoint_count >= MAX_CHECKPOINTS {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        let payload = encode_checkpoint(next).map_err(|_| FinalHoldoutCasStoreError::Rejected)?;
        if payload.len() > MAX_FRAME_BYTES {
            return Err(FinalHoldoutCasStoreError::Rejected);
        }
        let next_length = self
            .length
            .checked_add(4)
            .and_then(|value| value.checked_add(payload.len() as u64))
            .and_then(|value| value.checked_add(32))
            .filter(|value| *value <= MAX_FILE_BYTES)
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
        self.state = Some(next.clone());
        self.length = next_length;
        self.checkpoint_count += 1;
        Ok(())
    }
}

fn encode_checkpoint(record: &FinalHoldoutCasRecordV1) -> Result<Vec<u8>, CheckpointFileCasErrorV1> {
    record
        .validate(record.binding)
        .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
    if record.journal.records.len() > MAX_RECORDS {
        return Err(CheckpointFileCasErrorV1::Capacity);
    }
    let owner = record.fence.owner_id.as_str().as_bytes();
    let owner_len = u16::try_from(owner.len()).map_err(|_| CheckpointFileCasErrorV1::Capacity)?;
    let record_count = u32::try_from(record.journal.records.len())
        .map_err(|_| CheckpointFileCasErrorV1::Capacity)?;
    let mut bytes = DOMAIN.to_vec();
    bytes.extend_from_slice(record.binding.as_array());
    bytes.extend_from_slice(&owner_len.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&record.fence.generation.to_be_bytes());
    bytes.extend_from_slice(record.fence.lease_digest.as_array());
    bytes.extend_from_slice(&record_count.to_be_bytes());
    for row in &record.journal.records {
        let plan = encode_holdout_plan(&row.plan)
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
        let plan_len = u32::try_from(plan.len()).map_err(|_| CheckpointFileCasErrorV1::Capacity)?;
        bytes.extend_from_slice(&plan_len.to_be_bytes());
        bytes.extend_from_slice(&plan);
    }
    bytes.extend_from_slice(record.journal.head_digest.as_array());
    bytes.extend_from_slice(record.state_digest.as_array());
    Ok(bytes)
}

fn decode_checkpoint(
    binding: Digest32,
    mut bytes: &[u8],
) -> Result<FinalHoldoutCasRecordV1, CheckpointFileCasErrorV1> {
    if take(&mut bytes, DOMAIN.len())? != DOMAIN {
        return Err(CheckpointFileCasErrorV1::Corrupt);
    }
    let encoded_binding = digest_from(take(&mut bytes, 32)?)?;
    if encoded_binding != binding {
        return Err(CheckpointFileCasErrorV1::Binding);
    }
    let owner_len_raw = take(&mut bytes, 2)?;
    let owner_len = usize::from(u16::from_be_bytes([owner_len_raw[0], owner_len_raw[1]]));
    let owner = std::str::from_utf8(take(&mut bytes, owner_len)?)
        .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
    let owner_id = StableId::new(owner).map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
    let generation = u64::from_be_bytes(
        take(&mut bytes, 8)?
            .try_into()
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?,
    );
    let lease_digest = digest_from(take(&mut bytes, 32)?)?;
    if generation == 0 || lease_digest.is_zero() {
        return Err(CheckpointFileCasErrorV1::Corrupt);
    }
    let count = u32::from_be_bytes(
        take(&mut bytes, 4)?
            .try_into()
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?,
    ) as usize;
    if count > MAX_RECORDS {
        return Err(CheckpointFileCasErrorV1::Capacity);
    }
    let mut journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
        .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
    for _ in 0..count {
        let plan_len = u32::from_be_bytes(
            take(&mut bytes, 4)?
                .try_into()
                .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?,
        ) as usize;
        let plan = decode_holdout_plan(take(&mut bytes, plan_len)?)
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
        let receipt = journal
            .consume(journal.head_digest(), &plan)
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
        if receipt.disposition != HoldoutUseDispositionV1::Recorded {
            return Err(CheckpointFileCasErrorV1::Corrupt);
        }
    }
    let expected_head = digest_from(take(&mut bytes, 32)?)?;
    let expected_state = digest_from(take(&mut bytes, 32)?)?;
    if !bytes.is_empty() || journal.head_digest() != expected_head {
        return Err(CheckpointFileCasErrorV1::Corrupt);
    }
    let record = FinalHoldoutCasRecordV1::new(
        binding,
        HoldoutWriterFenceV1 {
            owner_id,
            generation,
            lease_digest,
        },
        journal.snapshot(),
    )
    .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?;
    if record.state_digest != expected_state {
        return Err(CheckpointFileCasErrorV1::Corrupt);
    }
    Ok(record)
}

fn validate_transition(
    current: &FinalHoldoutCasRecordV1,
    next: &FinalHoldoutCasRecordV1,
) -> Result<(), CheckpointFileCasErrorV1> {
    if current.binding != next.binding {
        return Err(CheckpointFileCasErrorV1::Binding);
    }
    if current.journal == next.journal {
        if next.fence.generation <= current.fence.generation {
            return Err(CheckpointFileCasErrorV1::Rollback);
        }
        return Ok(());
    }
    if current.fence == next.fence
        && next.journal.records.len() == current.journal.records.len() + 1
        && next.journal.records[..current.journal.records.len()]
            == current.journal.records[..]
    {
        return Ok(());
    }
    Err(CheckpointFileCasErrorV1::Corrupt)
}

fn validate_minimum(
    state: Option<&FinalHoldoutCasRecordV1>,
    minimum: Option<FinalHoldoutCasAnchorV1>,
) -> Result<(), CheckpointFileCasErrorV1> {
    let Some(minimum) = minimum else {
        return Ok(());
    };
    let state = state.ok_or(CheckpointFileCasErrorV1::Rollback)?;
    let current = record_anchor(state);
    if current.fence_generation < minimum.fence_generation
        || current.record_count < minimum.record_count
        || (current.fence_generation == minimum.fence_generation
            && current.record_count == minimum.record_count
            && current.state_digest != minimum.state_digest)
    {
        return Err(CheckpointFileCasErrorV1::Rollback);
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

fn header(binding: Digest32) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    bytes
}

fn validate_header(bytes: &[u8], binding: Digest32) -> Result<(), CheckpointFileCasErrorV1> {
    if bytes.len() < HEADER {
        return Err(CheckpointFileCasErrorV1::MissingHeader);
    }
    if &bytes[..8] != MAGIC
        || &bytes[8..40] != binding.as_array()
        || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
    {
        return Err(CheckpointFileCasErrorV1::Corrupt);
    }
    Ok(())
}

fn compaction_receipt_digest(receipt: &FinalHoldoutCompactionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.holdout-compaction-receipt.v1\0".to_vec();
    bytes.extend_from_slice(receipt.state_digest.as_array());
    for value in [
        receipt.before_bytes,
        receipt.after_bytes,
        receipt.before_checkpoints,
        receipt.after_checkpoints,
        receipt.holdout_record_count,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn take<'a>(
    bytes: &mut &'a [u8],
    count: usize,
) -> Result<&'a [u8], CheckpointFileCasErrorV1> {
    let (head, tail) = bytes
        .split_at_checked(count)
        .ok_or(CheckpointFileCasErrorV1::Corrupt)?;
    *bytes = tail;
    Ok(head)
}

fn digest_from(bytes: &[u8]) -> Result<Digest32, CheckpointFileCasErrorV1> {
    Ok(Digest32::from_array(
        bytes
            .try_into()
            .map_err(|_| CheckpointFileCasErrorV1::Corrupt)?,
    ))
}

fn acquire(file: &File, binding: Digest32) -> Result<(), CheckpointFileCasErrorV1> {
    if binding.is_zero() {
        return Err(CheckpointFileCasErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(CheckpointFileCasErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => CheckpointFileCasErrorV1::Busy,
        TryLockError::Error(error) => CheckpointFileCasErrorV1::Io(error.kind()),
    })
}

fn map_store_error(error: FinalHoldoutCasStoreError) -> CheckpointFileCasErrorV1 {
    match error {
        FinalHoldoutCasStoreError::Conflict | FinalHoldoutCasStoreError::Rejected => {
            CheckpointFileCasErrorV1::Corrupt
        }
        FinalHoldoutCasStoreError::Indeterminate => CheckpointFileCasErrorV1::Indeterminate,
    }
}

fn io_error(error: io::Error) -> CheckpointFileCasErrorV1 {
    CheckpointFileCasErrorV1::Io(error.kind())
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::time::Instant;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("test id")
    }

    fn temp_file(label: &str) -> (PathBuf, File) {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-learning-eval-{label}-{}-{nonce}.checkpoint",
            std::process::id()
        ));
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&path)
            .expect("create temp checkpoint");
        (path, file)
    }

    fn empty_record(binding: Digest32, generation: u64) -> FinalHoldoutCasRecordV1 {
        let journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS).expect("journal");
        FinalHoldoutCasRecordV1::new(
            binding,
            HoldoutWriterFenceV1 {
                owner_id: id("owner"),
                generation,
                lease_digest: digest(&format!("lease-{generation}")),
            },
            journal.snapshot(),
        )
        .expect("record")
    }

    #[test]
    fn checkpoint_recovery_and_compaction_preserve_exact_state() {
        let binding = digest("binding");
        let (source_path, source_file) = temp_file("source");
        let mut store =
            LockedCheckpointFinalHoldoutCasStoreV1::create(source_file, binding).expect("create");
        let mut expected = None;
        for generation in 1..=32 {
            let record = empty_record(binding, generation);
            store
                .compare_and_swap(binding, expected, &record)
                .expect("checkpoint");
            expected = Some(record.state_digest);
        }
        let before = store.metrics();
        let minimum = store.anchor().expect("anchor");
        let (compact_path, compact_file) = temp_file("compact");
        let (compacted, receipt) = store.compact_into(compact_file).expect("compact");
        receipt.validate_integrity().expect("receipt");
        assert_eq!(compacted.anchor(), Some(minimum));
        assert_eq!(compacted.metrics().checkpoint_count, 1);
        assert!(compacted.metrics().file_bytes < before.file_bytes);
        drop(compacted);
        let recovered_file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&compact_path)
            .expect("open compacted");
        let recovered = LockedCheckpointFinalHoldoutCasStoreV1::recover(
            recovered_file,
            binding,
            Some(minimum),
        )
        .expect("recover compacted");
        assert_eq!(recovered.anchor(), Some(minimum));
        drop(recovered);
        drop(store);
        fs::remove_file(source_path).expect("remove source");
        fs::remove_file(compact_path).expect("remove compact");
    }

    #[test]
    fn truncated_uncommitted_tail_is_removed_without_losing_acknowledged_anchor() {
        let binding = digest("binding");
        let (path, file) = temp_file("truncated");
        let mut store =
            LockedCheckpointFinalHoldoutCasStoreV1::create(file, binding).expect("create");
        let record = empty_record(binding, 1);
        store
            .compare_and_swap(binding, None, &record)
            .expect("checkpoint");
        let minimum = store.anchor().expect("anchor");
        drop(store);
        let mut append = OpenOptions::new()
            .append(true)
            .open(&path)
            .expect("append");
        append.write_all(&4096_u32.to_be_bytes()).expect("length");
        append.write_all(b"partial").expect("partial");
        append.sync_all().expect("sync partial");
        drop(append);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        let recovered = LockedCheckpointFinalHoldoutCasStoreV1::recover(
            file,
            binding,
            Some(minimum),
        )
        .expect("recover");
        assert_eq!(recovered.anchor(), Some(minimum));
        assert_eq!(recovered.metrics().checkpoint_count, 1);
        drop(recovered);
        fs::remove_file(path).expect("remove");
    }

    #[test]
    fn retained_anchor_rejects_stale_compacted_backup() {
        let binding = digest("binding");
        let (path, file) = temp_file("rollback");
        let mut store =
            LockedCheckpointFinalHoldoutCasStoreV1::create(file, binding).expect("create");
        let first = empty_record(binding, 1);
        store
            .compare_and_swap(binding, None, &first)
            .expect("first");
        let first_bytes = fs::read(&path).expect("backup");
        let second = empty_record(binding, 2);
        store
            .compare_and_swap(binding, Some(first.state_digest), &second)
            .expect("second");
        let minimum = store.anchor().expect("minimum");
        drop(store);
        fs::write(&path, first_bytes).expect("restore stale backup");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        assert!(matches!(
            LockedCheckpointFinalHoldoutCasStoreV1::recover(file, binding, Some(minimum)),
            Err(CheckpointFileCasErrorV1::Rollback)
        ));
        fs::remove_file(path).expect("remove");
    }

    #[test]
    #[ignore = "maximum checkpoint recovery qualification"]
    fn maximum_checkpoint_recovery_capacity_profile() {
        let binding = digest("capacity-binding");
        let (path, mut file) = temp_file("capacity");
        let mut bytes = header(binding);
        let journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS).expect("journal");
        let snapshot = journal.snapshot();
        for generation in 1..=MAX_CHECKPOINTS as u64 {
            let record = FinalHoldoutCasRecordV1::new(
                binding,
                HoldoutWriterFenceV1 {
                    owner_id: id("capacity-owner"),
                    generation,
                    lease_digest: digest(&format!("capacity-lease-{generation}")),
                },
                snapshot.clone(),
            )
            .expect("record");
            let payload = encode_checkpoint(&record).expect("encode");
            bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
            bytes.extend_from_slice(&payload);
            bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        }
        assert!((bytes.len() as u64) <= MAX_FILE_BYTES);
        file.write_all(&bytes).expect("write capacity fixture");
        file.sync_all().expect("sync fixture");
        drop(file);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .expect("reopen");
        let started = Instant::now();
        let recovered =
            LockedCheckpointFinalHoldoutCasStoreV1::recover(file, binding, None).expect("recover");
        let elapsed_millis = started.elapsed().as_millis();
        let metrics = recovered.metrics();
        println!(
            "HEPTA_CHECKPOINT_CAPACITY_JSON={{\"schema\":\"hepta.learning-eval.checkpoint-capacity.v1\",\"checkpoints\":{},\"fileBytes\":{},\"recoveryMillis\":{},\"maximumFileBytes\":{}}}",
            metrics.checkpoint_count,
            metrics.file_bytes,
            elapsed_millis,
            MAX_FILE_BYTES
        );
        assert_eq!(metrics.checkpoint_count, MAX_CHECKPOINTS as u64);
        assert!(elapsed_millis < 60_000);
        drop(recovered);
        fs::remove_file(path).expect("remove");
    }
}
