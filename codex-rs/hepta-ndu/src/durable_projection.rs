//! Opt-in durable writer candidate for NDU projection state.
//!
//! The host authorizes and opens the file. This module acquires an exclusive
//! cooperative lock, validates semantic mutations before writing, appends one
//! fixed canonical frame, calls `sync_all`, and only then publishes the same
//! mutation in memory. Containing-directory durability, access control and
//! external anchor protection remain host responsibilities.

use std::error::Error;
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

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalError;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

const MAGIC: &[u8; 8] = b"HNDUDR01";
const HEADER_BYTES: usize = 8 + 32 + 32;
const FRAME_BYTES: usize = 8 + 1 + 32 * 6;
const MAX_RECORDS: usize = 4096;
const MAX_BYTES: u64 = HEADER_BYTES as u64 + MAX_RECORDS as u64 * FRAME_BYTES as u64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionAnchorV1 {
    pub sequence: u64,
    pub entry_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduProjectionRecoveryV1 {
    Unacknowledged,
    Acknowledged(NduProjectionAnchorV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduDurableProjectionError {
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
    Corrupt,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Semantic(NduProjectionJournalError),
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

impl From<NduProjectionJournalError> for NduDurableProjectionError {
    fn from(error: NduProjectionJournalError) -> Self {
        Self::Semantic(error)
    }
}

struct LockedFile(File);

impl LockedFile {
    fn acquire(file: File) -> Result<Self, NduDurableProjectionError> {
        if !file.metadata()?.is_file() {
            return Err(NduDurableProjectionError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(NduDurableProjectionError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for LockedFile {
    type Target = File;

    fn deref(&self) -> &File {
        &self.0
    }
}

impl DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

/// Durable owner-local projection writer candidate.
///
/// An external anchor is a minimum acknowledged history witness. It must be
/// retained outside this file under an independently protected boundary. The
/// anchor prevents a hostile or accidental wholesale rewrite from being trusted
/// merely because the rewritten file contains a self-consistent hash chain.
pub struct NduDurableProjectionJournalV1 {
    file: LockedFile,
    binding_digest: Digest32,
    core: NduProjectionJournalV1,
    max_records: usize,
    durable_length: u64,
    poisoned: bool,
}

impl NduDurableProjectionJournalV1 {
    /// Create an empty durable store. The host owns file creation and directory
    /// synchronization; this function refuses to overwrite existing bytes.
    pub fn create(
        file: File,
        binding_digest: Digest32,
        max_records: usize,
    ) -> Result<Self, NduDurableProjectionError> {
        validate_domain(binding_digest, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        if file.metadata()?.len() != 0 {
            return Err(NduDurableProjectionError::AlreadyInitialized);
        }
        let header = encode_header(binding_digest);
        file.seek(SeekFrom::Start(0))?;
        file.write_all(&header)
            .and_then(|()| file.sync_all())
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        Ok(Self {
            file,
            binding_digest,
            core: NduProjectionJournalV1::new(),
            max_records,
            durable_length: HEADER_BYTES as u64,
            poisoned: false,
        })
    }

    /// Recover complete frames and reconcile an incomplete unacknowledged tail.
    /// An acknowledged external anchor must exist and match exactly.
    pub fn recover(
        file: File,
        binding_digest: Digest32,
        max_records: usize,
        recovery: NduProjectionRecoveryV1,
    ) -> Result<Self, NduDurableProjectionError> {
        validate_domain(binding_digest, max_records)?;
        validate_recovery(recovery, max_records)?;
        let mut file = LockedFile::acquire(file)?;
        let (core, cursor, length) =
            replay(&mut file, binding_digest, max_records, recovery)?;
        if cursor != length {
            file.set_len(cursor)
                .map_err(|_| NduDurableProjectionError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        }
        Ok(Self {
            file,
            binding_digest,
            core,
            max_records,
            durable_length: cursor,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn entries(&self) -> Result<&[NduProjectionEntryV1], NduDurableProjectionError> {
        if self.poisoned {
            Err(NduDurableProjectionError::Poisoned)
        } else {
            Ok(self.core.entries())
        }
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduDurableProjectionError> {
        if self.poisoned {
            Err(NduDurableProjectionError::Poisoned)
        } else {
            Ok(self
                .core
                .selected_projection_digest(objective_digest, subject_digest))
        }
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<NduProjectionAnchorV1>, NduDurableProjectionError> {
        let entries = self.entries()?;
        Ok(entries.last().map(|entry| NduProjectionAnchorV1 {
            sequence: entry.sequence,
            entry_digest: entry.entry_digest,
        }))
    }

    pub fn append_projection(
        &mut self,
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.require_healthy()?;
        let mut prepared_core = self.core.clone();
        let prepared = prepared_core.append_projection(
            kind,
            identity_digest,
            objective_digest,
            subject_digest,
            payload_digest,
        )?;
        if self.is_idempotent(&prepared) {
            return Ok(prepared);
        }
        self.persist_prepared(&prepared)?;
        let published = self
            .core
            .append_projection(
                kind,
                identity_digest,
                objective_digest,
                subject_digest,
                payload_digest,
            )
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        self.finish_publish(prepared, published)
    }

    pub fn select_projection(
        &mut self,
        operation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.require_healthy()?;
        let mut prepared_core = self.core.clone();
        let prepared = prepared_core.select_projection(
            operation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )?;
        if self.is_idempotent(&prepared) {
            return Ok(prepared);
        }
        self.persist_prepared(&prepared)?;
        let published = self
            .core
            .select_projection(
                operation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        self.finish_publish(prepared, published)
    }

    pub fn revoke_projection(
        &mut self,
        revocation_identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        self.require_healthy()?;
        let mut prepared_core = self.core.clone();
        let prepared = prepared_core.revoke_projection(
            revocation_identity_digest,
            objective_digest,
            subject_digest,
            projection_digest,
        )?;
        if self.is_idempotent(&prepared) {
            return Ok(prepared);
        }
        self.persist_prepared(&prepared)?;
        let published = self
            .core
            .revoke_projection(
                revocation_identity_digest,
                objective_digest,
                subject_digest,
                projection_digest,
            )
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        self.finish_publish(prepared, published)
    }

    fn require_healthy(&self) -> Result<(), NduDurableProjectionError> {
        if self.poisoned {
            Err(NduDurableProjectionError::Poisoned)
        } else {
            Ok(())
        }
    }

    fn is_idempotent(&self, entry: &NduProjectionEntryV1) -> bool {
        usize::try_from(entry.sequence)
            .ok()
            .is_some_and(|sequence| sequence <= self.core.entries().len())
    }

    fn persist_prepared(
        &mut self,
        entry: &NduProjectionEntryV1,
    ) -> Result<(), NduDurableProjectionError> {
        if self.core.entries().len() >= self.max_records {
            return Err(NduDurableProjectionError::Capacity);
        }
        let expected_sequence = u64::try_from(self.core.entries().len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(NduDurableProjectionError::Capacity)?;
        if entry.sequence != expected_sequence {
            return Err(NduDurableProjectionError::Corrupt);
        }
        let frame = encode_entry(entry);
        let next_length = self
            .durable_length
            .checked_add(frame.len() as u64)
            .ok_or(NduDurableProjectionError::Capacity)?;
        if next_length > MAX_BYTES {
            return Err(NduDurableProjectionError::Capacity);
        }

        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(NduDurableProjectionError::Corrupt);
        }
        self.file
            .write_all(&frame)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| NduDurableProjectionError::Indeterminate)?;
        self.durable_length = next_length;
        Ok(())
    }

    fn finish_publish(
        &mut self,
        prepared: NduProjectionEntryV1,
        published: NduProjectionEntryV1,
    ) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
        if prepared != published {
            return Err(NduDurableProjectionError::Indeterminate);
        }
        self.poisoned = false;
        Ok(published)
    }
}

fn validate_domain(
    binding_digest: Digest32,
    max_records: usize,
) -> Result<(), NduDurableProjectionError> {
    if binding_digest.is_zero() {
        return Err(NduDurableProjectionError::InvalidBinding);
    }
    if !(1..=MAX_RECORDS).contains(&max_records) {
        return Err(NduDurableProjectionError::InvalidLimit);
    }
    Ok(())
}

fn validate_recovery(
    recovery: NduProjectionRecoveryV1,
    max_records: usize,
) -> Result<(), NduDurableProjectionError> {
    if let NduProjectionRecoveryV1::Acknowledged(anchor) = recovery {
        if anchor.sequence == 0
            || usize::try_from(anchor.sequence)
                .ok()
                .is_none_or(|sequence| sequence > max_records)
            || anchor.entry_digest.is_zero()
        {
            return Err(NduDurableProjectionError::InvalidAnchor);
        }
    }
    Ok(())
}

fn encode_header(binding_digest: Digest32) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(binding_digest.as_array());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    bytes
}

fn replay(
    file: &mut File,
    binding_digest: Digest32,
    max_records: usize,
    recovery: NduProjectionRecoveryV1,
) -> Result<(NduProjectionJournalV1, u64, u64), NduDurableProjectionError> {
    let length = file.metadata()?.len();
    if length < HEADER_BYTES as u64 {
        return Err(NduDurableProjectionError::MissingHeader);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut header = vec![0_u8; HEADER_BYTES];
    file.read_exact(&mut header)?;
    if &header[..8] != MAGIC {
        return Err(NduDurableProjectionError::Corrupt);
    }
    let stored_binding = Digest32::from_array(
        header[8..40]
            .try_into()
            .map_err(|_| NduDurableProjectionError::Corrupt)?,
    );
    if stored_binding != binding_digest {
        return Err(NduDurableProjectionError::BindingMismatch);
    }
    let stored_header_digest = Digest32::from_array(
        header[40..72]
            .try_into()
            .map_err(|_| NduDurableProjectionError::Corrupt)?,
    );
    if stored_header_digest != Digest32::of_bytes(&header[..40]) {
        return Err(NduDurableProjectionError::Corrupt);
    }

    let payload_bytes = length - HEADER_BYTES as u64;
    let complete_frames = payload_bytes / FRAME_BYTES as u64;
    if usize::try_from(complete_frames)
        .ok()
        .is_none_or(|count| count > max_records)
    {
        return Err(NduDurableProjectionError::Capacity);
    }
    let mut core = NduProjectionJournalV1::new();
    let mut cursor = HEADER_BYTES as u64;
    let mut anchor_seen = false;

    for _ in 0..complete_frames {
        let mut frame = vec![0_u8; FRAME_BYTES];
        file.read_exact(&mut frame)?;
        let decoded = decode_entry(&frame)?;
        let published = apply_decoded(&mut core, &decoded)?;
        if published != decoded {
            return Err(NduDurableProjectionError::Corrupt);
        }
        if let NduProjectionRecoveryV1::Acknowledged(anchor) = recovery
            && decoded.sequence == anchor.sequence
        {
            if decoded.entry_digest != anchor.entry_digest {
                return Err(NduDurableProjectionError::AnchorMismatch);
            }
            anchor_seen = true;
        }
        cursor = cursor
            .checked_add(FRAME_BYTES as u64)
            .ok_or(NduDurableProjectionError::Capacity)?;
    }

    if let NduProjectionRecoveryV1::Acknowledged(anchor) = recovery
        && !anchor_seen
    {
        if anchor.sequence > complete_frames {
            return Err(NduDurableProjectionError::AcknowledgedHistoryMissing);
        }
        return Err(NduDurableProjectionError::AnchorMismatch);
    }

    if length != cursor {
        return Ok((core, cursor, length));
    }
    Ok((core, cursor, cursor))
}

fn apply_decoded(
    journal: &mut NduProjectionJournalV1,
    entry: &NduProjectionEntryV1,
) -> Result<NduProjectionEntryV1, NduDurableProjectionError> {
    let published = match entry.kind {
        NduProjectionKindV1::Preference | NduProjectionKindV1::Utility => {
            journal.append_projection(
                entry.kind,
                entry.identity_digest,
                entry.objective_digest,
                entry.subject_digest,
                entry.payload_digest,
            )?
        }
        NduProjectionKindV1::SelectedProjection => journal.select_projection(
            entry.identity_digest,
            entry.objective_digest,
            entry.subject_digest,
            entry.payload_digest,
        )?,
        NduProjectionKindV1::Revocation => journal.revoke_projection(
            entry.identity_digest,
            entry.objective_digest,
            entry.subject_digest,
            entry.payload_digest,
        )?,
    };
    Ok(published)
}

fn encode_entry(entry: &NduProjectionEntryV1) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(FRAME_BYTES);
    bytes.extend_from_slice(&entry.sequence.to_be_bytes());
    bytes.push(kind_tag(entry.kind));
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
    if bytes.len() != FRAME_BYTES {
        return Err(NduDurableProjectionError::Corrupt);
    }
    let sequence = u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .map_err(|_| NduDurableProjectionError::Corrupt)?,
    );
    let kind = kind_from_tag(bytes[8])?;
    let mut offset = 9;
    let identity_digest = read_digest(bytes, &mut offset)?;
    let objective_digest = read_digest(bytes, &mut offset)?;
    let subject_digest = read_digest(bytes, &mut offset)?;
    let payload_digest = read_digest(bytes, &mut offset)?;
    let predecessor_entry_digest = read_digest(bytes, &mut offset)?;
    let entry_digest = read_digest(bytes, &mut offset)?;
    Ok(NduProjectionEntryV1 {
        sequence,
        kind,
        identity_digest,
        objective_digest,
        subject_digest,
        payload_digest,
        predecessor_entry_digest,
        entry_digest,
    })
}

fn read_digest(
    bytes: &[u8],
    offset: &mut usize,
) -> Result<Digest32, NduDurableProjectionError> {
    let end = (*offset)
        .checked_add(32)
        .ok_or(NduDurableProjectionError::Corrupt)?;
    let array = bytes
        .get(*offset..end)
        .ok_or(NduDurableProjectionError::Corrupt)?
        .try_into()
        .map_err(|_| NduDurableProjectionError::Corrupt)?;
    *offset = end;
    Ok(Digest32::from_array(array))
}

const fn kind_tag(kind: NduProjectionKindV1) -> u8 {
    match kind {
        NduProjectionKindV1::Preference => 0,
        NduProjectionKindV1::Utility => 1,
        NduProjectionKindV1::SelectedProjection => 2,
        NduProjectionKindV1::Revocation => 3,
    }
}

fn kind_from_tag(value: u8) -> Result<NduProjectionKindV1, NduDurableProjectionError> {
    match value {
        0 => Ok(NduProjectionKindV1::Preference),
        1 => Ok(NduProjectionKindV1::Utility),
        2 => Ok(NduProjectionKindV1::SelectedProjection),
        3 => Ok(NduProjectionKindV1::Revocation),
        _ => Err(NduDurableProjectionError::Corrupt),
    }
}

#[cfg(test)]
#[path = "durable_projection_tests.rs"]
mod tests;
