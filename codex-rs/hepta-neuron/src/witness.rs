//! Independent append-only acknowledgement witness for sparse checkpoints.
//!
//! The witness is deliberately stored outside the sparse journal. A journal
//! checksum can prove only the bytes that remain present; this store records the
//! minimum history the host already acknowledged so rollback is detectable.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AnchorWitnessStore;
use crate::JournalAnchor;
use crate::JournalScope;
use crate::WitnessStoreError;

const ROOT_MAGIC: &[u8; 8] = b"HPTNWA01";
const ROOT_HEADER: usize = 112;
const SUCCESSOR_MAGIC: &[u8; 8] = b"HPTNWA02";
const SUCCESSOR_HEADER: usize = 152;
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
    scope: JournalScope,
    generation: Generation,
    seed: Option<JournalAnchor>,
    header_bytes: usize,
    max_records: usize,
    records: usize,
    current: Option<JournalAnchor>,
    poisoned: bool,
}

impl FileAnchorWitnessStore {
    /// Open or initialize the first witness segment. Existing HPTNWA01 bytes
    /// remain byte-compatible with the original single-file implementation.
    pub fn open(
        file: File,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
    ) -> Result<Self, WitnessStoreError> {
        Self::open_segment(file, scope, generation, max_records, None)
    }

    /// Create the first segment by pathname and durably enroll its directory
    /// entry before returning. The parent directory must already exist and be
    /// private to the composing owner.
    pub fn create(
        path: &Path,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
    ) -> Result<Self, WitnessStoreError> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let store = Self::open(file, scope, generation, max_records)?;
        sync_parent_directory(path)?;
        Ok(store)
    }

    /// Open or initialize a compacted successor segment. Its immutable header
    /// binds the exact acknowledged frontier of the predecessor segment. A
    /// successor can therefore start empty without pretending history began at
    /// sequence one or silently discarding the retained anti-rollback anchor.
    pub fn open_successor(
        file: File,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
        seed: JournalAnchor,
    ) -> Result<Self, WitnessStoreError> {
        Self::open_segment(file, scope, generation, max_records, Some(seed))
    }

    /// Path-owned successor creation includes parent-directory synchronization.
    /// A crash before the caller atomically publishes its segment manifest may
    /// leave an unreferenced file, but cannot move the acknowledged frontier.
    pub fn create_successor(
        path: &Path,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
        seed: JournalAnchor,
    ) -> Result<Self, WitnessStoreError> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let store = Self::open_successor(file, scope, generation, max_records, seed)?;
        sync_parent_directory(path)?;
        Ok(store)
    }

    /// Start a bounded successor from the exact current acknowledged anchor.
    /// The old segment remains immutable and may be retained for audit/backup;
    /// deletion is a separate host-authorized lifecycle operation.
    pub fn start_successor(
        &self,
        file: File,
        max_records: usize,
    ) -> Result<Self, WitnessStoreError> {
        if self.poisoned {
            return Err(WitnessStoreError::Poisoned);
        }
        let seed = self.current.ok_or(WitnessStoreError::InvalidAnchor)?;
        Self::open_successor(file, self.scope, self.generation, max_records, seed)
    }

    #[must_use]
    pub fn segment_seed(&self) -> Option<JournalAnchor> {
        self.seed
    }

    pub fn remaining_capacity(&self) -> Result<usize, WitnessStoreError> {
        if self.poisoned {
            return Err(WitnessStoreError::Poisoned);
        }
        Ok(self.max_records.saturating_sub(self.records))
    }

    fn open_segment(
        file: File,
        scope: JournalScope,
        generation: Generation,
        max_records: usize,
        seed: Option<JournalAnchor>,
    ) -> Result<Self, WitnessStoreError> {
        if !(1..=MAX_RECORDS).contains(&max_records) {
            return Err(WitnessStoreError::InvalidLimit);
        }
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(WitnessStoreError::ContextMismatch);
        }
        if seed.is_some_and(|anchor| anchor.sequence == 0 || anchor.checkpoint_digest.is_zero()) {
            return Err(WitnessStoreError::InvalidAnchor);
        }

        let mut file = WitnessLockedFile::acquire(file)?;
        let header = encode_header(scope, generation, seed);
        let header_bytes = header.len();
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            file.write_all(&header)
                .map_err(|_| WitnessStoreError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| WitnessStoreError::Indeterminate)?;
        } else {
            if length < header_bytes as u64
                || !(length - header_bytes as u64).is_multiple_of(RECORD as u64)
            {
                return Err(WitnessStoreError::Corrupt);
            }
            let records = ((length - header_bytes as u64) / RECORD as u64) as usize;
            if records > max_records {
                return Err(WitnessStoreError::Capacity);
            }
            let mut actual = vec![0_u8; header_bytes];
            file.read_exact(&mut actual)?;
            if actual != header {
                return Err(WitnessStoreError::ContextMismatch);
            }
        }

        let records = ((file.metadata()?.len() - header_bytes as u64) / RECORD as u64) as usize;
        let mut current = seed;
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
            scope,
            generation,
            seed,
            header_bytes,
            max_records,
            records,
            current,
            poisoned: false,
        })
    }
}

impl AnchorWitnessStore for FileAnchorWitnessStore {
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        if self.poisoned {
            return Err(WitnessStoreError::Poisoned);
        }
        if self.current != expected {
            return Err(WitnessStoreError::Conflict);
        }
        if self.records >= self.max_records {
            return Err(WitnessStoreError::Capacity);
        }
        Ok(())
    }

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
        self.admit_new_anchor(expected)?;
        if !is_successor(expected, next) {
            return Err(WitnessStoreError::InvalidAnchor);
        }
        let record = encode_record(expected, next);
        let expected_length = (self.header_bytes + self.records * RECORD) as u64;
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

fn encode_header(
    scope: JournalScope,
    generation: Generation,
    seed: Option<JournalAnchor>,
) -> Vec<u8> {
    let capacity = if seed.is_some() {
        SUCCESSOR_HEADER
    } else {
        ROOT_HEADER
    };
    let mut bytes = Vec::with_capacity(capacity);
    bytes.extend_from_slice(if seed.is_some() {
        SUCCESSOR_MAGIC
    } else {
        ROOT_MAGIC
    });
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    if let Some(seed) = seed {
        bytes.extend_from_slice(&seed.sequence.to_be_bytes());
        bytes.extend_from_slice(seed.checkpoint_digest.as_array());
    }
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    debug_assert_eq!(bytes.len(), capacity);
    bytes
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

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), WitnessStoreError> {
    let parent = path.parent().ok_or_else(|| {
        WitnessStoreError::Io(std::io::ErrorKind::InvalidInput)
    })?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), WitnessStoreError> {
    Ok(())
}

#[cfg(test)]
#[path = "witness_tests.rs"]
mod tests;
