//! Protected-frame terminal journal for control.engineering plasticity.
//!
//! A frame has a magic prefix, body length and complement, a checksum-bound body,
//! and a footer that repeats the length/complement plus the frame digest. Recovery
//! truncates only a final frame whose valid prefix names bytes that are not fully
//! present and for which no complete valid footer exists. A complete frame with a
//! damaged length, body, footer, sequence or predecessor fails closed and remains
//! byte-for-byte available for incident recovery.

use std::collections::BTreeMap;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::legacy::DurableIterationJournalErrorV1;
use super::legacy::IterationPlasticityKindV1;
use super::legacy::IterationPlasticityTerminalDispositionV1;
use super::legacy::IterationPlasticityTerminalReceiptV1;

const JOURNAL_MAGIC: &[u8; 8] = b"HPTITE02";
const FRAME_MAGIC: &[u8; 8] = b"HPTIFR02";
const FOOTER_MAGIC: &[u8; 8] = b"HPTIFT02";
const JOURNAL_VERSION: u16 = 2;
const HEADER_PREFIX_BYTES: usize = 8 + 2 + 32 + 8 + 4;
const HEADER_BYTES: usize = HEADER_PREFIX_BYTES + 32;
const FRAME_PREFIX_BYTES: usize = 8 + 4 + 4;
const FRAME_FOOTER_BYTES: usize = 8 + 4 + 4 + 32;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_FRAME_BODY_BYTES: usize = MAX_FRAME_BYTES - FRAME_PREFIX_BYTES - FRAME_FOOTER_BYTES;
const MAX_JOURNAL_RECORDS: usize = 65_536;
const MAX_ID_BYTES: usize = 4_096;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableIterationJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(DurableIterationJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableIterationJournalErrorV1::Busy),
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

/// Durable terminal bookkeeping owned by control.engineering. It cannot mutate a
/// proposal registry, selected artifact, topology or runtime authority.
pub struct DurableIterationTerminalJournalV1 {
    file: LockedFile,
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    by_identity: BTreeMap<Digest32, IterationPlasticityTerminalReceiptV1>,
    frame_digests: Vec<Digest32>,
    poisoned: bool,
}

impl DurableIterationTerminalJournalV1 {
    pub fn bootstrap_new(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        Self::open_inner(file, scope, writer_fence, maximum_records, true)
    }

    pub fn reopen(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        Self::open_inner(file, scope, writer_fence, maximum_records, false)
    }

    fn open_inner(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        bootstrap: bool,
    ) -> Result<Self, DurableIterationJournalErrorV1> {
        validate_journal_context(scope, writer_fence, maximum_records)?;
        let expected_header = encode_header(scope, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let initial_length = file.metadata()?.len();
        if initial_length > MAX_FILE_BYTES {
            return Err(DurableIterationJournalErrorV1::Capacity);
        }
        if bootstrap && initial_length != 0 {
            return Err(DurableIterationJournalErrorV1::BootstrapRequiresEmptyFile);
        }
        if initial_length == 0 {
            if !bootstrap {
                return Err(DurableIterationJournalErrorV1::ContextMismatch);
            }
            write_durable(&mut file, &expected_header)?;
        } else {
            if initial_length < HEADER_BYTES as u64 {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            file.seek(SeekFrom::Start(0))?;
            let mut header = vec![0_u8; HEADER_BYTES];
            file.read_exact(&mut header)?;
            validate_header(&header)?;
            if header != expected_header {
                return Err(DurableIterationJournalErrorV1::ContextMismatch);
            }
        }

        let mut journal = Self {
            file,
            scope,
            writer_fence,
            maximum_records,
            by_identity: BTreeMap::new(),
            frame_digests: Vec::new(),
            poisoned: false,
        };
        let physical_length = journal.file.metadata()?.len();
        let mut offset = HEADER_BYTES as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            let remaining = physical_length - offset;
            if remaining < FRAME_PREFIX_BYTES as u64 {
                incomplete_tail = true;
                break;
            }
            journal.file.seek(SeekFrom::Start(offset))?;
            let mut prefix = [0_u8; FRAME_PREFIX_BYTES];
            journal.file.read_exact(&mut prefix)?;
            let body_length = decode_prefix(&prefix)?;
            let total = FRAME_PREFIX_BYTES
                .checked_add(body_length)
                .and_then(|value| value.checked_add(FRAME_FOOTER_BYTES))
                .ok_or(DurableIterationJournalErrorV1::Capacity)?;
            if remaining < total as u64 {
                if complete_footer_exists(&mut journal.file, offset, remaining)? {
                    return Err(DurableIterationJournalErrorV1::Corrupt);
                }
                incomplete_tail = true;
                break;
            }
            if journal.frame_digests.len() >= maximum_records {
                return Err(DurableIterationJournalErrorV1::Capacity);
            }
            let mut body = vec![0_u8; body_length];
            journal.file.read_exact(&mut body)?;
            let mut footer = [0_u8; FRAME_FOOTER_BYTES];
            journal.file.read_exact(&mut footer)?;
            let frame_digest = validate_footer(body_length, &body, &footer)?;
            let receipt = decode_body(&body, frame_digest)?;
            let expected_sequence = journal.frame_digests.len() as u64 + 1;
            let expected_predecessor = journal
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            if receipt.sequence != expected_sequence
                || receipt.predecessor_frame_digest != expected_predecessor
            {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            let identity = terminal_identity_digest(&receipt)?;
            if journal.by_identity.insert(identity, receipt.clone()).is_some() {
                return Err(DurableIterationJournalErrorV1::Corrupt);
            }
            journal.frame_digests.push(receipt.frame_digest);
            offset = offset
                .checked_add(total as u64)
                .ok_or(DurableIterationJournalErrorV1::Capacity)?;
        }
        if incomplete_tail {
            journal
                .file
                .set_len(offset)
                .and_then(|_| journal.file.sync_all())
                .map_err(|error| DurableIterationJournalErrorV1::Indeterminate(error.kind()))?;
        }
        Ok(journal)
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope
    }

    #[must_use]
    pub const fn writer_fence(&self) -> u64 {
        self.writer_fence
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.by_identity.len()
    }

    pub fn lookup(
        &self,
        template: &IterationPlasticityTerminalReceiptV1,
    ) -> Result<Option<&IterationPlasticityTerminalReceiptV1>, DurableIterationJournalErrorV1> {
        Ok(self.by_identity.get(&terminal_identity_digest(template)?))
    }

    pub fn append(
        &mut self,
        mut receipt: IterationPlasticityTerminalReceiptV1,
    ) -> Result<IterationPlasticityTerminalReceiptV1, DurableIterationJournalErrorV1> {
        if self.poisoned {
            return Err(DurableIterationJournalErrorV1::Poisoned);
        }
        validate_terminal_payload(&receipt)?;
        let identity = terminal_identity_digest(&receipt)?;
        if let Some(existing) = self.by_identity.get(&identity) {
            if terminal_semantics_equal(existing, &receipt) {
                return Ok(existing.clone());
            }
            return Err(DurableIterationJournalErrorV1::Conflict);
        }
        if self.by_identity.len() >= self.maximum_records {
            return Err(DurableIterationJournalErrorV1::Capacity);
        }
        receipt.sequence = self.frame_digests.len() as u64 + 1;
        receipt.predecessor_frame_digest = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        receipt.frame_digest = Digest32::ZERO;
        let frame = encode_frame(&mut receipt)?;
        let write_result = self
            .file
            .seek(SeekFrom::End(0))
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_all());
        if let Err(error) = write_result {
            self.poisoned = true;
            return Err(DurableIterationJournalErrorV1::Indeterminate(error.kind()));
        }
        self.frame_digests.push(receipt.frame_digest);
        self.by_identity.insert(identity, receipt.clone());
        Ok(receipt)
    }
}

fn terminal_semantics_equal(
    left: &IterationPlasticityTerminalReceiptV1,
    right: &IterationPlasticityTerminalReceiptV1,
) -> bool {
    left.envelope_id == right.envelope_id
        && left.envelope_digest == right.envelope_digest
        && left.freeze_digest == right.freeze_digest
        && left.proposal_id == right.proposal_id
        && left.candidate_generation == right.candidate_generation
        && left.kind == right.kind
        && left.disposition == right.disposition
        && left.request_digest == right.request_digest
        && left.terminal_payload_digest == right.terminal_payload_digest
        && left.coverage_digest == right.coverage_digest
}

fn validate_journal_context(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<(), DurableIterationJournalErrorV1> {
    if scope.is_zero() {
        return Err(DurableIterationJournalErrorV1::InvalidScope);
    }
    if writer_fence == 0 {
        return Err(DurableIterationJournalErrorV1::InvalidFence);
    }
    if !(1..=MAX_JOURNAL_RECORDS).contains(&maximum_records) {
        return Err(DurableIterationJournalErrorV1::InvalidLimit);
    }
    Ok(())
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableIterationJournalErrorV1> {
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(JOURNAL_MAGIC);
    bytes.extend_from_slice(&JOURNAL_VERSION.to_be_bytes());
    bytes.extend_from_slice(scope.as_array());
    bytes.extend_from_slice(&writer_fence.to_be_bytes());
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), DurableIterationJournalErrorV1> {
    if bytes.len() != HEADER_BYTES
        || &bytes[..8] != JOURNAL_MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != JOURNAL_VERSION
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    let digest = Digest32::from_array(
        bytes[HEADER_PREFIX_BYTES..HEADER_BYTES]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    if Digest32::of_bytes(&bytes[..HEADER_PREFIX_BYTES]) != digest {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn write_durable(
    file: &mut File,
    bytes: &[u8],
) -> Result<(), DurableIterationJournalErrorV1> {
    file.seek(SeekFrom::Start(0))?;
    file.write_all(bytes)
        .and_then(|_| file.sync_all())
        .map_err(|error| DurableIterationJournalErrorV1::Indeterminate(error.kind()))
}

fn encode_frame(
    receipt: &mut IterationPlasticityTerminalReceiptV1,
) -> Result<Vec<u8>, DurableIterationJournalErrorV1> {
    let body = encode_body(receipt)?;
    if body.is_empty() || body.len() > MAX_FRAME_BODY_BYTES {
        return Err(DurableIterationJournalErrorV1::Capacity);
    }
    let body_length = u32::try_from(body.len())
        .map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
    let frame_digest = digest_frame_body(body_length, &body);
    receipt.frame_digest = frame_digest;
    let mut frame = Vec::with_capacity(FRAME_PREFIX_BYTES + body.len() + FRAME_FOOTER_BYTES);
    frame.extend_from_slice(FRAME_MAGIC);
    frame.extend_from_slice(&body_length.to_be_bytes());
    frame.extend_from_slice(&(!body_length).to_be_bytes());
    frame.extend_from_slice(&body);
    frame.extend_from_slice(FOOTER_MAGIC);
    frame.extend_from_slice(&body_length.to_be_bytes());
    frame.extend_from_slice(&(!body_length).to_be_bytes());
    frame.extend_from_slice(frame_digest.as_array());
    Ok(frame)
}

fn decode_prefix(prefix: &[u8; FRAME_PREFIX_BYTES]) -> Result<usize, DurableIterationJournalErrorV1> {
    if &prefix[..8] != FRAME_MAGIC {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    let length = u32::from_be_bytes(
        prefix[8..12]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    let complement = u32::from_be_bytes(
        prefix[12..16]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    let length = usize::try_from(length).map_err(|_| DurableIterationJournalErrorV1::Capacity)?;
    if complement != !(length as u32) || length == 0 || length > MAX_FRAME_BODY_BYTES {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    Ok(length)
}

fn validate_footer(
    body_length: usize,
    body: &[u8],
    footer: &[u8; FRAME_FOOTER_BYTES],
) -> Result<Digest32, DurableIterationJournalErrorV1> {
    if &footer[..8] != FOOTER_MAGIC {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    let encoded_length = u32::from_be_bytes(
        footer[8..12]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    let complement = u32::from_be_bytes(
        footer[12..16]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    if encoded_length as usize != body_length || complement != !encoded_length {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    let stored = Digest32::from_array(
        footer[16..48]
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
    );
    if digest_frame_body(encoded_length, body) != stored {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    Ok(stored)
}

fn digest_frame_body(body_length: u32, body: &[u8]) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.iteration-terminal-frame.v2\0".to_vec();
    bytes.extend_from_slice(&body_length.to_be_bytes());
    bytes.extend_from_slice(body);
    Digest32::of_bytes(&bytes)
}

fn complete_footer_exists(
    file: &mut LockedFile,
    offset: u64,
    remaining: u64,
) -> Result<bool, DurableIterationJournalErrorV1> {
    let scan_length = usize::try_from(remaining.min(MAX_FRAME_BYTES as u64))
        .map_err(|_| DurableIterationJournalErrorV1::Capacity)?;
    file.seek(SeekFrom::Start(offset))?;
    let mut bytes = vec![0_u8; scan_length];
    file.read_exact(&mut bytes)?;
    if bytes.len() < FRAME_PREFIX_BYTES + FRAME_FOOTER_BYTES {
        return Ok(false);
    }
    for index in FRAME_PREFIX_BYTES..=bytes.len() - FRAME_FOOTER_BYTES {
        if &bytes[index..index + 8] != FOOTER_MAGIC {
            continue;
        }
        let length = u32::from_be_bytes(
            bytes[index + 8..index + 12]
                .try_into()
                .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
        );
        let complement = u32::from_be_bytes(
            bytes[index + 12..index + 16]
                .try_into()
                .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
        );
        let body_length = length as usize;
        if complement != !length
            || body_length == 0
            || body_length > MAX_FRAME_BODY_BYTES
            || index != FRAME_PREFIX_BYTES + body_length
        {
            continue;
        }
        let stored = Digest32::from_array(
            bytes[index + 16..index + 48]
                .try_into()
                .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?,
        );
        if digest_frame_body(length, &bytes[FRAME_PREFIX_BYTES..index]) == stored {
            return Ok(true);
        }
    }
    Ok(false)
}

fn encode_body(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Vec<u8>, DurableIterationJournalErrorV1> {
    validate_terminal_payload(receipt)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&receipt.sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.predecessor_frame_digest.as_array());
    bytes.extend_from_slice(terminal_identity_digest(receipt)?.as_array());
    push_id(&mut bytes, &receipt.envelope_id)?;
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    bytes.extend_from_slice(receipt.freeze_digest.as_array());
    push_id(&mut bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    bytes.push(kind_tag(receipt.kind));
    bytes.push(disposition_tag(receipt.disposition));
    for digest in [
        receipt.request_digest,
        receipt.terminal_payload_digest,
        receipt.coverage_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.observed_unix_seconds.to_be_bytes());
    Ok(bytes)
}

fn decode_body(
    body: &[u8],
    frame_digest: Digest32,
) -> Result<IterationPlasticityTerminalReceiptV1, DurableIterationJournalErrorV1> {
    let mut cursor = ByteCursor::new(body);
    let sequence = cursor.take_u64()?;
    let predecessor_frame_digest = cursor.take_digest()?;
    let encoded_identity = cursor.take_digest()?;
    let receipt = IterationPlasticityTerminalReceiptV1 {
        sequence,
        envelope_id: cursor.take_id()?,
        envelope_digest: cursor.take_digest()?,
        freeze_digest: cursor.take_digest()?,
        proposal_id: cursor.take_id()?,
        candidate_generation: cursor.take_u64()?,
        kind: kind_from_tag(cursor.take_u8()?)?,
        disposition: disposition_from_tag(cursor.take_u8()?)?,
        request_digest: cursor.take_digest()?,
        terminal_payload_digest: cursor.take_digest()?,
        coverage_digest: cursor.take_digest()?,
        observed_unix_seconds: cursor.take_u64()?,
        predecessor_frame_digest,
        frame_digest,
    };
    if !cursor.is_done()
        || terminal_identity_digest(&receipt)? != encoded_identity
        || receipt.sequence == 0
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    validate_terminal_payload(&receipt)?;
    Ok(receipt)
}

fn validate_terminal_payload(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<(), DurableIterationJournalErrorV1> {
    if receipt.envelope_digest.is_zero()
        || receipt.freeze_digest.is_zero()
        || receipt.candidate_generation == 0
        || receipt.request_digest.is_zero()
        || receipt.terminal_payload_digest.is_zero()
        || receipt.coverage_digest.is_zero()
        || receipt.observed_unix_seconds == 0
    {
        return Err(DurableIterationJournalErrorV1::Corrupt);
    }
    match (receipt.kind, receipt.disposition) {
        (
            IterationPlasticityKindV1::Parameter,
            IterationPlasticityTerminalDispositionV1::ParameterCommitted
            | IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals
            | IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates
            | IterationPlasticityTerminalDispositionV1::IncompleteCoverage,
        )
        | (
            IterationPlasticityKindV1::Topology,
            IterationPlasticityTerminalDispositionV1::TopologyCommitted,
        ) => Ok(()),
        _ => Err(DurableIterationJournalErrorV1::Corrupt),
    }
}

fn terminal_identity_digest(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Digest32, DurableIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.iteration-terminal-identity.v1\0".to_vec();
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    push_id(&mut bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    bytes.push(kind_tag(receipt.kind));
    Ok(Digest32::of_bytes(&bytes))
}

const fn kind_tag(kind: IterationPlasticityKindV1) -> u8 {
    match kind {
        IterationPlasticityKindV1::Parameter => 0,
        IterationPlasticityKindV1::Topology => 1,
    }
}

fn kind_from_tag(value: u8) -> Result<IterationPlasticityKindV1, DurableIterationJournalErrorV1> {
    match value {
        0 => Ok(IterationPlasticityKindV1::Parameter),
        1 => Ok(IterationPlasticityKindV1::Topology),
        _ => Err(DurableIterationJournalErrorV1::Corrupt),
    }
}

const fn disposition_tag(disposition: IterationPlasticityTerminalDispositionV1) -> u8 {
    match disposition {
        IterationPlasticityTerminalDispositionV1::ParameterCommitted => 0,
        IterationPlasticityTerminalDispositionV1::TopologyCommitted => 1,
        IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals => 2,
        IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates => 3,
        IterationPlasticityTerminalDispositionV1::IncompleteCoverage => 4,
    }
}

fn disposition_from_tag(
    value: u8,
) -> Result<IterationPlasticityTerminalDispositionV1, DurableIterationJournalErrorV1> {
    match value {
        0 => Ok(IterationPlasticityTerminalDispositionV1::ParameterCommitted),
        1 => Ok(IterationPlasticityTerminalDispositionV1::TopologyCommitted),
        2 => Ok(IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals),
        3 => Ok(IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates),
        4 => Ok(IterationPlasticityTerminalDispositionV1::IncompleteCoverage),
        _ => Err(DurableIterationJournalErrorV1::Corrupt),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), DurableIterationJournalErrorV1> {
    let raw = value.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_ID_BYTES {
        return Err(DurableIterationJournalErrorV1::Capacity);
    }
    let length = u32::try_from(raw.len()).map_err(|_| DurableIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

struct ByteCursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> ByteCursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn take_array<const N: usize>(&mut self) -> Result<[u8; N], DurableIterationJournalErrorV1> {
        let end = self
            .offset
            .checked_add(N)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?
            .try_into()
            .map_err(|_| DurableIterationJournalErrorV1::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn take_u8(&mut self) -> Result<u8, DurableIterationJournalErrorV1> {
        Ok(self.take_array::<1>()?[0])
    }
    fn take_u32(&mut self) -> Result<u32, DurableIterationJournalErrorV1> {
        Ok(u32::from_be_bytes(self.take_array::<4>()?))
    }
    fn take_u64(&mut self) -> Result<u64, DurableIterationJournalErrorV1> {
        Ok(u64::from_be_bytes(self.take_array::<8>()?))
    }
    fn take_digest(&mut self) -> Result<Digest32, DurableIterationJournalErrorV1> {
        Ok(Digest32::from_array(self.take_array::<32>()?))
    }
    fn take_id(&mut self) -> Result<StableId, DurableIterationJournalErrorV1> {
        let length = self.take_u32()? as usize;
        if length == 0 || length > MAX_ID_BYTES {
            return Err(DurableIterationJournalErrorV1::Corrupt);
        }
        let end = self
            .offset
            .checked_add(length)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        let raw = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableIterationJournalErrorV1::Corrupt)?;
        self.offset = end;
        let value = std::str::from_utf8(raw).map_err(|_| DurableIterationJournalErrorV1::Corrupt)?;
        StableId::new(value.to_string()).map_err(|_| DurableIterationJournalErrorV1::Corrupt)
    }
    fn is_done(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::io::Write;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn terminal(proposal: &str, request: &[u8]) -> IterationPlasticityTerminalReceiptV1 {
        IterationPlasticityTerminalReceiptV1 {
            sequence: 0,
            envelope_id: id("envelope:journal:v2"),
            envelope_digest: digest(b"envelope"),
            freeze_digest: digest(b"freeze"),
            proposal_id: id(proposal),
            candidate_generation: 2,
            kind: IterationPlasticityKindV1::Parameter,
            disposition: IterationPlasticityTerminalDispositionV1::ParameterCommitted,
            request_digest: digest(request),
            terminal_payload_digest: digest(b"terminal"),
            coverage_digest: digest(b"coverage"),
            observed_unix_seconds: 10,
            predecessor_frame_digest: Digest32::ZERO,
            frame_digest: Digest32::ZERO,
        }
    }
    fn open(path: &std::path::Path) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .expect("open")
    }

    #[test]
    fn protected_journal_reopens_replays_and_preserves_chain() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        let (first, second) = {
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
                open(fixture.path()),
                scope,
                7,
                8,
            )
            .expect("journal");
            let first = journal
                .append(terminal("proposal:one", b"request:one"))
                .expect("first");
            let second = journal
                .append(terminal("proposal:two", b"request:two"))
                .expect("second");
            assert_eq!(second.predecessor_frame_digest, first.frame_digest);
            assert_eq!(
                journal
                    .append(terminal("proposal:one", b"request:one"))
                    .expect("retry"),
                first
            );
            (first, second)
        };
        let journal = DurableIterationTerminalJournalV1::reopen(
            open(fixture.path()),
            scope,
            7,
            8,
        )
        .expect("reopen");
        assert_eq!(journal.record_count(), 2);
        assert_eq!(
            journal.lookup(&terminal("proposal:one", b"request:one")).expect("lookup"),
            Some(&first)
        );
        assert_eq!(
            journal.lookup(&terminal("proposal:two", b"request:two")).expect("lookup"),
            Some(&second)
        );
    }

    #[test]
    fn complete_frame_with_corrupt_prefix_length_is_not_truncated() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        {
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
                open(fixture.path()),
                scope,
                9,
                8,
            )
            .expect("journal");
            journal
                .append(terminal("proposal:length", b"request"))
                .expect("append");
        }
        let mut bytes = std::fs::read(fixture.path()).expect("read");
        let length_offset = HEADER_BYTES + 8;
        let length = u32::from_be_bytes(
            bytes[length_offset..length_offset + 4]
                .try_into()
                .expect("length"),
        );
        let changed = length + 1;
        bytes[length_offset..length_offset + 4].copy_from_slice(&changed.to_be_bytes());
        bytes[length_offset + 4..length_offset + 8]
            .copy_from_slice(&(!changed).to_be_bytes());
        std::fs::write(fixture.path(), &bytes).expect("corrupt");
        assert!(matches!(
            DurableIterationTerminalJournalV1::reopen(open(fixture.path()), scope, 9, 8),
            Err(DurableIterationJournalErrorV1::Corrupt)
        ));
        assert_eq!(std::fs::read(fixture.path()).expect("read back"), bytes);
    }

    #[test]
    fn partial_final_frame_is_the_only_repairable_tail() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        {
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
                open(fixture.path()),
                scope,
                11,
                8,
            )
            .expect("journal");
            journal
                .append(terminal("proposal:tail", b"request"))
                .expect("append");
        }
        let valid_length = std::fs::metadata(fixture.path()).expect("metadata").len();
        {
            let mut file = OpenOptions::new()
                .append(true)
                .open(fixture.path())
                .expect("append");
            file.write_all(FRAME_MAGIC).expect("magic");
            file.write_all(&100_u32.to_be_bytes()).expect("length");
            file.write_all(&(!100_u32).to_be_bytes()).expect("complement");
            file.write_all(b"partial").expect("partial body");
            file.sync_all().expect("sync");
        }
        let journal = DurableIterationTerminalJournalV1::reopen(
            open(fixture.path()),
            scope,
            11,
            8,
        )
        .expect("repair");
        assert_eq!(journal.record_count(), 1);
        assert_eq!(
            std::fs::metadata(fixture.path()).expect("metadata").len(),
            valid_length
        );
    }

    #[test]
    fn complete_frame_mutation_corpus_fails_closed() {
        let source = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        {
            let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
                open(source.path()),
                scope,
                13,
                8,
            )
            .expect("journal");
            journal
                .append(terminal("proposal:mutation", b"request"))
                .expect("append");
        }
        let bytes = std::fs::read(source.path()).expect("read");
        for index in HEADER_BYTES..bytes.len() {
            let fixture = tempfile::NamedTempFile::new().expect("mutation file");
            let mut changed = bytes.clone();
            changed[index] ^= 0x01;
            std::fs::write(fixture.path(), &changed).expect("write mutation");
            assert!(
                DurableIterationTerminalJournalV1::reopen(
                    open(fixture.path()),
                    scope,
                    13,
                    8,
                )
                .is_err(),
                "mutation at byte {index} was accepted"
            );
            assert_eq!(
                std::fs::read(fixture.path()).expect("read mutation"),
                changed,
                "mutation at byte {index} was modified during rejected recovery"
            );
        }
    }

    #[test]
    fn capacity_and_second_writer_fail_closed() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let scope = digest(b"scope");
        let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
            open(fixture.path()),
            scope,
            15,
            2,
        )
        .expect("journal");
        assert!(matches!(
            DurableIterationTerminalJournalV1::reopen(open(fixture.path()), scope, 15, 2),
            Err(DurableIterationJournalErrorV1::Busy)
        ));
        journal
            .append(terminal("proposal:one", b"one"))
            .expect("one");
        journal
            .append(terminal("proposal:two", b"two"))
            .expect("two");
        assert_eq!(
            journal.append(terminal("proposal:three", b"three")),
            Err(DurableIterationJournalErrorV1::Capacity)
        );
    }
}
