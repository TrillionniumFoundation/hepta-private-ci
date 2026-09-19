//! Durable owner-local storage adapter for NDU projection state.
//!
//! The host supplies an authorized regular file and retains returned anchors
//! independently of this file. The adapter uses an immutable store binding,
//! exclusive cooperative file lock, append-only fixed records and sync-before-
//! publish ordering. Directory durability, backup policy, retention, external
//! anchor authentication and production activation remain host responsibilities.

use std::error::Error;
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
use crate::NduProjectionJournalAnchorV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const MAGIC: &[u8; 8] = b"HNDUDR01";
const HEADER_BYTES: usize = 72;
const RECORD_BYTES: usize = 8 + 1 + 32 * 6;
const MAX_RECORDS: usize = 4096;
const MAX_BYTES: u64 = HEADER_BYTES as u64 + MAX_RECORDS as u64 * RECORD_BYTES as u64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduDurableProjectionError {
    InvalidBinding,
    InvalidAnchor,
    NotRegular,
    Busy,
    AlreadyInitialized,
    MissingHeader,
    BindingMismatch,
    Corrupt,
    MissingAcknowledgedHistory,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Semantic(NduProjectionJournalError),
    Io(io::ErrorKind),
}

impl fmt::Display for NduDurableProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduDurableProjectionError {}

impl From<io::Error> for NduDurableProjectionError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// One exclusively owned local append-only projection store.
///
/// The core journal advances only after the corresponding record is synced.
/// After an indeterminate I/O outcome the handle is poisoned; callers must
/// recover against their independently retained minimum anchor before retrying.
#[derive(Debug)]
pub struct NduDurableProjectionStoreV1 {
    file: File,
    journal: NduProjectionJournalV1,
    durable_length: u64,
    poisoned: bool,
}

impl NduDurableProjectionStoreV1 {
    /// Explicit initialization only. Never use creation as a fallback when
    /// acknowledged history is missing.
    pub fn create(mut file: File, binding: Digest32) -> Result<Self, NduDurableProjectionError> {
        acquire(&file, binding)?;
        if file.metadata()?.len() != 0 {
            return Err(NduDurableProjectionError::AlreadyInitialized);
        }
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(binding.as_array());
        header.extend_from_slice(Digest32::of_bytes(&header).as_array());
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            journal: NduProjectionJournalV1::new(),
            durable_length: HEADER_BYTES as u64,
            poisoned: false,
        })
    }

    /// Replays a complete store without trimming or silently replacing history.
    /// The minimum anchor must be retained outside the store itself.
    pub fn recover(
        mut file: File,
        binding: Digest32,
        minimum: NduProjectionJournalAnchorV1,
    ) -> Result<Self, NduDurableProjectionError> {
        acquire(&file, binding)?;
        validate_anchor(minimum)?;
        let length = file.metadata()?.len();
        if length < HEADER_BYTES as u64 {
            return Err(NduDurableProjectionError::MissingHeader);
        }
        if length > MAX_BYTES {
            return Err(NduDurableProjectionError::Capacity);
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Vec::new();
        (&mut file).take(MAX_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != length {
            return Err(NduDurableProjectionError::Corrupt);
        }
        if &bytes[..8] != MAGIC
            || &bytes[8..40] != binding.as_array()
            || &bytes[40..HEADER_BYTES] != Digest32::of_bytes(&bytes[..40]).as_array()
        {
            return Err(NduDurableProjectionError::BindingMismatch);
        }
        let body = &bytes[HEADER_BYTES..];
        if body.len() % RECORD_BYTES != 0 {
            return Err(NduDurableProjectionError::Corrupt);
        }
        let count = body.len() / RECORD_BYTES;
        if count > MAX_RECORDS {
            return Err(NduDurableProjectionError::Capacity);
        }

        let mut journal = NduProjectionJournalV1::new();
        let mut witnessed = minimum.record_count == 0;
        for raw in body.chunks_exact(RECORD_BYTES) {
            let stored = decode_entry(raw)?;
            let replayed = replay_entry(&mut journal, &stored)?;
            if replayed != stored {
                return Err(NduDurableProjectionError::Corrupt);
            }
            if stored.sequence == u64::from(minimum.record_count) {
                if stored.entry_digest != minimum.tip_digest {
                    return Err(NduDurableProjectionError::MissingAcknowledgedHistory);
                }
                witnessed = true;
            }
        }
        if !witnessed {
            return Err(NduDurableProjectionError::MissingAcknowledgedHistory);
        }
        file.sync_all()
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            journal,
            durable_length: length,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn anchor(&self) -> NduProjectionJournalAnchorV1 {
        self.journal.anchor()
    }

    pub fn entries(&self) -> Result<&[NduProjectionEntryV1], NduDurableProjectionError> {
        if self.poisoned {
            Err(NduDurableProjectionError::Poisoned)
        } else {
            Ok(self.journal.entries())
        }
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduDurableProjectionError> {
        if self.poisoned {
            return Err(NduDurableProjectionError::Poisoned);
        }
        Ok(self
            .journal
            .selected_projection_digest(objective_digest, subject_digest))
    }

    pub fn append_projection(
        &mut self,
        expected: NduProjectionJournalAnchorV1,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.commit(expected, |journal| {
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
        expected: NduProjectionJournalAnchorV1,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.commit(expected, |journal| {
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
        expected: NduProjectionJournalAnchorV1,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.commit(expected, |journal| {
            journal.revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
        })
    }

    fn commit(
        &mut self,
        expected: NduProjectionJournalAnchorV1,
        mutate: impl FnOnce(
            &mut NduProjectionJournalV1,
        ) -> Result<NduProjectionEntryV1, NduProjectionJournalError>,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        if self.poisoned {
            return Err(NduDurableProjectionError::Poisoned);
        }
        if expected != self.journal.anchor() {
            return Err(NduDurableProjectionError::Conflict);
        }
        if self.file.metadata()?.len() != self.durable_length {
            self.poisoned = true;
            return Err(NduDurableProjectionError::Indeterminate);
        }

        let mut candidate = self.journal.clone();
        let before = candidate.entries().len();
        let receipt = mutate(&mut candidate).map_err(NduDurableProjectionError::Semantic)?;
        if candidate.entries().len() == before {
            return Ok(receipt);
        }
        if candidate.entries().len() != before + 1 || before >= MAX_RECORDS {
            return Err(NduDurableProjectionError::Capacity);
        }
        let record = encode_entry(
            candidate
                .entries()
                .last()
                .ok_or(NduDurableProjectionError::Corrupt)?,
        );
        let next_length = self
            .durable_length
            .checked_add(record.len() as u64)
            .ok_or(NduDurableProjectionError::Capacity)?;
        if next_length > MAX_BYTES {
            return Err(NduDurableProjectionError::Capacity);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(NduDurableProjectionError::Corrupt);
        }
        self.file
            .write_all(&record)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        self.journal = candidate;
        self.durable_length = next_length;
        self.poisoned = false;
        Ok(receipt)
    }
}

fn acquire(file: &File, binding: Digest32) -> Result<(), NduDurableProjectionError> {
    if binding.is_zero() {
        return Err(NduDurableProjectionError::InvalidBinding);
    }
    if !file.metadata()?.is_file() {
        return Err(NduDurableProjectionError::NotRegular);
    }
    file.try_lock().map_err(|error| match error {
        TryLockError::WouldBlock => NduDurableProjectionError::Busy,
        TryLockError::Error(error) => NduDurableProjectionError::Io(error.kind()),
    })
}

fn validate_anchor(anchor: NduProjectionJournalAnchorV1) -> Result<(), NduDurableProjectionError> {
    let count = usize::try_from(anchor.record_count)
        .map_err(|_| NduDurableProjectionError::InvalidAnchor)?;
    if count > MAX_RECORDS || (anchor.record_count == 0) != anchor.tip_digest.is_zero() {
        return Err(NduDurableProjectionError::InvalidAnchor);
    }
    Ok(())
}

fn replay_entry(
    journal: &mut NduProjectionJournalV1,
    entry: &NduProjectionEntryV1,
) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
    let result = match entry.kind {
        NduProjectionKindV1::Preference | NduProjectionKindV1::Utility => journal
            .append_projection(
                entry.kind,
                entry.identity_digest,
                entry.objective_digest,
                entry.subject_digest,
                entry.payload_digest,
            ),
        NduProjectionKindV1::SelectedProjection => journal.select_projection(
            entry.identity_digest,
            entry.objective_digest,
            entry.subject_digest,
            entry.payload_digest,
        ),
        NduProjectionKindV1::Revocation => journal.revoke_projection(
            entry.identity_digest,
            entry.objective_digest,
            entry.subject_digest,
            entry.payload_digest,
        ),
    };
    result.map_err(NduDurableProjectionError::Semantic)
}

fn encode_entry(entry: &NduProjectionEntryV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(RECORD_BYTES);
    bytes.extend_from_slice(&entry.sequence.to_be_bytes());
    bytes.push(entry.kind.tag());
    for digest in [
        entry.identity_digest,
        entry.objective_digest,
        entry.subject_digest,
        entry.payload_digest,
        entry.predecessor_entry_digest,
        entry.entry_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

fn decode_entry(bytes: &[u8]) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
    if bytes.len() != RECORD_BYTES {
        return Err(NduDurableProjectionError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .map_err(|_| NduDurableProjectionError::Corrupt)?,
    );
    let kind = NduProjectionKindV1::from_tag(bytes[8])
        .map_err(NduDurableProjectionError::Semantic)?;
    let mut offset = 9;
    let mut next_digest = || -> Result<Digest32, NduDurableProjectionError> {
        let end = offset + 32;
        let raw: [u8; 32] = bytes
            .get(offset..end)
            .ok_or(NduDurableProjectionError::Corrupt)?
            .try_into()
            .map_err(|_| NduDurableProjectionError::Corrupt)?;
        offset = end;
        Ok(Digest32::from_array(raw))
    };
    Ok(NduProjectionEntryV1 {
        sequence,
        kind,
        identity_digest: next_digest()?,
        objective_digest: next_digest()?,
        subject_digest: next_digest()?,
        payload_digest: next_digest()?,
        predecessor_entry_digest: next_digest()?,
        entry_digest: next_digest()?,
    })
}

#[cfg(test)]
#[path = "durable_projection_store_tests.rs"]
mod tests;
