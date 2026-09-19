//! Independent append-only acknowledgement witness for sparse checkpoints.
//!
//! The witness is deliberately stored outside the sparse journal. A journal
//! checksum can prove only the bytes that remain present; this store records the
//! minimum history the host already acknowledged so rollback is detectable.

use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AnchorWitnessStore;
use crate::JournalAnchor;
use crate::JournalScope;
use crate::WitnessStoreError;

const MAGIC: &[u8; 8] = b"HPTNWA01";
const HEADER: usize = 112;
const RECORD: usize = 112;
const MAX_RECORDS: usize = 4096;

struct WitnessLockedFile(File);

impl WitnessLockedFile {
    fn acquire(file: File) -> Result<Self, WitnessStoreError> {
        if !file.metadata()?.is_file() {
            return Err(WitnessStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(WitnessStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for WitnessLockedFile {
    type Target = File;

    fn deref(&self) -> &File {
        &self.0
    }
}

impl DerefMut for WitnessLockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for WitnessLockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct FileAnchorWitnessStore {
    file: WitnessLockedFile,
    max_records: usize,
    records: usize,
    current: Option<JournalAnchor>,
    poisoned: bool,
}

impl FileAnchorWitnessStore {
    pub fn open(
        file: File,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
    ) -> Result<Self, WitnessStoreError> {
        if !(1..=MAX_RECORDS).contains(&max_records) {
            return Err(WitnessStoreError::InvalidLimit);
        }
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(WitnessStoreError::ContextMismatch);
        }
        let mut file = WitnessLockedFile::acquire(file)?;
        let header = encode_header(scope, generation);
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            file.write_all(&header)
                .map_err(|_| WitnessStoreError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        } else {
            if length < HEADER as u64 || (length - HEADER as u64) % RECORD as u64 != 0 {
                return Err(WitnessStoreError::Corrupt);
            }
            let records = ((length - HEADER as u64) / RECORD as u64) as usize;
            if records > max_records {
                return Err(WitnessStoreError::Capacity);
            }
            let mut actual = [0_u8; HEADER];
            file.read_exact(&mut actual)?;
            if actual.as_slice() != header {
                return Err(WitnessStoreError::ContextMismatch);
            }
        }

        let records = ((file.metadata()?.len() - HEADER as u64) / RECORD as u64) as usize;
        let mut current = None;
        let mut buffer = [0_u8; RECORD];
        for _ in 0..records {
            file.read_exact(&mut buffer)?;
            let (expected, next) = decode_record(&buffer)?;
            if expected != current || !is_successor(expected, next) {
                return Err(WitnessStoreError::Corrupt);
            }
            current = Some(next);
        }
        file.sync_data()
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        Ok(Self {
            file,
            max_records,
            records,
            current,
            poisoned: false,
        })
    }
}

impl AnchorWitnessStore for FileAnchorWitnessStore {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        if self.poisoned {
            Err(WitnessStoreError::Poisoned)
        } else {
            Ok(self.current)
        }
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if self.poisoned {
            return Err(WitnessStoreError::Poisoned);
        }
        if self.current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        if !is_successor(expected, next) {
            return Err(WitnessStoreError::InvalidAnchor);
        }
        if self.records >= self.max_records {
            return Err(WitnessStoreError::Capacity);
        }
        let record = encode_record(expected, next);
        let expected_length = (HEADER + self.records * RECORD) as u64;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(WitnessStoreError::Corrupt);
        }
        self.file
            .write_all(&record)
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| WitnessStoreError::Indeterminate)?;
        self.records += 1;
        self.current = Some(next);
        self.poisoned = false;
        Ok(())
    }
}

fn encode_header(scope: JournalScope, generation: Generation) -> [u8; HEADER] {
    let mut bytes = Vec::with_capacity(HEADER);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; HEADER];
    output.copy_from_slice(&bytes);
    output
}

fn encode_record(expected: Option<JournalAnchor>, next: JournalAnchor) -> [u8; RECORD] {
    let mut bytes = Vec::with_capacity(RECORD);
    let expected = expected.unwrap_or(JournalAnchor {
        sequence: 0,
        checkpoint_digest: Digest32::ZERO,
    });
    bytes.extend_from_slice(&expected.sequence.to_be_bytes());
    bytes.extend_from_slice(expected.checkpoint_digest.as_array());
    bytes.extend_from_slice(&next.sequence.to_be_bytes());
    bytes.extend_from_slice(next.checkpoint_digest.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; RECORD];
    output.copy_from_slice(&bytes);
    output
}

fn decode_record(
    bytes: &[u8; RECORD],
) -> Result<(Option<JournalAnchor>, JournalAnchor), WitnessStoreError> {
    if Digest32::of_bytes(&bytes[..RECORD - 32]).as_array() != &bytes[RECORD - 32..] {
        return Err(WitnessStoreError::Corrupt);
    }
    let expected_sequence = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let expected_digest = Digest32::from_array(
        bytes[8..40]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let next_sequence = u64::from_be_bytes(
        bytes[40..48]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let next_digest = Digest32::from_array(
        bytes[48..80]
            .try_into()
            .map_err(|_| WitnessStoreError::Corrupt)?,
    );
    let expected = match (expected_sequence, expected_digest.is_zero()) {
        (0, true) => None,
        (0, false) | (_, true) => return Err(WitnessStoreError::Corrupt),
        (sequence, false) => Some(JournalAnchor {
            sequence,
            checkpoint_digest: expected_digest,
        }),
    };
    if next_sequence == 0 || next_digest.is_zero() {
        return Err(WitnessStoreError::Corrupt);
    }
    Ok((
        expected,
        JournalAnchor {
            sequence: next_sequence,
            checkpoint_digest: next_digest,
        },
    ))
}

fn is_successor(expected: Option<JournalAnchor>, next: JournalAnchor) -> bool {
    if next.checkpoint_digest.is_zero() {
        return false;
    }
    expected.map_or(next.sequence == 1, |value| {
        value.sequence.checked_add(1) == Some(next.sequence)
    })
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
