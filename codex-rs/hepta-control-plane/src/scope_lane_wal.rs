//! Scope-owned incremental WAL with typed, authority-free envelopes.
//!
//! A scope has one ordered lane.  Appends are idempotent by envelope digest,
//! reject owner and generation regressions, and bind every receipt to the
//! complete envelope plus its predecessor.  [`ScopeLaneFileWalV1`] provides the
//! host persistence seam: each complete frame is appended and fsynced before
//! the in-memory projection advances, while an incomplete crash tail is
//! truncated during reopen.  No value in this module carries runtime or effect
//! authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HCSLWA01";
const HEADER_BYTES: usize = MAGIC.len();
const MAX_LANES: usize = 4_096;
const MAX_RECORDS_PER_LANE: usize = 4_096;
const MAX_RECORDS: usize = 65_536;
const MAX_OWNER_BYTES: usize = 128;
const MAX_FRAME_BODY_BYTES: usize = 512;

/// Immutable, typed scope-owner message envelope.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeOwnerEnvelopeV1 {
    pub scope_digest: Digest32,
    pub owner_id: StableId,
    pub generation: Generation,
    pub message_digest: Digest32,
    pub payload_digest: Digest32,
}

impl ScopeOwnerEnvelopeV1 {
    pub fn new(
        scope_digest: Digest32,
        owner_id: StableId,
        generation: Generation,
        message_digest: Digest32,
        payload_digest: Digest32,
    ) -> Result<Self, ScopeLaneWalError> {
        if scope_digest.is_zero() {
            return Err(ScopeLaneWalError::EmptyDigest("scope"));
        }
        if message_digest.is_zero() {
            return Err(ScopeLaneWalError::EmptyDigest("message"));
        }
        if payload_digest.is_zero() {
            return Err(ScopeLaneWalError::EmptyDigest("payload"));
        }
        if owner_id.as_str().is_empty() {
            return Err(ScopeLaneWalError::InvalidOwner);
        }
        Ok(Self {
            scope_digest,
            owner_id,
            generation,
            message_digest,
            payload_digest,
        })
    }

    #[must_use]
    pub fn envelope_digest(&self) -> Digest32 {
        digest_envelope(self)
    }
}

/// One committed record in a scope lane.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeLaneEntryV1 {
    pub sequence: u64,
    pub envelope: ScopeOwnerEnvelopeV1,
    pub predecessor_entry_digest: Digest32,
    pub entry_digest: Digest32,
}

/// Non-authorizing append receipt bound to the exact committed record.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScopeLaneReceiptV1 {
    pub scope_digest: Digest32,
    pub sequence: u64,
    pub envelope_digest: Digest32,
    pub entry_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// In-memory projection of independent scope lanes.
#[derive(Clone, Debug, Eq, PartialEq, Default)]
pub struct ScopeLaneWalV1 {
    lanes: BTreeMap<Digest32, Vec<ScopeLaneEntryV1>>,
    identities: BTreeMap<(Digest32, Digest32), ()>,
}

impl ScopeLaneWalV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn lane_count(&self) -> usize {
        self.lanes.len()
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.identities.len()
    }

    #[must_use]
    pub fn entries(&self, scope_digest: Digest32) -> Option<&[ScopeLaneEntryV1]> {
        self.lanes.get(&scope_digest).map(Vec::as_slice)
    }

    /// Pure preflight. The file owner can encode and sync the exact entry
    /// without cloning all previously committed lanes and records.
    fn prepare_append(
        &self,
        envelope: &ScopeOwnerEnvelopeV1,
    ) -> Result<(ScopeLaneReceiptV1, Option<ScopeLaneEntryV1>), ScopeLaneWalError> {
        validate_envelope(envelope)?;
        let scope = envelope.scope_digest;
        let envelope_digest = envelope.envelope_digest();
        if self.identities.contains_key(&(scope, envelope_digest)) {
            let entry = self
                .lanes
                .get(&scope)
                .and_then(|entries| {
                    entries
                        .iter()
                        .find(|entry| entry.envelope.envelope_digest() == envelope_digest)
                })
                .ok_or(ScopeLaneWalError::CorruptEntryDigest)?;
            if &entry.envelope != envelope {
                return Err(ScopeLaneWalError::EnvelopeConflict);
            }
            return Ok((receipt_from_entry(entry), None));
        }
        if !self.lanes.contains_key(&scope) && self.lanes.len() >= MAX_LANES {
            return Err(ScopeLaneWalError::LaneLimitExceeded);
        }
        if self.identities.len() >= MAX_RECORDS {
            return Err(ScopeLaneWalError::RecordLimitExceeded);
        }
        let entries = self.lanes.get(&scope);
        if entries.is_some_and(|records| records.len() >= MAX_RECORDS_PER_LANE) {
            return Err(ScopeLaneWalError::LaneRecordLimitExceeded);
        }
        let previous = entries.and_then(|records| records.last());
        if let Some(previous) = previous {
            if previous.envelope.owner_id != envelope.owner_id {
                return Err(ScopeLaneWalError::OwnerConflict);
            }
            if envelope.generation < previous.envelope.generation {
                return Err(ScopeLaneWalError::GenerationRegression);
            }
        }
        let sequence = u64::try_from(entries.map_or(0, Vec::len))
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(ScopeLaneWalError::LaneRecordLimitExceeded)?;
        let predecessor_entry_digest = previous.map_or(Digest32::ZERO, |entry| entry.entry_digest);
        let entry_digest = digest_entry(sequence, envelope, predecessor_entry_digest);
        let entry = ScopeLaneEntryV1 {
            sequence,
            envelope: envelope.clone(),
            predecessor_entry_digest,
            entry_digest,
        };
        Ok((receipt_from_entry(&entry), Some(entry)))
    }

    pub fn append(
        &mut self,
        envelope: ScopeOwnerEnvelopeV1,
    ) -> Result<ScopeLaneReceiptV1, ScopeLaneWalError> {
        let (receipt, pending) = self.prepare_append(&envelope)?;
        if let Some(entry) = pending {
            self.identities
                .insert((envelope.scope_digest, envelope.envelope_digest()), ());
            self.lanes
                .entry(envelope.scope_digest)
                .or_default()
                .push(entry);
        }
        Ok(receipt)
    }

    #[must_use]
    pub fn export_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(
            &u32::try_from(self.lane_count())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(
            &u32::try_from(self.record_count())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for entries in self.lanes.values() {
            for entry in entries {
                let body = encode_entry_body(entry);
                bytes.extend_from_slice(
                    &u32::try_from(body.len()).unwrap_or(u32::MAX).to_be_bytes(),
                );
                bytes.extend_from_slice(&body);
                bytes.extend_from_slice(Digest32::of_bytes(&body).as_array());
            }
        }
        bytes
    }

    pub fn reopen(bytes: &[u8]) -> Result<Self, ScopeLaneWalError> {
        if bytes.len() < HEADER_BYTES + 8 {
            return Err(ScopeLaneWalError::Truncated);
        }
        if &bytes[..HEADER_BYTES] != MAGIC {
            return Err(ScopeLaneWalError::CorruptHeader);
        }
        let mut offset = HEADER_BYTES;
        let lane_count = usize::try_from(read_u32(bytes, &mut offset)?)
            .map_err(|_| ScopeLaneWalError::LaneLimitExceeded)?;
        let record_count = usize::try_from(read_u32(bytes, &mut offset)?)
            .map_err(|_| ScopeLaneWalError::RecordLimitExceeded)?;
        if lane_count > MAX_LANES {
            return Err(ScopeLaneWalError::LaneLimitExceeded);
        }
        if record_count > MAX_RECORDS {
            return Err(ScopeLaneWalError::RecordLimitExceeded);
        }
        let mut wal = Self::new();
        for _ in 0..record_count {
            let body_len = usize::try_from(read_u32(bytes, &mut offset)?)
                .map_err(|_| ScopeLaneWalError::FrameTooLarge)?;
            if !(1..=MAX_FRAME_BODY_BYTES).contains(&body_len) {
                return Err(ScopeLaneWalError::FrameTooLarge);
            }
            let body = read_slice(bytes, &mut offset, body_len)?;
            let checksum = read_digest(bytes, &mut offset)?;
            if Digest32::of_bytes(body) != checksum {
                return Err(ScopeLaneWalError::CorruptFrame);
            }
            let (entry, encoded_sequence, encoded_predecessor, encoded_entry_digest) =
                decode_entry_body(body)?;
            if wal.identities.contains_key(&(
                entry.envelope.scope_digest,
                entry.envelope.envelope_digest(),
            )) {
                return Err(ScopeLaneWalError::DuplicateSerializedEnvelope);
            }
            let receipt = wal.append(entry.envelope)?;
            if receipt.sequence != encoded_sequence
                || receipt.entry_digest != encoded_entry_digest
                || wal
                    .entries(receipt.scope_digest)
                    .and_then(|entries| entries.last())
                    .map(|entry| entry.predecessor_entry_digest)
                    != Some(encoded_predecessor)
            {
                return Err(ScopeLaneWalError::CorruptChain);
            }
        }
        if wal.lane_count() != lane_count || wal.record_count() != record_count {
            return Err(ScopeLaneWalError::CorruptCount);
        }
        if offset != bytes.len() {
            return Err(ScopeLaneWalError::TrailingBytes);
        }
        Ok(wal)
    }
}

/// File-backed incremental WAL. The file lock prevents concurrent writers;
/// every successful append reaches `sync_all` before the projection advances.
pub struct ScopeLaneFileWalV1 {
    file: LockedFile,
    wal: ScopeLaneWalV1,
    poisoned: bool,
}

impl ScopeLaneFileWalV1 {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ScopeLaneWalError> {
        let mut options = OpenOptions::new();
        // On Windows, append-only handles may deny SetEndOfFile while repairing
        // an incomplete frame. Keep WRITE_DATA and seek to EOF under the
        // exclusive owner lock in append_frame; retain O_APPEND elsewhere.
        options.create(true).read(true).write(true);
        #[cfg(not(windows))]
        options.append(true);
        let file = options
            .open(path.as_ref())
            .map_err(ScopeLaneWalError::from)?;
        let mut file = LockedFile::acquire(file)?;
        let physical_len = file.0.metadata().map_err(ScopeLaneWalError::from)?.len();
        if physical_len == 0 {
            file.0.write_all(MAGIC).map_err(ScopeLaneWalError::from)?;
            file.0.sync_all().map_err(ScopeLaneWalError::from)?;
            // Persist the filename itself, not merely its inode contents.
            #[cfg(unix)]
            {
                let parent = path
                    .as_ref()
                    .parent()
                    .filter(|parent| !parent.as_os_str().is_empty())
                    .unwrap_or_else(|| Path::new("."));
                File::open(parent)
                    .and_then(|directory| directory.sync_all())
                    .map_err(ScopeLaneWalError::from)?;
            }
        } else {
            if physical_len < HEADER_BYTES as u64 {
                return Err(ScopeLaneWalError::CorruptHeader);
            }
            let mut header = [0_u8; HEADER_BYTES];
            file.0
                .seek(SeekFrom::Start(0))
                .and_then(|_| file.0.read_exact(&mut header))
                .map_err(ScopeLaneWalError::from)?;
            if &header != MAGIC {
                return Err(ScopeLaneWalError::CorruptHeader);
            }
        }

        let physical_len = file.0.metadata().map_err(ScopeLaneWalError::from)?.len();
        let mut offset = HEADER_BYTES as u64;
        let mut wal = ScopeLaneWalV1::new();
        while offset < physical_len {
            let remaining = physical_len - offset;
            if remaining < 4 {
                truncate_tail(&mut file.0, offset)?;
                break;
            }
            let mut length_bytes = [0_u8; 4];
            file.0
                .seek(SeekFrom::Start(offset))
                .and_then(|_| file.0.read_exact(&mut length_bytes))
                .map_err(ScopeLaneWalError::from)?;
            let body_len = usize::try_from(u32::from_be_bytes(length_bytes))
                .map_err(|_| ScopeLaneWalError::FrameTooLarge)?;
            if !(1..=MAX_FRAME_BODY_BYTES).contains(&body_len) {
                return Err(ScopeLaneWalError::FrameTooLarge);
            }
            let frame_bytes = 4_u64
                .checked_add(body_len as u64)
                .and_then(|value| value.checked_add(32))
                .ok_or(ScopeLaneWalError::FrameTooLarge)?;
            if remaining < frame_bytes {
                truncate_tail(&mut file.0, offset)?;
                break;
            }
            let mut body = vec![0_u8; body_len];
            let mut checksum = [0_u8; 32];
            file.0
                .read_exact(&mut body)
                .and_then(|_| file.0.read_exact(&mut checksum))
                .map_err(ScopeLaneWalError::from)?;
            if Digest32::of_bytes(&body) != Digest32::from_array(checksum) {
                return Err(ScopeLaneWalError::CorruptFrame);
            }
            let (entry, encoded_sequence, encoded_predecessor, encoded_entry_digest) =
                decode_entry_body(&body)?;
            if wal.identities.contains_key(&(
                entry.envelope.scope_digest,
                entry.envelope.envelope_digest(),
            )) {
                return Err(ScopeLaneWalError::DuplicateSerializedEnvelope);
            }
            let receipt = wal.append(entry.envelope)?;
            if receipt.sequence != encoded_sequence
                || receipt.entry_digest != encoded_entry_digest
                || wal
                    .entries(receipt.scope_digest)
                    .and_then(|entries| entries.last())
                    .map(|entry| entry.predecessor_entry_digest)
                    != Some(encoded_predecessor)
            {
                return Err(ScopeLaneWalError::CorruptChain);
            }
            offset = offset
                .checked_add(frame_bytes)
                .ok_or(ScopeLaneWalError::FrameTooLarge)?;
        }
        file.0
            .seek(SeekFrom::End(0))
            .map_err(ScopeLaneWalError::from)?;
        Ok(Self {
            file,
            wal,
            poisoned: false,
        })
    }

    #[must_use]
    pub fn wal(&self) -> &ScopeLaneWalV1 {
        &self.wal
    }

    pub fn append(
        &mut self,
        envelope: ScopeOwnerEnvelopeV1,
    ) -> Result<ScopeLaneReceiptV1, ScopeLaneWalError> {
        if self.poisoned {
            return Err(ScopeLaneWalError::Poisoned);
        }
        let (receipt, pending) = self.wal.prepare_append(&envelope)?;
        let Some(entry) = pending else {
            return Ok(receipt);
        };
        let body = encode_entry_body(&entry);
        // If write/fsync fails, a partial physical frame may be present.
        // Poison this open handle until a fresh locked reopen repairs its tail.
        self.poisoned = true;
        append_frame(&mut self.file.0, &body)?;
        let committed = self.wal.append(envelope)?;
        if committed != receipt {
            return Err(ScopeLaneWalError::CorruptEntryDigest);
        }
        self.poisoned = false;
        Ok(receipt)
    }
}

struct LockedFile(File);

impl LockedFile {
    fn acquire(file: File) -> Result<Self, ScopeLaneWalError> {
        if !file.metadata().map_err(ScopeLaneWalError::from)?.is_file() {
            return Err(ScopeLaneWalError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(ScopeLaneWalError::Busy),
            Err(TryLockError::Error(error)) => Err(ScopeLaneWalError::from(error)),
        }
    }
}

impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

fn validate_envelope(envelope: &ScopeOwnerEnvelopeV1) -> Result<(), ScopeLaneWalError> {
    if envelope.scope_digest.is_zero() {
        return Err(ScopeLaneWalError::EmptyDigest("scope"));
    }
    if envelope.message_digest.is_zero() {
        return Err(ScopeLaneWalError::EmptyDigest("message"));
    }
    if envelope.payload_digest.is_zero() {
        return Err(ScopeLaneWalError::EmptyDigest("payload"));
    }
    if envelope.owner_id.as_str().is_empty() || envelope.owner_id.as_str().len() > MAX_OWNER_BYTES {
        return Err(ScopeLaneWalError::InvalidOwner);
    }
    Ok(())
}

fn receipt_from_entry(entry: &ScopeLaneEntryV1) -> ScopeLaneReceiptV1 {
    ScopeLaneReceiptV1 {
        scope_digest: entry.envelope.scope_digest,
        sequence: entry.sequence,
        envelope_digest: entry.envelope.envelope_digest(),
        entry_digest: entry.entry_digest,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn digest_envelope(envelope: &ScopeOwnerEnvelopeV1) -> Digest32 {
    let owner = envelope.owner_id.as_str().as_bytes();
    let owner_len = u16::try_from(owner.len()).unwrap_or(u16::MAX);
    let mut bytes = Vec::with_capacity(8 + 32 + 2 + owner.len() + 8 + 64);
    bytes.extend_from_slice(b"hepta.control.scope-owner-envelope.v1\0");
    bytes.extend_from_slice(envelope.scope_digest.as_array());
    bytes.extend_from_slice(&owner_len.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(&envelope.generation.get().to_be_bytes());
    bytes.extend_from_slice(envelope.message_digest.as_array());
    bytes.extend_from_slice(envelope.payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_entry(
    sequence: u64,
    envelope: &ScopeOwnerEnvelopeV1,
    predecessor_entry_digest: Digest32,
) -> Digest32 {
    let envelope_digest = envelope.envelope_digest();
    Digest32::of_parts(&[
        b"hepta.control.scope-lane-entry.v1\0",
        &sequence.to_be_bytes(),
        envelope_digest.as_array(),
        predecessor_entry_digest.as_array(),
    ])
}

fn encode_entry_body(entry: &ScopeLaneEntryV1) -> Vec<u8> {
    let owner = entry.envelope.owner_id.as_str().as_bytes();
    let owner_len = u16::try_from(owner.len()).unwrap_or(u16::MAX);
    let mut bytes = Vec::with_capacity(8 + 32 + 8 + 8 + 2 + owner.len() + 128);
    bytes.extend_from_slice(entry.envelope.scope_digest.as_array());
    bytes.extend_from_slice(&entry.sequence.to_be_bytes());
    bytes.extend_from_slice(&entry.envelope.generation.get().to_be_bytes());
    bytes.extend_from_slice(&owner_len.to_be_bytes());
    bytes.extend_from_slice(owner);
    bytes.extend_from_slice(entry.envelope.message_digest.as_array());
    bytes.extend_from_slice(entry.envelope.payload_digest.as_array());
    bytes.extend_from_slice(entry.predecessor_entry_digest.as_array());
    bytes.extend_from_slice(entry.entry_digest.as_array());
    bytes
}

fn decode_entry_body(
    body: &[u8],
) -> Result<(ScopeLaneEntryV1, u64, Digest32, Digest32), ScopeLaneWalError> {
    let mut offset = 0;
    let scope_digest = read_digest(body, &mut offset)?;
    let sequence = read_u64(body, &mut offset)?;
    let generation = Generation::new(read_u64(body, &mut offset)?)
        .map_err(|_| ScopeLaneWalError::InvalidGeneration)?;
    let owner_len = usize::from(read_u16(body, &mut offset)?);
    if owner_len == 0 || owner_len > MAX_OWNER_BYTES {
        return Err(ScopeLaneWalError::InvalidOwner);
    }
    let owner_bytes = read_slice(body, &mut offset, owner_len)?;
    let owner_text =
        std::str::from_utf8(owner_bytes).map_err(|_| ScopeLaneWalError::InvalidOwner)?;
    let owner_id = StableId::new(owner_text).map_err(|_| ScopeLaneWalError::InvalidOwner)?;
    let message_digest = read_digest(body, &mut offset)?;
    let payload_digest = read_digest(body, &mut offset)?;
    let predecessor_entry_digest = read_digest(body, &mut offset)?;
    let encoded_entry_digest = read_digest(body, &mut offset)?;
    if offset != body.len() {
        return Err(ScopeLaneWalError::TrailingBytes);
    }
    let envelope = ScopeOwnerEnvelopeV1::new(
        scope_digest,
        owner_id,
        generation,
        message_digest,
        payload_digest,
    )?;
    let entry_digest = digest_entry(sequence, &envelope, predecessor_entry_digest);
    if entry_digest != encoded_entry_digest {
        return Err(ScopeLaneWalError::CorruptEntryDigest);
    }
    Ok((
        ScopeLaneEntryV1 {
            sequence,
            envelope,
            predecessor_entry_digest,
            entry_digest,
        },
        sequence,
        predecessor_entry_digest,
        encoded_entry_digest,
    ))
}

fn append_frame(file: &mut File, body: &[u8]) -> Result<(), ScopeLaneWalError> {
    if !(1..=MAX_FRAME_BODY_BYTES).contains(&body.len()) {
        return Err(ScopeLaneWalError::FrameTooLarge);
    }
    let body_len = u32::try_from(body.len()).map_err(|_| ScopeLaneWalError::FrameTooLarge)?;
    file.seek(SeekFrom::End(0))
        .map_err(ScopeLaneWalError::from)?;
    file.write_all(&body_len.to_be_bytes())
        .and_then(|_| file.write_all(body))
        .and_then(|_| file.write_all(Digest32::of_bytes(body).as_array()))
        .and_then(|_| file.sync_all())
        .map_err(ScopeLaneWalError::from)
}

fn truncate_tail(file: &mut File, offset: u64) -> Result<(), ScopeLaneWalError> {
    file.set_len(offset)
        .and_then(|_| file.sync_all())
        .map_err(ScopeLaneWalError::from)
}

fn read_u16(bytes: &[u8], offset: &mut usize) -> Result<u16, ScopeLaneWalError> {
    let end = (*offset)
        .checked_add(2)
        .ok_or(ScopeLaneWalError::Truncated)?;
    let value = u16::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ScopeLaneWalError::Truncated)?
            .try_into()
            .map_err(|_| ScopeLaneWalError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u32(bytes: &[u8], offset: &mut usize) -> Result<u32, ScopeLaneWalError> {
    let end = (*offset)
        .checked_add(4)
        .ok_or(ScopeLaneWalError::Truncated)?;
    let value = u32::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ScopeLaneWalError::Truncated)?
            .try_into()
            .map_err(|_| ScopeLaneWalError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_u64(bytes: &[u8], offset: &mut usize) -> Result<u64, ScopeLaneWalError> {
    let end = (*offset)
        .checked_add(8)
        .ok_or(ScopeLaneWalError::Truncated)?;
    let value = u64::from_be_bytes(
        bytes
            .get(*offset..end)
            .ok_or(ScopeLaneWalError::Truncated)?
            .try_into()
            .map_err(|_| ScopeLaneWalError::Truncated)?,
    );
    *offset = end;
    Ok(value)
}

fn read_slice<'a>(
    bytes: &'a [u8],
    offset: &mut usize,
    length: usize,
) -> Result<&'a [u8], ScopeLaneWalError> {
    let end = (*offset)
        .checked_add(length)
        .ok_or(ScopeLaneWalError::Truncated)?;
    let value = bytes
        .get(*offset..end)
        .ok_or(ScopeLaneWalError::Truncated)?;
    *offset = end;
    Ok(value)
}

fn read_digest(bytes: &[u8], offset: &mut usize) -> Result<Digest32, ScopeLaneWalError> {
    let array: [u8; 32] = read_slice(bytes, offset, 32)?
        .try_into()
        .map_err(|_| ScopeLaneWalError::Truncated)?;
    Ok(Digest32::from_array(array))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScopeLaneWalError {
    EmptyDigest(&'static str),
    InvalidOwner,
    InvalidGeneration,
    LaneLimitExceeded,
    RecordLimitExceeded,
    LaneRecordLimitExceeded,
    OwnerConflict,
    GenerationRegression,
    EnvelopeConflict,
    CorruptHeader,
    CorruptFrame,
    CorruptChain,
    CorruptEntryDigest,
    CorruptCount,
    DuplicateSerializedEnvelope,
    FrameTooLarge,
    Truncated,
    TrailingBytes,
    Poisoned,
    Busy,
    NotRegular,
    Io(std::io::ErrorKind),
}

impl fmt::Display for ScopeLaneWalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ScopeLaneWalError {}

impl From<std::io::Error> for ScopeLaneWalError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

#[cfg(test)]
#[path = "scope_lane_wal_tests.rs"]
mod tests;
