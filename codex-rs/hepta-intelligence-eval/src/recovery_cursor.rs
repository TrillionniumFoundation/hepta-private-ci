//! Bounded, restartable scheduling progress, never qualification evidence.
//!
//! Two checksummed slots retain one predecessor across a torn cursor write.
//! Replaying an older cursor is safe only because the authoritative attempt
//! journal and publication owner independently prevent repeated effects.
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ProductEvaluationAttemptJournalErrorV1;

type Error = ProductEvaluationAttemptJournalErrorV1;
const MAGIC: &[u8; 8] = b"HEQCUR01";
const SLOT_BYTES: usize = 256;
const BODY_BYTES: usize = SLOT_BYTES - 32;
const FILE_BYTES: usize = SLOT_BYTES * 2;
const ID_START: usize = 51;
const MAX_ID_BYTES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
struct Progress {
    generation: u64,
    after: Option<StableId>,
}

pub(super) struct RecoveryCursor {
    file: File,
    binding: Digest32,
    progress: Progress,
    slot: usize,
}

impl RecoveryCursor {
    /// The host supplies an authorized, directory-durable regular file. The
    /// exclusive lock is held for the entire page, not just the cursor write.
    pub(super) fn open(mut file: File, binding: Digest32) -> Result<Self, Error> {
        if binding.is_zero() {
            return Err(Error::Binding);
        }
        if !file.metadata().map_err(io_error)?.file_type().is_file() {
            return Err(Error::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(Error::Busy),
            Err(TryLockError::Error(error)) => return Err(io_error(error)),
        }
        let length = file.metadata().map_err(io_error)?.len();
        if length == 0 {
            file.set_len(FILE_BYTES as u64)
                .map_err(|_| Error::Indeterminate)?;
            let mut value = Self {
                file,
                binding,
                progress: Progress {
                    generation: 0,
                    after: None,
                },
                slot: 1,
            };
            value.save(None)?;
            return Ok(value);
        }
        if length != FILE_BYTES as u64 {
            return Err(Error::Corrupt);
        }
        let mut bytes = [0_u8; FILE_BYTES];
        file.seek(SeekFrom::Start(0)).map_err(io_error)?;
        file.read_exact(&mut bytes).map_err(io_error)?;
        let first = decode(&bytes[..SLOT_BYTES], binding)?;
        let second = decode(&bytes[SLOT_BYTES..], binding)?;
        let (progress, slot) = match (first, second) {
            (Some(first), Some(second)) => {
                if first.generation.abs_diff(second.generation) != 1 {
                    return Err(Error::Corrupt);
                }
                if first.generation > second.generation {
                    (first, 0)
                } else {
                    (second, 1)
                }
            }
            (Some(first), None) => (first, 0),
            (None, Some(second)) => (second, 1),
            (None, None) => return Err(Error::Corrupt),
        };
        Ok(Self {
            file,
            binding,
            progress,
            slot,
        })
    }

    pub(super) fn after(&self) -> Option<&StableId> {
        self.progress.after.as_ref()
    }

    /// Cursor acknowledgement follows fsync. Failure may have committed this
    /// progress, so callers must abandon the handle and reopen, not retry a
    /// qualification action on the strength of an in-memory error.
    pub(super) fn save(&mut self, after: Option<&StableId>) -> Result<(), Error> {
        if self.progress.generation != 0 && self.after() == after {
            return Ok(());
        }
        let next = Progress {
            generation: self
                .progress
                .generation
                .checked_add(1)
                .ok_or(Error::Capacity)?,
            after: after.cloned(),
        };
        let bytes = encode(&next, self.binding)?;
        if self.file.metadata().map_err(io_error)?.len() != FILE_BYTES as u64 {
            return Err(Error::Indeterminate);
        }
        let slot = 1 - self.slot;
        self.file
            .seek(SeekFrom::Start((slot * SLOT_BYTES) as u64))
            .and_then(|_| self.file.write_all(&bytes))
            .and_then(|()| self.file.sync_all())
            .map_err(|_| Error::Indeterminate)?;
        self.progress = next;
        self.slot = slot;
        Ok(())
    }
}

fn encode(progress: &Progress, binding: Digest32) -> Result<[u8; SLOT_BYTES], Error> {
    if progress.generation == 0 || binding.is_zero() {
        return Err(Error::Binding);
    }
    let mut bytes = [0_u8; SLOT_BYTES];
    bytes[..8].copy_from_slice(MAGIC);
    bytes[8..16].copy_from_slice(&progress.generation.to_be_bytes());
    bytes[16..48].copy_from_slice(binding.as_array());
    if let Some(after) = &progress.after {
        let id = after.as_str().as_bytes();
        if !(1..=MAX_ID_BYTES).contains(&id.len()) {
            return Err(Error::Capacity);
        }
        let length = u16::try_from(id.len()).map_err(|_| Error::Capacity)?;
        bytes[48] = 1;
        bytes[49..51].copy_from_slice(&length.to_be_bytes());
        bytes[ID_START..ID_START + id.len()].copy_from_slice(id);
    }
    let checksum = Digest32::of_bytes(&bytes[..BODY_BYTES]);
    bytes[BODY_BYTES..].copy_from_slice(checksum.as_array());
    Ok(bytes)
}

fn decode(bytes: &[u8], binding: Digest32) -> Result<Option<Progress>, Error> {
    if bytes.len() != SLOT_BYTES {
        return Err(Error::Corrupt);
    }
    if bytes.iter().all(|byte| *byte == 0)
        || &bytes[BODY_BYTES..] != Digest32::of_bytes(&bytes[..BODY_BYTES]).as_array()
    {
        return Ok(None);
    }
    if &bytes[..8] != MAGIC {
        return Err(Error::Corrupt);
    }
    if &bytes[16..48] != binding.as_array() {
        return Err(Error::Binding);
    }
    let generation = u64::from_be_bytes(bytes[8..16].try_into().map_err(|_| Error::Corrupt)?);
    let length = usize::from(u16::from_be_bytes([bytes[49], bytes[50]]));
    if generation == 0 || length > MAX_ID_BYTES {
        return Err(Error::Corrupt);
    }
    let after = match (bytes[48], length) {
        (0, 0) => None,
        (1, 1..=MAX_ID_BYTES) => {
            let text = std::str::from_utf8(&bytes[ID_START..ID_START + length])
                .map_err(|_| Error::Corrupt)?;
            Some(StableId::new(text).map_err(|_| Error::Corrupt)?)
        }
        _ => return Err(Error::Corrupt),
    };
    if bytes[ID_START + length..BODY_BYTES]
        .iter()
        .any(|byte| *byte != 0)
    {
        return Err(Error::Corrupt);
    }
    Ok(Some(Progress { generation, after }))
}

fn io_error(error: io::Error) -> Error {
    Error::Io(error.kind())
}

#[cfg(test)]
#[path = "recovery_cursor_tests.rs"]
mod tests;
