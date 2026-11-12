//! Locked, append-only persistence for one evaluation execution owner.
//!
//! The caller supplies an authorized regular file and retains the minimum
//! anchor independently. Path admission, directory fsync, file permissions and
//! original evaluator authentication remain caller responsibilities. Checksums
//! detect corruption and bind history; they do not authenticate an evaluator.
//! Returned completed bytes must still pass the runner's signed readback path.
//! Transfer exclusive ownership of the open file description: do not retain or
//! rewrap writable duplicates (including `File::try_clone`) or modify it outside
//! this store. A shared open description can make the OS lock reentrant.
//! Every live operation compares two complete physical images and the original
//! canonical replay against the retained state. Observed uncertainty poisons
//! this handle, even after old bytes are restored; this is not a cold fence.
//! All writers must honor the held lock. Cross-host use requires filesystem
//! locking and fsync semantics that are linearizable across those hosts.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1;
use crate::ProductEvaluationExecutionClaimV1;
use crate::ProductEvaluationExecutionKeyV1;
use crate::ProductEvaluationExecutionStateV1;
use crate::ProductEvaluationExecutionStoreErrorV1;
use crate::ProductEvaluationExecutionStoreV1;

#[path = "product_execution_physical.rs"]
mod physical;

#[path = "product_execution_readback.rs"]
mod readback;
pub use readback::ReadOnlyProductEvaluationExecutionStoreV1;

const MAGIC: &[u8; 8] = b"HEPTEX01";
const HEADER: usize = 72;
const MAX_FILE_BYTES: u64 = 32 * 1024 * 1024;
const MAX_PLANS: usize = 16_384;
const MAX_FRAME: usize = MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 + 163;

/// An externally retained prefix of one owner's execution journal.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProductEvaluationExecutionAnchorV1 {
    pub sequence: u64,
    pub history_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LockedFileProductEvaluationExecutionErrorV1 {
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

impl fmt::Display for LockedFileProductEvaluationExecutionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LockedFileProductEvaluationExecutionErrorV1 {}

type FileError = LockedFileProductEvaluationExecutionErrorV1;
type StoreError = ProductEvaluationExecutionStoreErrorV1;
type State = ProductEvaluationExecutionStateV1;

pub struct LockedFileProductEvaluationExecutionStoreV1 {
    file: HeldFile,
    binding: Digest32,
    image_digest: Digest32,
    records: BTreeMap<StableId, (Digest32, State)>,
    anchor: ProductEvaluationExecutionAnchorV1,
    length: u64,
    poisoned: bool,
}

// Explicit unlock also releases a lock retained by a duplicate open description.
struct HeldFile(File);

impl Deref for HeldFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for HeldFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl Drop for HeldFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

impl LockedFileProductEvaluationExecutionStoreV1 {
    pub fn create(file: File, binding: Digest32) -> Result<Self, FileError> {
        let mut file = acquire(file, binding)?;
        if file.metadata().map_err(io_error)?.len() != 0 {
            return Err(FileError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| FileError::Indeterminate)?;
        let mut store = Self {
            file,
            binding,
            image_digest: Digest32::of_bytes(&header),
            records: BTreeMap::new(),
            anchor: ProductEvaluationExecutionAnchorV1 {
                sequence: 0,
                history_digest: Digest32::of_bytes(&header),
            },
            length: HEADER as u64,
            poisoned: false,
        };
        store.ensure_ready().map_err(|_| FileError::Indeterminate)?;
        Ok(store)
    }

    /// Require a witnessed external prefix, including for an empty journal.
    /// Missing or torn suffixes are never truncated into an apparent success.
    pub fn recover(
        file: File,
        binding: Digest32,
        minimum: ProductEvaluationExecutionAnchorV1,
    ) -> Result<Self, FileError> {
        let mut file = acquire(file, binding)?;
        let bytes = physical::read_stable_image(&mut file)?;
        let replayed = physical::replay_image(&bytes, binding, minimum)?;
        file.sync_all().map_err(|_| FileError::Indeterminate)?;
        if physical::read_stable_image(&mut file)? != bytes {
            return Err(FileError::Indeterminate);
        }
        Ok(Self {
            file,
            binding,
            image_digest: Digest32::of_bytes(&bytes),
            records: replayed.records,
            anchor: replayed.anchor,
            length: bytes.len() as u64,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> ProductEvaluationExecutionAnchorV1 {
        self.anchor
    }

    fn ensure_ready(&mut self) -> Result<Vec<u8>, StoreError> {
        if self.poisoned {
            return Err(StoreError::Indeterminate);
        }
        self.poisoned = true;
        let bytes =
            physical::read_stable_image(&mut self.file).map_err(|_| StoreError::Indeterminate)?;
        let replayed = physical::replay_image(&bytes, self.binding, self.anchor)
            .map_err(|_| StoreError::Indeterminate)?;
        if bytes.len() as u64 != self.length
            || Digest32::of_bytes(&bytes) != self.image_digest
            || replayed.anchor != self.anchor
            || replayed.records != self.records
        {
            return Err(StoreError::Indeterminate);
        }
        self.poisoned = false;
        Ok(bytes)
    }

    fn append(&mut self, payload: &[u8]) -> Result<(), StoreError> {
        let next_length = self
            .length
            .checked_add(payload.len() as u64 + 36)
            .filter(|length| *length <= MAX_FILE_BYTES)
            .ok_or(StoreError::Rejected)?;
        let next = next_anchor(self.anchor, payload).map_err(|_| StoreError::Rejected)?;
        let mut expected = self.ensure_ready()?;
        let mut frame = (payload.len() as u32).to_be_bytes().to_vec();
        frame.extend_from_slice(payload);
        frame.extend_from_slice(next.history_digest.as_array());
        expected.extend_from_slice(&frame);
        self.poisoned = true;
        if self
            .file
            .seek(SeekFrom::Start(self.length))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|()| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(StoreError::Indeterminate);
        }
        let observed =
            physical::read_stable_image(&mut self.file).map_err(|_| StoreError::Indeterminate)?;
        let replayed = physical::replay_image(&observed, self.binding, next)
            .map_err(|_| StoreError::Indeterminate)?;
        if observed != expected || replayed.anchor != next {
            return Err(StoreError::Indeterminate);
        }
        self.length = next_length;
        self.anchor = next;
        self.image_digest = Digest32::of_bytes(&observed);
        self.poisoned = false;
        Ok(())
    }
}

impl ProductEvaluationExecutionStoreV1 for LockedFileProductEvaluationExecutionStoreV1 {
    fn claim(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionClaimV1, StoreError> {
        self.ensure_ready()?;
        if key.binding_digest.is_zero() {
            return Err(StoreError::Rejected);
        }
        if let Some((binding, state)) = self.records.get(&key.plan_id) {
            if *binding != key.binding_digest {
                return Err(StoreError::Conflict);
            }
            return Ok(ProductEvaluationExecutionClaimV1::Existing(state.clone()));
        }
        if self.records.len() >= MAX_PLANS {
            return Err(StoreError::Rejected);
        }
        let payload = encode_key(/*tag*/ 0, key);
        self.append(&payload)?;
        self.records
            .insert(key.plan_id.clone(), (key.binding_digest, State::Pending));
        Ok(ProductEvaluationExecutionClaimV1::Claimed)
    }

    fn complete(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
        payload: &[u8],
    ) -> Result<(), StoreError> {
        self.ensure_ready()?;
        if payload.is_empty() || payload.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
            return Err(StoreError::Rejected);
        }
        let (binding, current) = self.records.get(&key.plan_id).ok_or(StoreError::Missing)?;
        if *binding != key.binding_digest {
            return Err(StoreError::Conflict);
        }
        match current {
            State::Completed(existing) if existing == payload => return Ok(()),
            State::Completed(_) => return Err(StoreError::Conflict),
            State::Pending => {}
        }
        let mut event = encode_key(/*tag*/ 1, key);
        event.extend_from_slice(payload);
        self.append(&event)?;
        self.records.insert(
            key.plan_id.clone(),
            (key.binding_digest, State::Completed(payload.to_vec())),
        );
        Ok(())
    }

    fn readback(&mut self, key: &ProductEvaluationExecutionKeyV1) -> Result<State, StoreError> {
        self.ensure_ready()?;
        let (binding, state) = self.records.get(&key.plan_id).ok_or(StoreError::Missing)?;
        if *binding != key.binding_digest {
            return Err(StoreError::Conflict);
        }
        Ok(state.clone())
    }
}

fn encode_key(tag: u8, key: &ProductEvaluationExecutionKeyV1) -> Vec<u8> {
    let mut bytes = vec![tag];
    let id = key.plan_id.as_str().as_bytes();
    bytes.extend_from_slice(&(id.len() as u16).to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(key.binding_digest.as_array());
    bytes
}

fn replay(
    records: &mut BTreeMap<StableId, (Digest32, State)>,
    mut payload: &[u8],
) -> Result<(), FileError> {
    let tag = take(&mut payload, 1)?[0];
    let raw = take(&mut payload, 2)?;
    let id_length = u16::from_be_bytes([raw[0], raw[1]]) as usize;
    if !(1..=128).contains(&id_length) {
        return Err(FileError::Corrupt);
    }
    let name =
        std::str::from_utf8(take(&mut payload, id_length)?).map_err(|_| FileError::Corrupt)?;
    let plan_id = StableId::new(name).map_err(|_| FileError::Corrupt)?;
    let binding = Digest32::from_array(
        take(&mut payload, 32)?
            .try_into()
            .map_err(|_| FileError::Corrupt)?,
    );
    if binding.is_zero() {
        return Err(FileError::Corrupt);
    }
    match tag {
        0 => {
            if !payload.is_empty() || records.contains_key(&plan_id) {
                return Err(FileError::Corrupt);
            }
            if records.len() >= MAX_PLANS {
                return Err(FileError::Capacity);
            }
            records.insert(plan_id, (binding, State::Pending));
        }
        1 => {
            if payload.is_empty() || payload.len() > MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1 {
                return Err(FileError::Capacity);
            }
            let (prior_binding, prior) = records.get_mut(&plan_id).ok_or(FileError::Corrupt)?;
            if *prior_binding != binding || !matches!(prior, State::Pending) {
                return Err(FileError::Corrupt);
            }
            *prior = State::Completed(payload.to_vec());
        }
        _ => return Err(FileError::Corrupt),
    }
    Ok(())
}

fn take<'a>(bytes: &mut &'a [u8], count: usize) -> Result<&'a [u8], FileError> {
    let (head, tail) = bytes.split_at_checked(count).ok_or(FileError::Corrupt)?;
    *bytes = tail;
    Ok(head)
}

fn next_anchor(
    previous: ProductEvaluationExecutionAnchorV1,
    payload: &[u8],
) -> Result<ProductEvaluationExecutionAnchorV1, FileError> {
    let sequence = previous
        .sequence
        .checked_add(1)
        .ok_or(FileError::Capacity)?;
    let history_digest = Digest32::of_parts(&[
        b"hepta.product-evaluation.execution-journal.v1",
        previous.history_digest.as_array(),
        &sequence.to_be_bytes(),
        payload,
    ]);
    Ok(ProductEvaluationExecutionAnchorV1 {
        sequence,
        history_digest,
    })
}

fn acquire(file: File, binding: Digest32) -> Result<HeldFile, FileError> {
    if binding.is_zero() {
        return Err(FileError::Binding);
    }
    if !file.metadata().map_err(io_error)?.is_file() {
        return Err(FileError::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => FileError::Busy,
        TryLockError::Error(error) => io_error(error),
    })?;
    Ok(HeldFile(file))
}

fn io_error(error: io::Error) -> FileError {
    FileError::Io(error.kind())
}

#[cfg(test)]
#[path = "product_execution_file_tests.rs"]
mod tests;
