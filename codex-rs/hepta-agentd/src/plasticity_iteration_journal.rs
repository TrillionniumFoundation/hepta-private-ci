//! Durable control.engineering terminal receipts for governed plasticity iterations.
//!
//! This journal is deliberately separate from parameter/topology proposal registries.
//! It can record only a terminal receipt that already binds an externally anchored
//! product result. It cannot construct, select, activate or apply a candidate. The
//! idempotency key is `(envelope, proposal, generation, kind)`; exact replay is
//! unchanged and semantic drift conflicts. Complete corrupt frames fail closed and
//! only an incomplete final crash tail may be repaired.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
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
use codex_hepta_types::StableId;

use crate::PlasticityFileIdentityV1;
use crate::PlasticitySecureFileErrorV1;
use crate::open_or_create_plasticity_file_v1;

const HEADER_MAGIC: &[u8; 8] = b"HPTITR01";
const FRAME_MAGIC: &[u8; 8] = b"HPTITF01";
const FORMAT_VERSION: u16 = 1;
const HEADER_SIZE: usize = 8 + 2 + 32 + 4 + 32;
const MAX_RECORDS: usize = 16_384;
const MAX_FRAME_BYTES: usize = 64 * 1024;
const MAX_FILE_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PlasticityIterationKindV1 {
    Parameter,
    Topology,
}
impl PlasticityIterationKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Parameter => 0,
            Self::Topology => 1,
        }
    }
    fn from_tag(value: u8) -> Result<Self, PlasticityIterationJournalErrorV1> {
        match value {
            0 => Ok(Self::Parameter),
            1 => Ok(Self::Topology),
            _ => Err(PlasticityIterationJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityIterationTerminalV1 {
    UpdateCandidates,
    NoAdmissibleUpdate,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    TopologyCandidates,
    NoTopologyChange,
}
impl PlasticityIterationTerminalV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::UpdateCandidates => 0,
            Self::NoAdmissibleUpdate => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
            Self::TopologyCandidates => 4,
            Self::NoTopologyChange => 5,
        }
    }
    fn from_tag(value: u8) -> Result<Self, PlasticityIterationJournalErrorV1> {
        match value {
            0 => Ok(Self::UpdateCandidates),
            1 => Ok(Self::NoAdmissibleUpdate),
            2 => Ok(Self::ZeroEligibleSignals),
            3 => Ok(Self::PolicyDisabledUpdates),
            4 => Ok(Self::TopologyCandidates),
            5 => Ok(Self::NoTopologyChange),
            _ => Err(PlasticityIterationJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityIterationTerminalReceiptV1 {
    pub envelope_digest: Digest32,
    pub proposal_id: StableId,
    pub candidate_generation: Generation,
    pub kind: PlasticityIterationKindV1,
    pub terminal: PlasticityIterationTerminalV1,
    pub coverage_digest: Option<Digest32>,
    pub durable_sequence: u64,
    pub durable_frame_digest: Digest32,
    pub product_composition_digest: Digest32,
    pub idempotent_replay: bool,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityIterationJournalDispositionV1 {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityIterationJournalAppendReceiptV1 {
    pub sequence: u64,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub terminal_receipt_digest: Digest32,
    pub disposition: PlasticityIterationJournalDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedPlasticityIterationReceiptV1 {
    pub terminal: PlasticityIterationTerminalReceiptV1,
    pub journal: PlasticityIterationJournalAppendReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
struct TerminalKeyV1 {
    envelope_digest: Digest32,
    proposal_id: StableId,
    candidate_generation: Generation,
    kind: PlasticityIterationKindV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityIterationJournalAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Debug)]
pub enum PlasticityIterationJournalErrorV1 {
    Busy,
    InvalidScope,
    InvalidLimit,
    BootstrapRequiresEmptyFile,
    ContextMismatch,
    Capacity,
    Conflict,
    Corrupt,
    Poisoned,
    Indeterminate,
    Identity,
    Arithmetic,
    Io(std::io::ErrorKind),
    SecureFile(PlasticitySecureFileErrorV1),
}
impl fmt::Display for PlasticityIterationJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityIterationJournalErrorV1 {}
impl From<std::io::Error> for PlasticityIterationJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<PlasticitySecureFileErrorV1> for PlasticityIterationJournalErrorV1 {
    fn from(value: PlasticitySecureFileErrorV1) -> Self {
        Self::SecureFile(value)
    }
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, PlasticityIterationJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(PlasticityIterationJournalErrorV1::Corrupt);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(PlasticityIterationJournalErrorV1::Busy),
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

pub struct ControlEngineeringPlasticityJournalV1 {
    file: LockedFile,
    file_identity: Option<PlasticityFileIdentityV1>,
    scope_digest: Digest32,
    maximum_records: usize,
    records: BTreeMap<TerminalKeyV1, (PlasticityIterationTerminalReceiptV1, u64, Digest32)>,
    frame_digests: Vec<Digest32>,
    poisoned: bool,
}

impl ControlEngineeringPlasticityJournalV1 {
    pub fn open_or_create_path(
        path: &Path,
        scope_digest: Digest32,
        maximum_records: usize,
    ) -> Result<Self, PlasticityIterationJournalErrorV1> {
        let opened = open_or_create_plasticity_file_v1(path)?;
        let identity = opened.identity;
        let mut journal = if opened.created {
            Self::bootstrap_empty(opened.file, scope_digest, maximum_records)?
        } else {
            Self::reopen(opened.file, scope_digest, maximum_records)?
        };
        journal.file_identity = Some(identity);
        Ok(journal)
    }

    pub fn bootstrap_empty(
        file: File,
        scope_digest: Digest32,
        maximum_records: usize,
    ) -> Result<Self, PlasticityIterationJournalErrorV1> {
        if file.metadata()?.len() != 0 {
            return Err(PlasticityIterationJournalErrorV1::BootstrapRequiresEmptyFile);
        }
        Self::open(file, scope_digest, maximum_records, true)
    }

    pub fn reopen(
        file: File,
        scope_digest: Digest32,
        maximum_records: usize,
    ) -> Result<Self, PlasticityIterationJournalErrorV1> {
        Self::open(file, scope_digest, maximum_records, false)
    }

    fn open(
        file: File,
        scope_digest: Digest32,
        maximum_records: usize,
        bootstrap: bool,
    ) -> Result<Self, PlasticityIterationJournalErrorV1> {
        if scope_digest.is_zero() {
            return Err(PlasticityIterationJournalErrorV1::InvalidScope);
        }
        if !(1..=MAX_RECORDS).contains(&maximum_records) {
            return Err(PlasticityIterationJournalErrorV1::InvalidLimit);
        }
        let expected_header = encode_header(scope_digest, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let physical_length = file.metadata()?.len();
        if physical_length > MAX_FILE_BYTES {
            return Err(PlasticityIterationJournalErrorV1::Capacity);
        }
        if bootstrap {
            file.seek(SeekFrom::Start(0))?;
            file.write_all(&expected_header)
                .and_then(|_| file.sync_all())
                .map_err(|_| PlasticityIterationJournalErrorV1::Indeterminate)?;
        } else {
            if physical_length < HEADER_SIZE as u64 {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
            file.seek(SeekFrom::Start(0))?;
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.read_exact(&mut actual)?;
            validate_header(&actual)?;
            if actual != expected_header {
                return Err(PlasticityIterationJournalErrorV1::ContextMismatch);
            }
        }

        let mut journal = Self {
            file,
            file_identity: None,
            scope_digest,
            maximum_records,
            records: BTreeMap::new(),
            frame_digests: Vec::new(),
            poisoned: false,
        };
        let physical_length = journal.file.metadata()?.len();
        let mut offset = HEADER_SIZE as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            journal.file.seek(SeekFrom::Start(offset))?;
            let mut size = [0_u8; 4];
            journal.file.read_exact(&mut size)?;
            let frame_size = u32::from_be_bytes(size) as usize;
            if frame_size == 0 || frame_size > MAX_FRAME_BYTES {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_size as u64)
                .ok_or(PlasticityIterationJournalErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if journal.frame_digests.len() >= maximum_records {
                return Err(PlasticityIterationJournalErrorV1::Capacity);
            }
            let mut frame = vec![0_u8; frame_size];
            journal.file.read_exact(&mut frame)?;
            let decoded = decode_frame(scope_digest, &frame)?;
            let expected_sequence = journal.frame_digests.len() as u64 + 1;
            let expected_predecessor = journal
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            if decoded.sequence != expected_sequence
                || decoded.predecessor_frame_digest != expected_predecessor
            {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
            let key = terminal_key(&decoded.receipt);
            if journal
                .records
                .insert(
                    key,
                    (decoded.receipt, decoded.sequence, decoded.frame_digest),
                )
                .is_some()
            {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
            journal.frame_digests.push(decoded.frame_digest);
            offset = offset
                .checked_add(total)
                .ok_or(PlasticityIterationJournalErrorV1::Capacity)?;
        }
        if incomplete_tail {
            journal
                .file
                .set_len(offset)
                .and_then(|_| journal.file.sync_all())
                .map_err(|_| PlasticityIterationJournalErrorV1::Indeterminate)?;
        }
        Ok(journal)
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn file_identity(&self) -> Option<PlasticityFileIdentityV1> {
        self.file_identity
    }

    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }

    #[must_use]
    pub fn current_anchor(&self) -> Option<PlasticityIterationJournalAnchorV1> {
        self.frame_digests.last().copied().map(|frame_digest| {
            PlasticityIterationJournalAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            }
        })
    }

    pub fn append(
        &mut self,
        receipt: PlasticityIterationTerminalReceiptV1,
    ) -> Result<PlasticityIterationJournalAppendReceiptV1, PlasticityIterationJournalErrorV1> {
        if self.poisoned {
            return Err(PlasticityIterationJournalErrorV1::Poisoned);
        }
        verify_terminal_receipt_v1(&receipt)?;
        let key = terminal_key(&receipt);
        if let Some((existing, sequence, frame_digest)) = self.records.get(&key) {
            if existing != &receipt {
                return Err(PlasticityIterationJournalErrorV1::Conflict);
            }
            let predecessor = sequence
                .checked_sub(2)
                .and_then(|index| usize::try_from(index).ok())
                .and_then(|index| self.frame_digests.get(index))
                .copied()
                .unwrap_or(Digest32::ZERO);
            return Ok(PlasticityIterationJournalAppendReceiptV1 {
                sequence: *sequence,
                predecessor_frame_digest: predecessor,
                frame_digest: *frame_digest,
                terminal_receipt_digest: receipt.receipt_digest,
                disposition: PlasticityIterationJournalDispositionV1::Unchanged,
            });
        }
        if self.records.len() >= self.maximum_records {
            return Err(PlasticityIterationJournalErrorV1::Capacity);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let predecessor_frame_digest = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        let frame = encode_frame(
            self.scope_digest,
            sequence,
            predecessor_frame_digest,
            &receipt,
        )?;
        let frame_size = u32::try_from(frame.len())
            .map_err(|_| PlasticityIterationJournalErrorV1::Capacity)?;
        let frame_digest = Digest32::from_array(
            frame[frame.len() - 32..]
                .try_into()
                .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?,
        );
        self.file.seek(SeekFrom::End(0))?;
        if self
            .file
            .write_all(&frame_size.to_be_bytes())
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(PlasticityIterationJournalErrorV1::Indeterminate);
        }
        self.records
            .insert(key, (receipt.clone(), sequence, frame_digest));
        self.frame_digests.push(frame_digest);
        Ok(PlasticityIterationJournalAppendReceiptV1 {
            sequence,
            predecessor_frame_digest,
            frame_digest,
            terminal_receipt_digest: receipt.receipt_digest,
            disposition: PlasticityIterationJournalDispositionV1::Inserted,
        })
    }
}

pub(crate) fn build_terminal_receipt_v1(
    envelope_digest: Digest32,
    proposal_id: StableId,
    candidate_generation: Generation,
    kind: PlasticityIterationKindV1,
    terminal: PlasticityIterationTerminalV1,
    coverage_digest: Option<Digest32>,
    durable_sequence: u64,
    durable_frame_digest: Digest32,
    product_composition_digest: Digest32,
    idempotent_replay: bool,
) -> Result<PlasticityIterationTerminalReceiptV1, PlasticityIterationJournalErrorV1> {
    let mut receipt = PlasticityIterationTerminalReceiptV1 {
        envelope_digest,
        proposal_id,
        candidate_generation,
        kind,
        terminal,
        coverage_digest,
        durable_sequence,
        durable_frame_digest,
        product_composition_digest,
        idempotent_replay,
        receipt_digest: Digest32::ZERO,
    };
    validate_terminal_fields(&receipt)?;
    receipt.receipt_digest = digest_terminal_receipt(&receipt)?;
    Ok(receipt)
}

pub fn verify_terminal_receipt_v1(
    receipt: &PlasticityIterationTerminalReceiptV1,
) -> Result<(), PlasticityIterationJournalErrorV1> {
    validate_terminal_fields(receipt)?;
    if receipt.receipt_digest.is_zero()
        || digest_terminal_receipt(receipt)? != receipt.receipt_digest
    {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn validate_terminal_fields(
    receipt: &PlasticityIterationTerminalReceiptV1,
) -> Result<(), PlasticityIterationJournalErrorV1> {
    if receipt.envelope_digest.is_zero()
        || receipt.durable_sequence == 0
        || receipt.durable_frame_digest.is_zero()
        || receipt.product_composition_digest.is_zero()
        || receipt.coverage_digest.is_some_and(|digest| digest.is_zero())
    {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    match receipt.kind {
        PlasticityIterationKindV1::Parameter => {
            if receipt.coverage_digest.is_none()
                || matches!(
                    receipt.terminal,
                    PlasticityIterationTerminalV1::TopologyCandidates
                        | PlasticityIterationTerminalV1::NoTopologyChange
                )
            {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
        }
        PlasticityIterationKindV1::Topology => {
            if receipt.coverage_digest.is_some()
                || !matches!(
                    receipt.terminal,
                    PlasticityIterationTerminalV1::TopologyCandidates
                        | PlasticityIterationTerminalV1::NoTopologyChange
                )
            {
                return Err(PlasticityIterationJournalErrorV1::Corrupt);
            }
        }
    }
    Ok(())
}

fn terminal_key(receipt: &PlasticityIterationTerminalReceiptV1) -> TerminalKeyV1 {
    TerminalKeyV1 {
        envelope_digest: receipt.envelope_digest,
        proposal_id: receipt.proposal_id.clone(),
        candidate_generation: receipt.candidate_generation,
        kind: receipt.kind,
    }
}

fn digest_terminal_receipt(
    receipt: &PlasticityIterationTerminalReceiptV1,
) -> Result<Digest32, PlasticityIterationJournalErrorV1> {
    let mut bytes = b"hepta.control-engineering.plasticity-terminal-receipt.v1\0".to_vec();
    push_terminal_fields(&mut bytes, receipt, false)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn encode_header(
    scope_digest: Digest32,
    maximum_records: usize,
) -> Result<Vec<u8>, PlasticityIterationJournalErrorV1> {
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| PlasticityIterationJournalErrorV1::InvalidLimit)?;
    let mut bytes = Vec::with_capacity(HEADER_SIZE);
    bytes.extend_from_slice(HEADER_MAGIC);
    bytes.extend_from_slice(&FORMAT_VERSION.to_be_bytes());
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    let mut digest_material = b"hepta.control-engineering.plasticity-terminal-header.v1\0".to_vec();
    digest_material.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&digest_material).as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), PlasticityIterationJournalErrorV1> {
    if bytes.len() != HEADER_SIZE || &bytes[..8] != HEADER_MAGIC {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    if u16::from_be_bytes([bytes[8], bytes[9]]) != FORMAT_VERSION {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    let mut material = b"hepta.control-engineering.plasticity-terminal-header.v1\0".to_vec();
    material.extend_from_slice(&bytes[..HEADER_SIZE - 32]);
    if Digest32::of_bytes(&material).as_array() != &bytes[HEADER_SIZE - 32..] {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn encode_frame(
    scope_digest: Digest32,
    sequence: u64,
    predecessor_frame_digest: Digest32,
    receipt: &PlasticityIterationTerminalReceiptV1,
) -> Result<Vec<u8>, PlasticityIterationJournalErrorV1> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(FRAME_MAGIC);
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(predecessor_frame_digest.as_array());
    push_terminal_fields(&mut bytes, receipt, true)?;
    let mut digest_material = b"hepta.control-engineering.plasticity-terminal-frame.v1\0".to_vec();
    digest_material.extend_from_slice(scope_digest.as_array());
    digest_material.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&digest_material).as_array());
    Ok(bytes)
}

struct DecodedFrameV1 {
    sequence: u64,
    predecessor_frame_digest: Digest32,
    receipt: PlasticityIterationTerminalReceiptV1,
    frame_digest: Digest32,
}

fn decode_frame(
    scope_digest: Digest32,
    frame: &[u8],
) -> Result<DecodedFrameV1, PlasticityIterationJournalErrorV1> {
    if frame.len() < 8 + 8 + 32 + 32 || &frame[..8] != FRAME_MAGIC {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    let (body, digest_bytes) = frame.split_at(frame.len() - 32);
    let frame_digest = Digest32::from_array(
        digest_bytes
            .try_into()
            .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?,
    );
    let mut material = b"hepta.control-engineering.plasticity-terminal-frame.v1\0".to_vec();
    material.extend_from_slice(scope_digest.as_array());
    material.extend_from_slice(body);
    if Digest32::of_bytes(&material) != frame_digest {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    let mut decoder = Decoder::new(&body[8..]);
    let sequence = decoder.u64()?;
    let predecessor_frame_digest = decoder.digest()?;
    let receipt = decoder.terminal_receipt()?;
    if !decoder.finished() {
        return Err(PlasticityIterationJournalErrorV1::Corrupt);
    }
    verify_terminal_receipt_v1(&receipt)?;
    Ok(DecodedFrameV1 {
        sequence,
        predecessor_frame_digest,
        receipt,
        frame_digest,
    })
}

fn push_terminal_fields(
    bytes: &mut Vec<u8>,
    receipt: &PlasticityIterationTerminalReceiptV1,
    include_receipt_digest: bool,
) -> Result<(), PlasticityIterationJournalErrorV1> {
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    push_id(bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    bytes.push(receipt.kind.tag());
    bytes.push(receipt.terminal.tag());
    match receipt.coverage_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&receipt.durable_sequence.to_be_bytes());
    bytes.extend_from_slice(receipt.durable_frame_digest.as_array());
    bytes.extend_from_slice(receipt.product_composition_digest.as_array());
    bytes.push(u8::from(receipt.idempotent_replay));
    if include_receipt_digest {
        bytes.extend_from_slice(receipt.receipt_digest.as_array());
    }
    Ok(())
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), PlasticityIterationJournalErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| PlasticityIterationJournalErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Decoder<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn take(&mut self, length: usize) -> Result<&'a [u8], PlasticityIterationJournalErrorV1> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(PlasticityIterationJournalErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(PlasticityIterationJournalErrorV1::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn byte(&mut self) -> Result<u8, PlasticityIterationJournalErrorV1> {
        Ok(self.take(1)?[0])
    }
    fn u32(&mut self) -> Result<u32, PlasticityIterationJournalErrorV1> {
        Ok(u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?,
        ))
    }
    fn u64(&mut self) -> Result<u64, PlasticityIterationJournalErrorV1> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, PlasticityIterationJournalErrorV1> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?,
        ))
    }
    fn stable_id(&mut self) -> Result<StableId, PlasticityIterationJournalErrorV1> {
        let length = usize::try_from(self.u32()?)
            .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?;
        let raw = self.take(length)?;
        let value = std::str::from_utf8(raw)
            .map_err(|_| PlasticityIterationJournalErrorV1::Identity)?;
        StableId::new(value.to_string())
            .map_err(|_| PlasticityIterationJournalErrorV1::Identity)
    }
    fn terminal_receipt(
        &mut self,
    ) -> Result<PlasticityIterationTerminalReceiptV1, PlasticityIterationJournalErrorV1> {
        let envelope_digest = self.digest()?;
        let proposal_id = self.stable_id()?;
        let candidate_generation = Generation::new(self.u64()?)
            .map_err(|_| PlasticityIterationJournalErrorV1::Corrupt)?;
        let kind = PlasticityIterationKindV1::from_tag(self.byte()?)?;
        let terminal = PlasticityIterationTerminalV1::from_tag(self.byte()?)?;
        let coverage_digest = match self.byte()? {
            0 => None,
            1 => Some(self.digest()?),
            _ => return Err(PlasticityIterationJournalErrorV1::Corrupt),
        };
        let durable_sequence = self.u64()?;
        let durable_frame_digest = self.digest()?;
        let product_composition_digest = self.digest()?;
        let idempotent_replay = match self.byte()? {
            0 => false,
            1 => true,
            _ => return Err(PlasticityIterationJournalErrorV1::Corrupt),
        };
        let receipt_digest = self.digest()?;
        Ok(PlasticityIterationTerminalReceiptV1 {
            envelope_digest,
            proposal_id,
            candidate_generation,
            kind,
            terminal,
            coverage_digest,
            durable_sequence,
            durable_frame_digest,
            product_composition_digest,
            idempotent_replay,
            receipt_digest,
        })
    }
    fn finished(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    struct TestFile {
        path: std::path::PathBuf,
    }
    impl TestFile {
        fn new(label: &str) -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos();
            Self {
                path: std::env::temp_dir().join(format!(
                    "hepta-iteration-{label}-{}-{nonce}.journal",
                    std::process::id()
                )),
            }
        }
        fn create(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&self.path)
                .expect("create")
        }
        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.path)
                .expect("open")
        }
    }
    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.path);
        }
    }

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn terminal() -> PlasticityIterationTerminalReceiptV1 {
        build_terminal_receipt_v1(
            digest(b"envelope"),
            id("iteration:parameter:proposal"),
            generation(2),
            PlasticityIterationKindV1::Parameter,
            PlasticityIterationTerminalV1::UpdateCandidates,
            Some(digest(b"coverage")),
            1,
            digest(b"proposal-frame"),
            digest(b"composition"),
            false,
        )
        .expect("terminal")
    }

    #[test]
    fn append_reopen_and_exact_retry_are_idempotent() {
        let fixture = TestFile::new("reopen");
        let scope = digest(b"scope");
        let receipt = terminal();
        let first = {
            let mut journal = ControlEngineeringPlasticityJournalV1::bootstrap_empty(
                fixture.create(),
                scope,
                8,
            )
            .expect("bootstrap");
            journal.append(receipt.clone()).expect("append")
        };
        assert_eq!(first.disposition, PlasticityIterationJournalDispositionV1::Inserted);
        let mut journal = ControlEngineeringPlasticityJournalV1::reopen(
            fixture.open(),
            scope,
            8,
        )
        .expect("reopen");
        let retry = journal.append(receipt).expect("retry");
        assert_eq!(retry.disposition, PlasticityIterationJournalDispositionV1::Unchanged);
        assert_eq!(retry.frame_digest, first.frame_digest);
        assert_eq!(journal.record_count(), 1);
    }

    #[test]
    fn semantic_drift_under_the_same_iteration_key_conflicts() {
        let fixture = TestFile::new("conflict");
        let scope = digest(b"scope");
        let mut journal = ControlEngineeringPlasticityJournalV1::bootstrap_empty(
            fixture.create(),
            scope,
            8,
        )
        .expect("bootstrap");
        let receipt = terminal();
        journal.append(receipt.clone()).expect("append");
        let mut drift = receipt;
        drift.product_composition_digest = digest(b"other-composition");
        drift.receipt_digest = digest_terminal_receipt(&drift).expect("digest");
        assert!(matches!(
            journal.append(drift),
            Err(PlasticityIterationJournalErrorV1::Conflict)
        ));
    }

    #[test]
    fn incomplete_tail_is_repaired_but_complete_corruption_fails() {
        let fixture = TestFile::new("tail");
        let scope = digest(b"scope");
        let anchor = {
            let mut journal = ControlEngineeringPlasticityJournalV1::bootstrap_empty(
                fixture.create(),
                scope,
                8,
            )
            .expect("bootstrap");
            journal.append(terminal()).expect("append");
            journal.current_anchor().expect("anchor")
        };
        let valid_length = std::fs::metadata(&fixture.path).expect("metadata").len();
        {
            let mut file = OpenOptions::new()
                .append(true)
                .open(&fixture.path)
                .expect("append tail");
            file.write_all(&[0, 0, 0]).expect("tail");
            file.sync_all().expect("sync");
        }
        let journal = ControlEngineeringPlasticityJournalV1::reopen(
            fixture.open(),
            scope,
            8,
        )
        .expect("repair");
        assert_eq!(journal.current_anchor(), Some(anchor));
        drop(journal);
        assert_eq!(
            std::fs::metadata(&fixture.path).expect("metadata").len(),
            valid_length
        );

        let mut bytes = std::fs::read(&fixture.path).expect("read");
        let last = bytes.len() - 1;
        bytes[last] ^= 0x80;
        std::fs::write(&fixture.path, bytes).expect("corrupt");
        assert!(matches!(
            ControlEngineeringPlasticityJournalV1::reopen(fixture.open(), scope, 8),
            Err(PlasticityIterationJournalErrorV1::Corrupt)
        ));
    }

    #[test]
    fn second_writer_is_excluded() {
        let fixture = TestFile::new("lock");
        let first = ControlEngineeringPlasticityJournalV1::bootstrap_empty(
            fixture.create(),
            digest(b"scope"),
            8,
        )
        .expect("first");
        assert!(matches!(
            ControlEngineeringPlasticityJournalV1::reopen(
                fixture.open(),
                digest(b"scope"),
                8,
            ),
            Err(PlasticityIterationJournalErrorV1::Busy)
        ));
        drop(first);
    }
}
