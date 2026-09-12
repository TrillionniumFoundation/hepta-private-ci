//! Durable owner adapter for the existing final-holdout semantic journal.
//!
//! The host supplies an authorized regular file and an independently retained,
//! authenticated anchor. It owns directory durability and currentness. File
//! locks serialize cooperating owners, not hostile writers or cloned handles.
use std::error::Error;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::io::{self};

use crate::CrossFoldPlanReceiptV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutJournalV1;
use crate::HoldoutUseDispositionV1;
use crate::closure::decode_holdout_plan;
use crate::closure::encode_holdout_plan;
use codex_hepta_types::Digest32;

const MAGIC: &[u8; 8] = b"HEPTHO01";
const HEADER: usize = 72;
const MAX_BYTES: u64 = 16 * 1024 * 1024;
const MAX_FRAME: usize = 2048;
const MAX_RECORDS: usize = 8192;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HoldoutAnchorV1 {
    pub sequence: u64,
    pub head: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableHoldoutError {
    Binding,
    NotRegular,
    Busy,
    AlreadyInitialized,
    MissingHeader,
    Corrupt,
    MissingAcknowledgedHistory,
    Conflict,
    Capacity,
    Semantic,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}
impl fmt::Display for DurableHoldoutError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for DurableHoldoutError {}
impl From<io::Error> for DurableHoldoutError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

pub struct DurableFinalHoldoutJournalV1 {
    file: File,
    journal: FinalHoldoutJournalV1,
    length: u64,
    poisoned: bool,
}
impl DurableFinalHoldoutJournalV1 {
    /// Explicit initialization only; never use creation as a recovery fallback.
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, DurableHoldoutError> {
        acquire(&file, binding)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableHoldoutError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableHoldoutError::Indeterminate)?;
        Ok(Self {
            file,
            journal: FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
                .map_err(|_| DurableHoldoutError::Capacity)?,
            length: HEADER as u64,
            poisoned: false,
        })
    }

    /// Replay without trimming, recreating or inferring an anchor from this file.
    /// The minimum anchor must survive independently of backups of this store.
    pub fn recover(
        mut file: File,
        binding: Digest32,
        minimum: HoldoutAnchorV1,
    ) -> Result<Self, DurableHoldoutError> {
        acquire(&file, binding)?;
        if (minimum.sequence == 0) != minimum.head.is_zero()
            || minimum.sequence > MAX_RECORDS as u64
        {
            return Err(DurableHoldoutError::Binding);
        }
        let length = file.metadata()?.len();
        if length > MAX_BYTES {
            return Err(DurableHoldoutError::Capacity);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        (&mut file).take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != length {
            return Err(DurableHoldoutError::Corrupt);
        }
        if bytes.len() < HEADER {
            return Err(DurableHoldoutError::MissingHeader);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()
        {
            return Err(DurableHoldoutError::Corrupt);
        }
        let mut journal = FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
            .map_err(|_| DurableHoldoutError::Capacity)?;
        let mut cursor = HEADER;
        let mut witnessed = minimum.sequence == 0;
        while cursor < bytes.len() {
            let raw = bytes
                .get(cursor..cursor + 4)
                .ok_or(DurableHoldoutError::Corrupt)?;
            let count = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]) as usize;
            if !(1..=MAX_FRAME).contains(&count) {
                return Err(DurableHoldoutError::Capacity);
            }
            cursor += 4;
            let payload = bytes
                .get(cursor..cursor + count)
                .ok_or(DurableHoldoutError::Corrupt)?;
            cursor += count;
            let checksum = bytes
                .get(cursor..cursor + 32)
                .ok_or(DurableHoldoutError::Corrupt)?;
            cursor += 32;
            if checksum != Digest32::of_bytes(payload).as_array() {
                return Err(DurableHoldoutError::Corrupt);
            }
            let plan = decode_holdout_plan(payload).map_err(|_| DurableHoldoutError::Corrupt)?;
            let receipt = journal
                .consume(journal.head_digest(), &plan)
                .map_err(|_| DurableHoldoutError::Corrupt)?;
            if receipt.disposition != HoldoutUseDispositionV1::Recorded {
                return Err(DurableHoldoutError::Corrupt);
            }
            if receipt.sequence == minimum.sequence {
                if receipt.head_digest != minimum.head {
                    return Err(DurableHoldoutError::MissingAcknowledgedHistory);
                }
                witnessed = true;
            }
        }
        if !witnessed {
            return Err(DurableHoldoutError::MissingAcknowledgedHistory);
        }
        file.sync_all()
            .map_err(|_| DurableHoldoutError::Indeterminate)?;
        Ok(Self {
            file,
            journal,
            length,
            poisoned: false,
        })
    }

    /// Sync consumption before exposing it. The host must retain the resulting
    /// anchor independently BEFORE releasing confirmatory labels or acknowledging
    /// use externally. Repeating an identical plan never appends another record.
    pub fn consume(
        &mut self,
        expected: HoldoutAnchorV1,
        plan: &CrossFoldPlanReceiptV1,
    ) -> Result<FinalHoldoutJournalReceiptV1, DurableHoldoutError> {
        if self.poisoned {
            return Err(DurableHoldoutError::Poisoned);
        }
        if expected != self.anchor() {
            return Err(DurableHoldoutError::Conflict);
        }
        if self.file.metadata()?.len() != self.length {
            self.poisoned = true;
            return Err(DurableHoldoutError::Indeterminate);
        }
        let mut candidate = self.journal.clone();
        let receipt = candidate
            .consume(expected.head, plan)
            .map_err(|_| DurableHoldoutError::Semantic)?;
        if receipt.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            return Ok(receipt);
        }
        let payload = encode_holdout_plan(plan).map_err(|_| DurableHoldoutError::Semantic)?;
        let length = self.length + 4 + payload.len() as u64 + 32;
        if payload.len() > MAX_FRAME || length > MAX_BYTES {
            return Err(DurableHoldoutError::Capacity);
        }
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
            return Err(DurableHoldoutError::Indeterminate);
        }
        self.journal = candidate;
        self.length = length;
        Ok(receipt)
    }

    pub fn anchor(&self) -> HoldoutAnchorV1 {
        HoldoutAnchorV1 {
            sequence: self.journal.records().len() as u64,
            head: self.journal.head_digest(),
        }
    }
}

fn acquire(file: &File, binding: Digest32) -> Result<(), DurableHoldoutError> {
    if binding.is_zero() {
        return Err(DurableHoldoutError::Binding);
    }
    if !file.metadata()?.is_file() {
        return Err(DurableHoldoutError::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => DurableHoldoutError::Busy,
        TryLockError::Error(error) => DurableHoldoutError::Io(error.kind()),
    })
}

#[cfg(test)]
#[path = "durable_holdout_tests.rs"]
mod tests;
