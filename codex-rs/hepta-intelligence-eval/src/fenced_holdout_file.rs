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

/// The acquiring owner explicitly releases its OS lock on every exit path.
/// Closing one descriptor is insufficient when a concurrent fork temporarily
/// retains another descriptor for the same open-file description.
struct AcquiredHoldoutFile(File);

impl std::ops::Deref for AcquiredHoldoutFile {
    type Target = File;
    fn deref(&self) -> &File {
        &self.0
    }
}

impl std::ops::DerefMut for AcquiredHoldoutFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for AcquiredHoldoutFile {
    fn drop(&mut self) {
        // Do not unlock a failed contender: this guard is constructed only
        // after try_lock succeeds. Errors remain fail-closed for the next owner.
        let _ = self.0.unlock();
    }
}

pub struct LockedFileFinalHoldoutCasStoreV1 {
    file: AcquiredHoldoutFile,
    binding: Digest32,
    state: Option<FinalHoldoutCasRecordV1>,
    length: u64,
    poisoned: bool,
}

impl LockedFileFinalHoldoutCasStoreV1 {
    pub fn create(file: File, binding: Digest32) -> Result<Self, LockedFileCasErrorV1> {
        let mut file = acquire(file, binding)?;
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
            length: HEADER as u64,
            poisoned: false,
        })
    }

    pub fn recover(
        file: File,
        binding: Digest32,
        minimum: Option<FinalHoldoutCasAnchorV1>,
    ) -> Result<Self, LockedFileCasErrorV1> {
        let mut file = acquire(file, binding)?;
        let length = file.metadata().map_err(io_error)?.len();
        if length > MAX_BYTES {
            return Err(LockedFileCasErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        let mut bytes = Vec::new();
        (&mut *file)
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

        let mut replay = ValidatedReplay::new(binding)?;
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
            let observed = replay.apply(payload)?;
            if minimum == Some(observed) {
                minimum_witnessed = true;
            }
        }
        let state = replay.finish()?;
        validate_minimum(state.as_ref(), minimum, minimum_witnessed)?;
        file.sync_all()
            .map_err(|_| LockedFileCasErrorV1::Indeterminate)?;
        Ok(Self {
            file,
            binding,
            state,
            length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> Option<FinalHoldoutCasAnchorV1> {
        self.state.as_ref().map(record_anchor)
    }
}

impl FinalHoldoutCasStoreV1 for LockedFileFinalHoldoutCasStoreV1 {
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
        self.state = Some(next.clone());
        self.length = next_length;
        Ok(())
    }
}

fn transition_payload(
    current: Option<&FinalHoldoutCasRecordV1>,
    next: &FinalHoldoutCasRecordV1,
) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    match current {
        None => {
            if !next.journal.records.is_empty() {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            encode_fence(&next.fence)
        }
        Some(current) if next.journal == current.journal => {
            if next.fence == current.fence {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            if next.fence.generation <= current.fence.generation {
                return Err(LockedFileCasErrorV1::Rollback);
            }
            encode_fence(&next.fence)
        }
        Some(current) => {
            if next.fence != current.fence
                || next.journal.records.len() != current.journal.records.len() + 1
                || next.journal.records[..current.journal.records.len()]
                    != current.journal.records[..]
            {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            let record = next
                .journal
                .records
                .last()
                .ok_or(LockedFileCasErrorV1::Corrupt)?;
            let encoded =
                encode_holdout_plan(&record.plan).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let mut payload = vec![EVENT_PLAN];
            payload.extend_from_slice(&encoded);
            Ok(payload)
        }
    }
}

/// Reuse the semantic journal while streaming verified frames. Previously every
/// frame reconstructed and revalidated the entire prefix multiple times. Each
/// event still checks its checksum, plan seal, one-use/lineage invariants and
/// fence order; each prefix is compared with the retained independent anchor.
/// Only the final externally returned CAS record is fully materialized.
struct ValidatedReplay {
    binding: Digest32,
    fence: Option<HoldoutWriterFenceV1>,
    journal: FinalHoldoutJournalV1,
}

impl ValidatedReplay {
    fn new(binding: Digest32) -> Result<Self, LockedFileCasErrorV1> {
        Ok(Self {
            binding,
            fence: None,
            journal: FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
        })
    }

    fn apply(&mut self, payload: &[u8]) -> Result<FinalHoldoutCasAnchorV1, LockedFileCasErrorV1> {
        match payload.first().copied() {
            Some(EVENT_FENCE) => {
                let next = decode_fence(payload)?;
                if self
                    .fence
                    .as_ref()
                    .is_some_and(|current| next.generation <= current.generation)
                {
                    return Err(LockedFileCasErrorV1::Rollback);
                }
                self.fence = Some(next);
            }
            Some(EVENT_PLAN) => {
                if self.fence.is_none() {
                    return Err(LockedFileCasErrorV1::Corrupt);
                }
                let plan = decode_holdout_plan(&payload[1..])
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
                let receipt = self
                    .journal
                    .consume(self.journal.head_digest(), &plan)
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
                if receipt.disposition != crate::HoldoutUseDispositionV1::Recorded {
                    return Err(LockedFileCasErrorV1::Corrupt);
                }
            }
            _ => return Err(LockedFileCasErrorV1::Corrupt),
        }
        let fence = self.fence.as_ref().ok_or(LockedFileCasErrorV1::Corrupt)?;
        Ok(FinalHoldoutCasAnchorV1 {
            fence_generation: fence.generation,
            record_count: self.journal.records().len() as u64,
            state_digest: crate::fenced_holdout::digest_state_frontier(
                self.binding,
                fence,
                self.journal.records().len(),
                self.journal.head_digest(),
            )
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
        })
    }

    fn finish(self) -> Result<Option<FinalHoldoutCasRecordV1>, LockedFileCasErrorV1> {
        self.fence
            .map(|fence| {
                FinalHoldoutCasRecordV1::new(self.binding, fence, self.journal.snapshot())
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)
            })
            .transpose()
    }
}

#[cfg(test)]
fn replay_event_reference(
    binding: Digest32,
    current: Option<FinalHoldoutCasRecordV1>,
    payload: &[u8],
) -> Result<FinalHoldoutCasRecordV1, LockedFileCasErrorV1> {
    let tag = *payload.first().ok_or(LockedFileCasErrorV1::Corrupt)?;
    match tag {
        EVENT_FENCE => {
            let fence = decode_fence(payload)?;
            let journal = match current {
                Some(ref current) => {
                    if fence.generation <= current.fence.generation {
                        return Err(LockedFileCasErrorV1::Rollback);
                    }
                    FinalHoldoutJournalV1::from_snapshot_with_record_limit(
                        current.journal.clone(),
                        MAX_RECORDS,
                    )
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?
                }
                None => FinalHoldoutJournalV1::with_record_limit(MAX_RECORDS)
                    .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
            };
            FinalHoldoutCasRecordV1::new(binding, fence, journal.snapshot())
                .map_err(|_| LockedFileCasErrorV1::Corrupt)
        }
        EVENT_PLAN => {
            let current = current.ok_or(LockedFileCasErrorV1::Corrupt)?;
            let plan =
                decode_holdout_plan(&payload[1..]).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let mut journal = FinalHoldoutJournalV1::from_snapshot_with_record_limit(
                current.journal.clone(),
                MAX_RECORDS,
            )
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            let receipt = journal
                .consume(journal.head_digest(), &plan)
                .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
            if receipt.disposition != crate::HoldoutUseDispositionV1::Recorded {
                return Err(LockedFileCasErrorV1::Corrupt);
            }
            FinalHoldoutCasRecordV1::new(binding, current.fence, journal.snapshot())
                .map_err(|_| LockedFileCasErrorV1::Corrupt)
        }
        _ => Err(LockedFileCasErrorV1::Corrupt),
    }
}

fn encode_fence(fence: &HoldoutWriterFenceV1) -> Result<Vec<u8>, LockedFileCasErrorV1> {
    if fence.generation == 0 || fence.lease_digest.is_zero() {
        return Err(LockedFileCasErrorV1::Binding);
    }
    let owner = fence.owner_id.as_str().as_bytes();
    let owner_len = u16::try_from(owner.len()).map_err(|_| LockedFileCasErrorV1::Capacity)?;
    let mut payload = vec![EVENT_FENCE];
    payload.extend_from_slice(&owner_len.to_be_bytes());
    payload.extend_from_slice(owner);
    payload.extend_from_slice(&fence.generation.to_be_bytes());
    payload.extend_from_slice(fence.lease_digest.as_array());
    Ok(payload)
}

fn decode_fence(payload: &[u8]) -> Result<HoldoutWriterFenceV1, LockedFileCasErrorV1> {
    if payload.first().copied() != Some(EVENT_FENCE) || payload.len() < 1 + 2 + 8 + 32 {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    let owner_len = u16::from_be_bytes([payload[1], payload[2]]) as usize;
    let owner_start = 3;
    let owner_end = owner_start + owner_len;
    let generation_end = owner_end + 8;
    let lease_end = generation_end + 32;
    if lease_end != payload.len() {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    let owner = std::str::from_utf8(
        payload
            .get(owner_start..owner_end)
            .ok_or(LockedFileCasErrorV1::Corrupt)?,
    )
    .map_err(|_| LockedFileCasErrorV1::Corrupt)?;
    let generation_bytes = payload
        .get(owner_end..generation_end)
        .ok_or(LockedFileCasErrorV1::Corrupt)?;
    let generation = u64::from_be_bytes(
        generation_bytes
            .try_into()
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
    );
    let lease = payload
        .get(generation_end..lease_end)
        .ok_or(LockedFileCasErrorV1::Corrupt)?;
    let lease_digest = Digest32::from_array(
        lease
            .try_into()
            .map_err(|_| LockedFileCasErrorV1::Corrupt)?,
    );
    let owner_id = StableId::new(owner).map_err(|_| LockedFileCasErrorV1::Corrupt)?;
    if generation == 0 || lease_digest.is_zero() {
        return Err(LockedFileCasErrorV1::Corrupt);
    }
    Ok(HoldoutWriterFenceV1 {
        owner_id,
        generation,
        lease_digest,
    })
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

fn acquire(file: File, binding: Digest32) -> Result<AcquiredHoldoutFile, LockedFileCasErrorV1> {
    if binding.is_zero() {
        return Err(LockedFileCasErrorV1::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(LockedFileCasErrorV1::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => LockedFileCasErrorV1::Busy,
        TryLockError::Error(error) => LockedFileCasErrorV1::Io(error.kind()),
    })?;
    Ok(AcquiredHoldoutFile(file))
}

fn io_error(error: io::Error) -> LockedFileCasErrorV1 {
    LockedFileCasErrorV1::Io(error.kind())
}

#[cfg(test)]
#[path = "fenced_holdout_file_tests.rs"]
mod tests;
