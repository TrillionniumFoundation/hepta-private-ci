//! Durable owner-local projection store over an explicitly host-authorized file.
//!
//! The store has no ambient path access and grants no selection, activation or
//! release authority. The host owns path authentication, containing-directory
//! durability, retention scheduling and independent protection of current
//! anchors/backups.

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

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const STORE_MAGIC: &[u8; 8] = b"HNDUPS01";
const REFERENCE_MAGIC: &[u8; 8] = b"HNDUPJ01";
const STORE_HEADER_BYTES: usize = 8 + 32 + 32;
const REFERENCE_HEADER_BYTES: usize = 8 + 4;
const RECORD_BYTES: usize = 8 + 1 + 32 + 32 + 32 + 32 + 32 + 32;
const MAX_RECORDS: usize = 4096;
const MAX_STORE_BYTES: usize =
    STORE_HEADER_BYTES + (MAX_RECORDS * RECORD_BYTES) + (RECORD_BYTES - 1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionStoreAnchorV1 {
    pub binding: Digest32,
    pub sequence: u64,
    pub entry_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionRecoveryV1 {
    Empty,
    Acknowledged(NduProjectionStoreAnchorV1),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionAppendDispositionV1 {
    Appended,
    IdempotentReplay,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionAppendReceiptV1 {
    pub disposition: NduProjectionAppendDispositionV1,
    pub entry: NduProjectionEntryV1,
    pub store_anchor: NduProjectionStoreAnchorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProjectionBackupV1 {
    pub binding: Digest32,
    pub store_anchor: Option<NduProjectionStoreAnchorV1>,
    pub file_digest: Digest32,
    pub encoded_bytes: usize,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableNduProjectionError {
    InvalidBinding,
    InvalidLimit,
    InvalidAnchor,
    Busy,
    NotRegular,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    IncompleteTail,
    UnwitnessedTail,
    Corrupt,
    Conflict,
    Capacity,
    BackupMismatch,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Semantic(NduProjectionJournalError),
}

impl fmt::Display for DurableNduProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DurableNduProjectionError {}

impl From<io::Error> for DurableNduProjectionError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<NduProjectionJournalError> for DurableNduProjectionError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Semantic(error)
    }
}

/// One exclusively owned local file plus the verified in-memory projection view.
/// Memory advances only after the corresponding record is durably synced.
pub struct DurableNduProjectionStoreV1 {
    file: LockedFile,
    core: NduProjectionJournalV1,
    binding: Digest32,
    max_records: usize,
    durable_length: u64,
    poisoned: bool,
}

impl DurableNduProjectionStoreV1 {
    /// Initialize an empty, already-created host-authorized regular file.
    /// Creation of the file and fsync of its containing directory remain host work.
    pub fn create(
        file: File,
        binding: Digest32,
        max_records: usize,
    ) -> Result<Self, DurableNduProjectionError> {
        validate_domain(binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableNduProjectionError::AlreadyInitialized);
        }
        let header = encode_header(binding);
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableNduProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            core: NduProjectionJournalV1::new(),
            binding,
            max_records,
            durable_length: STORE_HEADER_BYTES as u64,
            poisoned: false,
        })
    }

    /// Recover a store only against an independently retained anchor. A complete
    /// but unacknowledged suffix is rejected. An incomplete suffix may be
    /// truncated only when every complete record is covered by the supplied
    /// current anchor.
    pub fn recover(
        file: File,
        binding: Digest32,
        max_records: usize,
        recovery: NduProjectionRecoveryV1,
    ) -> Result<Self, DurableNduProjectionError> {
        validate_domain(binding, max_records)?;
        validate_recovery(recovery, binding, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        let (core, cursor, length) = replay_file(&mut file, binding, max_records)?;
        validate_recovered_history(&core, binding, recovery)?;
        if cursor != length {
            match recovery {
                NduProjectionRecoveryV1::Acknowledged(anchor)
                    if anchor.sequence == core.entries().len() as u64 =>
                {
                    file.set_len(cursor)
                        .map_err(|_| DurableNduProjectionError::Indeterminate)?;
                }
                _ => return Err(DurableNduProjectionError::IncompleteTail),
            }
        }
        file.sync_all()
            .map_err(|_| DurableNduProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            core,
            binding,
            max_records,
            durable_length: cursor,
            poisoned: false,
        })
    }

    /// Migrate an already validated owner-local reference journal into the
    /// durable store format. The caller is responsible for authenticating the
    /// source journal before invoking this operation.
    pub fn migrate_reference(
        file: File,
        binding: Digest32,
        max_records: usize,
        journal: NduProjectionJournalV1,
    ) -> Result<Self, DurableNduProjectionError> {
        validate_domain(binding, max_records)?;
        if journal.entries().len() > max_records {
            return Err(DurableNduProjectionError::Capacity);
        }
        let bytes = encode_store(binding, &journal)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableNduProjectionError::AlreadyInitialized);
        }
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableNduProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            core: journal,
            binding,
            max_records,
            durable_length: bytes.len() as u64,
            poisoned: false,
        })
    }

    pub fn restore_backup(
        file: File,
        max_records: usize,
        backup: NduProjectionBackupV1,
    ) -> Result<Self, DurableNduProjectionError> {
        validate_domain(backup.binding, max_records)?;
        if backup.encoded_bytes != backup.bytes.len()
            || backup.encoded_bytes > MAX_STORE_BYTES
            || Digest32::of_bytes(&backup.bytes) != backup.file_digest
        {
            return Err(DurableNduProjectionError::BackupMismatch);
        }
        let (journal, cursor) = decode_complete_store_bytes(
            &backup.bytes,
            backup.binding,
            max_records,
        )?;
        if cursor != backup.bytes.len() {
            return Err(DurableNduProjectionError::BackupMismatch);
        }
        validate_backup_anchor(&journal, backup.binding, backup.store_anchor)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(DurableNduProjectionError::AlreadyInitialized);
        }
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&backup.bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableNduProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            core: journal,
            binding: backup.binding,
            max_records,
            durable_length: backup.encoded_bytes as u64,
            poisoned: false,
        })
    }

    pub fn append_projection(
        &mut self,
        expected_anchor: Option<NduProjectionStoreAnchorV1>,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionAppendReceiptV1, DurableNduProjectionError> {
        self.mutate(expected_anchor, |journal| {
            journal.append_projection(
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
            )
        })
    }

    pub fn select_projection(
        &mut self,
        expected_anchor: Option<NduProjectionStoreAnchorV1>,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionAppendReceiptV1, DurableNduProjectionError> {
        self.mutate(expected_anchor, |journal| {
            journal.select_projection(
                operation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn revoke_projection(
        &mut self,
        expected_anchor: Option<NduProjectionStoreAnchorV1>,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionAppendReceiptV1, DurableNduProjectionError> {
        self.mutate(expected_anchor, |journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    pub fn journal(&self) -> Result<&NduProjectionJournalV1, DurableNduProjectionError> {
        if self.poisoned {
            Err(DurableNduProjectionError::Poisoned)
        } else {
            Ok(&self.core)
        }
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<NduProjectionStoreAnchorV1>, DurableNduProjectionError> {
        if self.poisoned {
            return Err(DurableNduProjectionError::Poisoned);
        }
        Ok(anchor_for(&self.core, self.binding))
    }

    /// Capture exact synced bytes and a current history witness. The returned
    /// object must be retained/authenticated outside the store before it is
    /// trusted as a restore source.
    pub fn backup(&mut self) -> Result<NduProjectionBackupV1, DurableNduProjectionError> {
        if self.poisoned {
            return Err(DurableNduProjectionError::Poisoned);
        }
        if self.file.metadata()?.len() != self.durable_length {
            return Err(DurableNduProjectionError::Corrupt);
        }
        let length = usize::try_from(self.durable_length)
            .map_err(|_| DurableNduProjectionError::Capacity)?;
        if length > MAX_STORE_BYTES {
            return Err(DurableNduProjectionError::Capacity);
        }
        self.file.seek(SeekFrom::Start(0))?;
        let mut bytes = vec![0; length];
        self.file.read_exact(&mut bytes)?;
        self.file.seek(SeekFrom::Start(self.durable_length))?;
        Ok(NduProjectionBackupV1 {
            binding: self.binding,
            store_anchor: anchor_for(&self.core, self.binding),
            file_digest: Digest32::of_bytes(&bytes),
            encoded_bytes: bytes.len(),
            bytes,
        })
    }

    fn mutate<F>(
        &mut self,
        expected_anchor: Option<NduProjectionStoreAnchorV1>,
        mutation: F,
    ) -> Result<NduProjectionAppendReceiptV1, DurableNduProjectionError>
    where
        F: FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    {
        if self.poisoned {
            return Err(DurableNduProjectionError::Poisoned);
        }
        if expected_anchor != anchor_for(&self.core, self.binding) {
            return Err(DurableNduProjectionError::Conflict);
        }

        let mut candidate = self.core.clone();
        let before = candidate.entries().len();
        let entry = mutation(&mut candidate)?;
        if candidate.entries().len() == before {
            let store_anchor = anchor_for(&self.core, self.binding)
                .ok_or(DurableNduProjectionError::Corrupt)?;
            return Ok(NduProjectionAppendReceiptV1 {
                disposition: NduProjectionAppendDispositionV1::IdempotentReplay,
                entry,
                store_anchor,
            });
        }
        if before >= self.max_records {
            return Err(DurableNduProjectionError::Capacity);
        }

        let exported = candidate.export_bytes();
        if exported.len() < REFERENCE_HEADER_BYTES + RECORD_BYTES {
            return Err(DurableNduProjectionError::Corrupt);
        }
        let record = &exported[exported.len() - RECORD_BYTES..];
        let next_length = self
            .durable_length
            .checked_add(RECORD_BYTES as u64)
            .ok_or(DurableNduProjectionError::Capacity)?;
        if next_length > MAX_STORE_BYTES as u64 {
            return Err(DurableNduProjectionError::Capacity);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(DurableNduProjectionError::Corrupt);
        }
        self.file
            .write_all(record)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| DurableNduProjectionError::Indeterminate)?;

        self.core = candidate;
        self.durable_length = next_length;
        self.poisoned = false;
        let store_anchor =
            anchor_for(&self.core, self.binding).ok_or(DurableNduProjectionError::Corrupt)?;
        Ok(NduProjectionAppendReceiptV1 {
            disposition: NduProjectionAppendDispositionV1::Appended,
            entry,
            store_anchor,
        })
    }
}

fn validate_domain(
    binding: Digest32,
    max_records: usize,
) -> Result<(), DurableNduProjectionError> {
    if binding.is_zero() {
        return Err(DurableNduProjectionError::InvalidBinding);
    }
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(DurableNduProjectionError::InvalidLimit);
    }
    Ok(())
}

fn validate_recovery(
    recovery: NduProjectionRecoveryV1,
    binding: Digest32,
    max_records: usize,
) -> Result<(), DurableNduProjectionError> {
    if let NduProjectionRecoveryV1::Acknowledged(anchor) = recovery
        && (anchor.binding != binding
            || anchor.sequence == 0
            || anchor.sequence > max_records as u64
            || anchor.entry_digest.is_zero())
    {
        return Err(DurableNduProjectionError::InvalidAnchor);
    }
    Ok(())
}

fn validate_recovered_history(
    journal: &NduProjectionJournalV1,
    binding: Digest32,
    recovery: NduProjectionRecoveryV1,
) -> Result<(), DurableNduProjectionError> {
    match recovery {
        NduProjectionRecoveryV1::Empty => {
            if journal.entries().is_empty() {
                Ok(())
            } else {
                Err(DurableNduProjectionError::UnwitnessedTail)
            }
        }
        NduProjectionRecoveryV1::Acknowledged(anchor) => {
            let index = usize::try_from(anchor.sequence - 1)
                .map_err(|_| DurableNduProjectionError::InvalidAnchor)?;
            let entry = journal
                .entries()
                .get(index)
                .ok_or(DurableNduProjectionError::AcknowledgedHistoryMissing)?;
            if anchor.binding != binding || entry.entry_digest != anchor.entry_digest {
                return Err(DurableNduProjectionError::AnchorMismatch);
            }
            if journal.entries().len() as u64 != anchor.sequence {
                return Err(DurableNduProjectionError::UnwitnessedTail);
            }
            Ok(())
        }
    }
}

fn validate_backup_anchor(
    journal: &NduProjectionJournalV1,
    binding: Digest32,
    anchor: Option<NduProjectionStoreAnchorV1>,
) -> Result<(), DurableNduProjectionError> {
    if anchor_for(journal, binding) == anchor {
        Ok(())
    } else {
        Err(DurableNduProjectionError::BackupMismatch)
    }
}

fn replay_file(
    file: &mut File,
    binding: Digest32,
    max_records: usize,
) -> Result<(NduProjectionJournalV1, u64, u64), DurableNduProjectionError> {
    let length = file.metadata()?.len();
    if length < STORE_HEADER_BYTES as u64 {
        return Err(DurableNduProjectionError::MissingHeader);
    }
    if length > MAX_STORE_BYTES as u64 {
        return Err(DurableNduProjectionError::Capacity);
    }
    let length_usize =
        usize::try_from(length).map_err(|_| DurableNduProjectionError::Capacity)?;
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = vec![0; length_usize];
    file.read_exact(&mut bytes)?;
    let (journal, cursor) = decode_store_prefix(&bytes, binding, max_records)?;
    Ok((journal, cursor as u64, length))
}

fn decode_complete_store_bytes(
    bytes: &[u8],
    binding: Digest32,
    max_records: usize,
) -> Result<(NduProjectionJournalV1, usize), DurableNduProjectionError> {
    let (journal, cursor) = decode_store_prefix(bytes, binding, max_records)?;
    if cursor != bytes.len() {
        return Err(DurableNduProjectionError::IncompleteTail);
    }
    Ok((journal, cursor))
}

fn decode_store_prefix(
    bytes: &[u8],
    binding: Digest32,
    max_records: usize,
) -> Result<(NduProjectionJournalV1, usize), DurableNduProjectionError> {
    if bytes.len() < STORE_HEADER_BYTES {
        return Err(DurableNduProjectionError::MissingHeader);
    }
    if bytes.len() > MAX_STORE_BYTES {
        return Err(DurableNduProjectionError::Capacity);
    }
    if &bytes[..8] != STORE_MAGIC {
        return Err(DurableNduProjectionError::Corrupt);
    }
    if &bytes[8..40] != binding.as_array() {
        return Err(DurableNduProjectionError::BindingMismatch);
    }
    if Digest32::of_bytes(&bytes[..40]).as_array() != &bytes[40..72] {
        return Err(DurableNduProjectionError::Corrupt);
    }

    let body = &bytes[STORE_HEADER_BYTES..];
    let complete_records = body.len() / RECORD_BYTES;
    if complete_records > max_records {
        return Err(DurableNduProjectionError::Capacity);
    }
    let complete_body = complete_records * RECORD_BYTES;
    let cursor = STORE_HEADER_BYTES + complete_body;
    let mut reference = Vec::with_capacity(REFERENCE_HEADER_BYTES + complete_body);
    reference.extend_from_slice(REFERENCE_MAGIC);
    reference.extend_from_slice(
        &u32::try_from(complete_records)
            .map_err(|_| DurableNduProjectionError::Capacity)?
            .to_be_bytes(),
    );
    reference.extend_from_slice(&body[..complete_body]);
    let journal =
        NduProjectionJournalV1::reopen(&reference).map_err(|_| DurableNduProjectionError::Corrupt)?;
    Ok((journal, cursor))
}

fn encode_header(binding: Digest32) -> Vec<u8> {
    let mut header = Vec::with_capacity(STORE_HEADER_BYTES);
    header.extend_from_slice(STORE_MAGIC);
    header.extend_from_slice(binding.as_array());
    let digest = Digest32::of_bytes(&header);
    header.extend_from_slice(digest.as_array());
    header
}

fn encode_store(
    binding: Digest32,
    journal: &NduProjectionJournalV1,
) -> Result<Vec<u8>, DurableNduProjectionError> {
    let reference = journal.export_bytes();
    if reference.len() < REFERENCE_HEADER_BYTES
        || &reference[..8] != REFERENCE_MAGIC
        || journal.entries().len() > MAX_RECORDS
    {
        return Err(DurableNduProjectionError::Corrupt);
    }
    let mut bytes = encode_header(binding);
    bytes.extend_from_slice(&reference[REFERENCE_HEADER_BYTES..]);
    if bytes.len() > MAX_STORE_BYTES {
        return Err(DurableNduProjectionError::Capacity);
    }
    Ok(bytes)
}

fn anchor_for(
    journal: &NduProjectionJournalV1,
    binding: Digest32,
) -> Option<NduProjectionStoreAnchorV1> {
    journal
        .entries()
        .last()
        .map(|entry| NduProjectionStoreAnchorV1 {
            binding,
            sequence: entry.sequence,
            entry_digest: entry.entry_digest,
        })
}

struct LockedFile(File);

impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableNduProjectionError> {
        if !file.metadata()?.is_file() {
            return Err(DurableNduProjectionError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableNduProjectionError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

impl std::ops::Deref for LockedFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl std::ops::DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

#[cfg(test)]
#[path = "durable_projection_store_tests.rs"]
mod tests;
