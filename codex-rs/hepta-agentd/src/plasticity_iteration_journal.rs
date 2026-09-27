//! Durable terminal journal for control-engineering-owned self-iteration.
//!
//! Agentd hosts this owner-native checksum chain beside the bounded producer,
//! but the journal grants no selection, activation, topology-apply, promotion or
//! release authority. The runtime returns success only after the exact terminal
//! receipt is synced. Identical retries are idempotent; drift conflicts.

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

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdIdentity;
use crate::MutableOwnerStorageIdentityV1;
use crate::SelfIterationParameterReceiptV1;
use crate::SelfIterationPlasticityTerminalV1;
use crate::SelfIterationTopologyReceiptV1;
use crate::secure_mutable_file::open_or_create_private_mutable_file_v1;

const FILE_NAME: &str = "control-engineering-plasticity-terminal-v1.journal";
const MAGIC: &[u8; 8] = b"HPTSIT01";
const HEADER_DOMAIN: &[u8] = b"hepta.control-engineering.plasticity-terminal-header.v1\0";
const FRAME_DOMAIN: &[u8] = b"hepta.control-engineering.plasticity-terminal-frame.v1\0";
const FORMAT_VERSION: u16 = 1;
const HEADER_PREFIX_SIZE: usize = 8 + 2 + 4 + 32;
const HEADER_SIZE: usize = HEADER_PREFIX_SIZE + 32;
const MAX_RECORDS: usize = 16_384;
const MAX_FRAME_BYTES: usize = 16 * 1024;
const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ID_BYTES: usize = 1_024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum TerminalKindV1 {
    Parameter,
    Topology,
}
impl TerminalKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Parameter => 0,
            Self::Topology => 1,
        }
    }
    fn decode(value: u8) -> Result<Self, SelfIterationTerminalJournalErrorV1> {
        match value {
            0 => Ok(Self::Parameter),
            1 => Ok(Self::Topology),
            _ => Err(SelfIterationTerminalJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct TerminalRecordV1 {
    kind: TerminalKindV1,
    envelope_digest: Digest32,
    coverage_receipt_digest: Option<Digest32>,
    proposal_id: StableId,
    proposal_digest: Digest32,
    registry_sequence: u64,
    registry_frame_digest: Digest32,
    committed_anchor_frame_digest: Digest32,
    product_composition_digest: Digest32,
    terminal: SelfIterationPlasticityTerminalV1,
    terminal_receipt_digest: Digest32,
}

impl From<SelfIterationParameterReceiptV1> for TerminalRecordV1 {
    fn from(value: SelfIterationParameterReceiptV1) -> Self {
        Self {
            kind: TerminalKindV1::Parameter,
            envelope_digest: value.envelope_digest,
            coverage_receipt_digest: Some(value.coverage_receipt_digest),
            proposal_id: value.proposal_id,
            proposal_digest: value.proposal_digest,
            registry_sequence: value.registry_sequence,
            registry_frame_digest: value.registry_frame_digest,
            committed_anchor_frame_digest: value.committed_anchor_frame_digest,
            product_composition_digest: value.product_composition_digest,
            terminal: value.terminal,
            terminal_receipt_digest: value.receipt_digest,
        }
    }
}
impl From<SelfIterationTopologyReceiptV1> for TerminalRecordV1 {
    fn from(value: SelfIterationTopologyReceiptV1) -> Self {
        Self {
            kind: TerminalKindV1::Topology,
            envelope_digest: value.envelope_digest,
            coverage_receipt_digest: None,
            proposal_id: value.proposal_id,
            proposal_digest: value.proposal_digest,
            registry_sequence: value.registry_sequence,
            registry_frame_digest: value.registry_frame_digest,
            committed_anchor_frame_digest: value.committed_anchor_frame_digest,
            product_composition_digest: value.product_composition_digest,
            terminal: value.terminal,
            terminal_receipt_digest: value.receipt_digest,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationTerminalAppendDispositionV1 {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTerminalAppendReceiptV1 {
    pub sequence: u64,
    pub generation: u64,
    pub terminal_receipt_digest: Digest32,
    pub frame_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub disposition: SelfIterationTerminalAppendDispositionV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SelfIterationTerminalJournalAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Debug, Eq, PartialEq)]
pub enum SelfIterationTerminalJournalErrorV1 {
    Busy,
    InvalidScope,
    InvalidGeneration,
    InvalidLimit,
    NotRegular,
    ContextMismatch,
    GenerationRollback,
    Capacity,
    Conflict,
    Corrupt,
    Poisoned,
    Indeterminate,
    Io(std::io::ErrorKind),
}
impl fmt::Display for SelfIterationTerminalJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationTerminalJournalErrorV1 {}
impl From<std::io::Error> for SelfIterationTerminalJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct TerminalIdentityV1 {
    kind: TerminalKindV1,
    envelope_digest: Digest32,
    proposal_id: StableId,
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, SelfIterationTerminalJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(SelfIterationTerminalJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(SelfIterationTerminalJournalErrorV1::Busy),
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

pub struct SelfIterationTerminalJournalV1 {
    file: LockedFile,
    scope_digest: Digest32,
    current_generation: u64,
    maximum_records: usize,
    storage_identity: MutableOwnerStorageIdentityV1,
    records: BTreeMap<TerminalIdentityV1, TerminalRecordV1>,
    receipts: BTreeMap<TerminalIdentityV1, SelfIterationTerminalAppendReceiptV1>,
    frame_digests: Vec<Digest32>,
    last_generation: u64,
    poisoned: bool,
}

impl SelfIterationTerminalJournalV1 {
    pub fn open_for_agent(
        identity: &AgentdIdentity,
        maximum_records: usize,
    ) -> Result<Self, SelfIterationTerminalJournalErrorV1> {
        Self::open_for_parts(
            &identity.home_root,
            identity.agent_id.as_str(),
            identity.spawn_generation,
            maximum_records,
        )
    }

    fn open_for_parts(
        home_root: &Path,
        agent_id: &str,
        current_generation: u64,
        maximum_records: usize,
    ) -> Result<Self, SelfIterationTerminalJournalErrorV1> {
        let scope_digest = terminal_journal_scope_digest(agent_id);
        if scope_digest.is_zero() {
            return Err(SelfIterationTerminalJournalErrorV1::InvalidScope);
        }
        if current_generation == 0 {
            return Err(SelfIterationTerminalJournalErrorV1::InvalidGeneration);
        }
        if !(1..=MAX_RECORDS).contains(&maximum_records) {
            return Err(SelfIterationTerminalJournalErrorV1::InvalidLimit);
        }
        let opened = open_or_create_private_mutable_file_v1(home_root, FILE_NAME)
            .map_err(|error| match error {
                crate::SecureMutableFileErrorV1::NotRegular => {
                    SelfIterationTerminalJournalErrorV1::NotRegular
                }
                crate::SecureMutableFileErrorV1::Io(kind) => {
                    SelfIterationTerminalJournalErrorV1::Io(kind)
                }
                _ => SelfIterationTerminalJournalErrorV1::ContextMismatch,
            })?;
        let _created = opened.created;
        Self::open_file(
            opened.file,
            scope_digest,
            current_generation,
            maximum_records,
            opened.identity,
        )
    }

    fn open_file(
        file: File,
        scope_digest: Digest32,
        current_generation: u64,
        maximum_records: usize,
        storage_identity: MutableOwnerStorageIdentityV1,
    ) -> Result<Self, SelfIterationTerminalJournalErrorV1> {
        let expected_header = encode_header(scope_digest, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let physical_length = file.metadata()?.len();
        if physical_length > MAX_FILE_BYTES {
            return Err(SelfIterationTerminalJournalErrorV1::Capacity);
        }
        file.seek(SeekFrom::Start(0))?;
        if physical_length == 0 {
            file.write_all(&expected_header)
                .and_then(|_| file.sync_all())
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Indeterminate)?;
        } else {
            if physical_length < HEADER_SIZE as u64 {
                return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.read_exact(&mut actual)?;
            validate_header(&actual)?;
            if actual != expected_header {
                return Err(SelfIterationTerminalJournalErrorV1::ContextMismatch);
            }
        }
        let mut value = Self {
            file,
            scope_digest,
            current_generation,
            maximum_records,
            storage_identity,
            records: BTreeMap::new(),
            receipts: BTreeMap::new(),
            frame_digests: Vec::new(),
            last_generation: 0,
            poisoned: false,
        };
        value.replay()?;
        Ok(value)
    }

    fn replay(&mut self) -> Result<(), SelfIterationTerminalJournalErrorV1> {
        let physical_length = self.file.metadata()?.len();
        let mut offset = HEADER_SIZE as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            self.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            self.file.read_exact(&mut length_bytes)?;
            let frame_len = u32::from_be_bytes(length_bytes) as usize;
            if !(8 + 8 + 32 + 1 + 32..=MAX_FRAME_BYTES).contains(&frame_len) {
                return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_len as u64)
                .ok_or(SelfIterationTerminalJournalErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if self.frame_digests.len() >= self.maximum_records {
                return Err(SelfIterationTerminalJournalErrorV1::Capacity);
            }
            let mut frame = vec![0_u8; frame_len];
            self.file.read_exact(&mut frame)?;
            let decoded = decode_frame(&frame)?;
            let expected_sequence = self.frame_digests.len() as u64 + 1;
            let expected_predecessor = self
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            if decoded.sequence != expected_sequence
                || decoded.predecessor_frame_digest != expected_predecessor
                || decoded.generation < self.last_generation
                || decoded.generation > self.current_generation
            {
                return Err(SelfIterationTerminalJournalErrorV1::GenerationRollback);
            }
            let key = identity_for(&decoded.record);
            if self.records.insert(key.clone(), decoded.record.clone()).is_some() {
                return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
            }
            self.receipts.insert(
                key,
                SelfIterationTerminalAppendReceiptV1 {
                    sequence: decoded.sequence,
                    generation: decoded.generation,
                    terminal_receipt_digest: decoded.record.terminal_receipt_digest,
                    frame_digest: decoded.frame_digest,
                    predecessor_frame_digest: decoded.predecessor_frame_digest,
                    disposition: SelfIterationTerminalAppendDispositionV1::Inserted,
                    authority: AuthorityPosture::DENY_ALL,
                },
            );
            self.frame_digests.push(decoded.frame_digest);
            self.last_generation = decoded.generation;
            offset = offset
                .checked_add(total)
                .ok_or(SelfIterationTerminalJournalErrorV1::Capacity)?;
        }
        if incomplete_tail {
            self.file
                .set_len(offset)
                .and_then(|_| self.file.sync_all())
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Indeterminate)?;
        }
        Ok(())
    }

    pub fn append_parameter(
        &mut self,
        receipt: SelfIterationParameterReceiptV1,
    ) -> Result<SelfIterationTerminalAppendReceiptV1, SelfIterationTerminalJournalErrorV1> {
        self.append(receipt.into())
    }

    pub fn append_topology(
        &mut self,
        receipt: SelfIterationTopologyReceiptV1,
    ) -> Result<SelfIterationTerminalAppendReceiptV1, SelfIterationTerminalJournalErrorV1> {
        self.append(receipt.into())
    }

    fn append(
        &mut self,
        record: TerminalRecordV1,
    ) -> Result<SelfIterationTerminalAppendReceiptV1, SelfIterationTerminalJournalErrorV1> {
        if self.poisoned {
            return Err(SelfIterationTerminalJournalErrorV1::Poisoned);
        }
        validate_record(&record)?;
        let key = identity_for(&record);
        if let Some(existing) = self.records.get(&key) {
            if existing != &record {
                return Err(SelfIterationTerminalJournalErrorV1::Conflict);
            }
            let mut receipt = self
                .receipts
                .get(&key)
                .cloned()
                .ok_or(SelfIterationTerminalJournalErrorV1::Corrupt)?;
            receipt.disposition = SelfIterationTerminalAppendDispositionV1::Unchanged;
            return Ok(receipt);
        }
        if self.records.len() >= self.maximum_records {
            return Err(SelfIterationTerminalJournalErrorV1::Capacity);
        }
        if self.current_generation < self.last_generation {
            return Err(SelfIterationTerminalJournalErrorV1::GenerationRollback);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let predecessor_frame_digest = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        let frame = encode_frame(
            sequence,
            self.current_generation,
            predecessor_frame_digest,
            &record,
        )?;
        let frame_digest = Digest32::from_array(
            frame[frame.len() - 32..]
                .try_into()
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
        );
        let length = u32::try_from(frame.len())
            .map_err(|_| SelfIterationTerminalJournalErrorV1::Capacity)?;
        self.file.seek(SeekFrom::End(0))?;
        if self
            .file
            .write_all(&length.to_be_bytes())
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(SelfIterationTerminalJournalErrorV1::Indeterminate);
        }
        let receipt = SelfIterationTerminalAppendReceiptV1 {
            sequence,
            generation: self.current_generation,
            terminal_receipt_digest: record.terminal_receipt_digest,
            frame_digest,
            predecessor_frame_digest,
            disposition: SelfIterationTerminalAppendDispositionV1::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.records.insert(key.clone(), record);
        self.receipts.insert(key, receipt.clone());
        self.frame_digests.push(frame_digest);
        self.last_generation = self.current_generation;
        Ok(receipt)
    }

    #[must_use]
    pub const fn storage_identity(&self) -> MutableOwnerStorageIdentityV1 {
        self.storage_identity
    }
    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }
    #[must_use]
    pub fn record_count(&self) -> usize {
        self.records.len()
    }
    #[must_use]
    pub fn current_anchor(&self) -> Option<SelfIterationTerminalJournalAnchorV1> {
        self.frame_digests.last().copied().map(|frame_digest| {
            SelfIterationTerminalJournalAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            }
        })
    }
}

struct DecodedFrameV1 {
    sequence: u64,
    generation: u64,
    predecessor_frame_digest: Digest32,
    record: TerminalRecordV1,
    frame_digest: Digest32,
}

fn terminal_journal_scope_digest(agent_id: &str) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.plasticity-terminal-scope.v1\0".to_vec();
    bytes.extend_from_slice(agent_id.as_bytes());
    Digest32::of_bytes(&bytes)
}

fn identity_for(record: &TerminalRecordV1) -> TerminalIdentityV1 {
    TerminalIdentityV1 {
        kind: record.kind,
        envelope_digest: record.envelope_digest,
        proposal_id: record.proposal_id.clone(),
    }
}

fn encode_header(
    scope_digest: Digest32,
    maximum_records: usize,
) -> Result<Vec<u8>, SelfIterationTerminalJournalErrorV1> {
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| SelfIterationTerminalJournalErrorV1::InvalidLimit)?;
    let mut bytes = Vec::with_capacity(HEADER_SIZE);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&FORMAT_VERSION.to_be_bytes());
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    bytes.extend_from_slice(scope_digest.as_array());
    let mut material = HEADER_DOMAIN.to_vec();
    material.extend_from_slice(&bytes);
    bytes.extend_from_slice(Digest32::of_bytes(&material).as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), SelfIterationTerminalJournalErrorV1> {
    if bytes.len() != HEADER_SIZE
        || &bytes[..8] != MAGIC
        || u16::from_be_bytes(
            bytes[8..10]
                .try_into()
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
        ) != FORMAT_VERSION
    {
        return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
    }
    let expected = Digest32::from_array(
        bytes[HEADER_PREFIX_SIZE..]
            .try_into()
            .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
    );
    let mut material = HEADER_DOMAIN.to_vec();
    material.extend_from_slice(&bytes[..HEADER_PREFIX_SIZE]);
    if expected != Digest32::of_bytes(&material) {
        return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn encode_frame(
    sequence: u64,
    generation: u64,
    predecessor_frame_digest: Digest32,
    record: &TerminalRecordV1,
) -> Result<Vec<u8>, SelfIterationTerminalJournalErrorV1> {
    let mut payload = Vec::new();
    payload.extend_from_slice(&sequence.to_be_bytes());
    payload.extend_from_slice(&generation.to_be_bytes());
    payload.extend_from_slice(predecessor_frame_digest.as_array());
    payload.push(record.kind.tag());
    payload.extend_from_slice(record.envelope_digest.as_array());
    match record.coverage_receipt_digest {
        Some(digest) => {
            payload.push(1);
            payload.extend_from_slice(digest.as_array());
        }
        None => payload.push(0),
    }
    push_id(&mut payload, &record.proposal_id)?;
    for digest in [
        record.proposal_digest,
        record.registry_frame_digest,
        record.committed_anchor_frame_digest,
        record.product_composition_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    payload.extend_from_slice(&record.registry_sequence.to_be_bytes());
    payload.push(terminal_tag(record.terminal));
    payload.extend_from_slice(record.terminal_receipt_digest.as_array());
    let mut material = FRAME_DOMAIN.to_vec();
    material.extend_from_slice(&payload);
    payload.extend_from_slice(Digest32::of_bytes(&material).as_array());
    if payload.len() > MAX_FRAME_BYTES {
        return Err(SelfIterationTerminalJournalErrorV1::Capacity);
    }
    Ok(payload)
}

fn decode_frame(bytes: &[u8]) -> Result<DecodedFrameV1, SelfIterationTerminalJournalErrorV1> {
    let payload_end = bytes
        .len()
        .checked_sub(32)
        .ok_or(SelfIterationTerminalJournalErrorV1::Corrupt)?;
    let expected = Digest32::from_array(
        bytes[payload_end..]
            .try_into()
            .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
    );
    let mut material = FRAME_DOMAIN.to_vec();
    material.extend_from_slice(&bytes[..payload_end]);
    if expected != Digest32::of_bytes(&material) {
        return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
    }
    let mut decoder = DecoderV1::new(&bytes[..payload_end]);
    let sequence = decoder.u64()?;
    let generation = decoder.u64()?;
    let predecessor_frame_digest = decoder.digest()?;
    let kind = TerminalKindV1::decode(decoder.u8()?)?;
    let envelope_digest = decoder.digest()?;
    let coverage_receipt_digest = match decoder.u8()? {
        0 => None,
        1 => Some(decoder.digest()?),
        _ => return Err(SelfIterationTerminalJournalErrorV1::Corrupt),
    };
    let record = TerminalRecordV1 {
        kind,
        envelope_digest,
        coverage_receipt_digest,
        proposal_id: decoder.id()?,
        proposal_digest: decoder.digest()?,
        registry_frame_digest: decoder.digest()?,
        committed_anchor_frame_digest: decoder.digest()?,
        product_composition_digest: decoder.digest()?,
        registry_sequence: decoder.u64()?,
        terminal: terminal_from_tag(decoder.u8()?)?,
        terminal_receipt_digest: decoder.digest()?,
    };
    if !decoder.is_empty() || sequence == 0 || generation == 0 {
        return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
    }
    validate_record(&record)?;
    Ok(DecodedFrameV1 {
        sequence,
        generation,
        predecessor_frame_digest,
        record,
        frame_digest: expected,
    })
}

fn validate_record(record: &TerminalRecordV1) -> Result<(), SelfIterationTerminalJournalErrorV1> {
    let terminal_shape = match record.kind {
        TerminalKindV1::Parameter => {
            record.coverage_receipt_digest.is_some()
                && record.terminal
                    != SelfIterationPlasticityTerminalV1::TopologyCandidatesAppended
        }
        TerminalKindV1::Topology => {
            record.coverage_receipt_digest.is_none()
                && record.terminal
                    == SelfIterationPlasticityTerminalV1::TopologyCandidatesAppended
        }
    };
    if !terminal_shape
        || record.registry_sequence == 0
        || record.envelope_digest.is_zero()
        || record
            .coverage_receipt_digest
            .is_some_and(Digest32::is_zero)
        || record.proposal_digest.is_zero()
        || record.registry_frame_digest.is_zero()
        || record.committed_anchor_frame_digest.is_zero()
        || record.product_composition_digest.is_zero()
        || record.terminal_receipt_digest.is_zero()
        || record.terminal_receipt_digest != terminal_receipt_digest(record)
    {
        return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
    }
    Ok(())
}

fn terminal_receipt_digest(record: &TerminalRecordV1) -> Digest32 {
    let mut bytes = match record.kind {
        TerminalKindV1::Parameter => {
            b"hepta.control-engineering.parameter-iteration-receipt.v1\0".to_vec()
        }
        TerminalKindV1::Topology => {
            b"hepta.control-engineering.topology-iteration-receipt.v1\0".to_vec()
        }
    };
    bytes.extend_from_slice(record.envelope_digest.as_array());
    if let Some(coverage) = record.coverage_receipt_digest {
        bytes.extend_from_slice(coverage.as_array());
    }
    for digest in [
        record.proposal_digest,
        record.registry_frame_digest,
        record.committed_anchor_frame_digest,
        record.product_composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(record.proposal_id.as_str().as_bytes());
    bytes.extend_from_slice(&record.registry_sequence.to_be_bytes());
    bytes.push(terminal_tag(record.terminal));
    Digest32::of_bytes(&bytes)
}

const fn terminal_tag(value: SelfIterationPlasticityTerminalV1) -> u8 {
    match value {
        SelfIterationPlasticityTerminalV1::ParameterCandidatesAppended => 0,
        SelfIterationPlasticityTerminalV1::NoAdmissibleParameterUpdate => 1,
        SelfIterationPlasticityTerminalV1::ZeroEligibleSignals => 2,
        SelfIterationPlasticityTerminalV1::PolicyDisabledUpdates => 3,
        SelfIterationPlasticityTerminalV1::TopologyCandidatesAppended => 4,
    }
}
fn terminal_from_tag(
    value: u8,
) -> Result<SelfIterationPlasticityTerminalV1, SelfIterationTerminalJournalErrorV1> {
    match value {
        0 => Ok(SelfIterationPlasticityTerminalV1::ParameterCandidatesAppended),
        1 => Ok(SelfIterationPlasticityTerminalV1::NoAdmissibleParameterUpdate),
        2 => Ok(SelfIterationPlasticityTerminalV1::ZeroEligibleSignals),
        3 => Ok(SelfIterationPlasticityTerminalV1::PolicyDisabledUpdates),
        4 => Ok(SelfIterationPlasticityTerminalV1::TopologyCandidatesAppended),
        _ => Err(SelfIterationTerminalJournalErrorV1::Corrupt),
    }
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), SelfIterationTerminalJournalErrorV1> {
    let raw = value.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_ID_BYTES {
        return Err(SelfIterationTerminalJournalErrorV1::Capacity);
    }
    let length = u32::try_from(raw.len())
        .map_err(|_| SelfIterationTerminalJournalErrorV1::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

struct DecoderV1<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> DecoderV1<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn take(&mut self, length: usize) -> Result<&'a [u8], SelfIterationTerminalJournalErrorV1> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(SelfIterationTerminalJournalErrorV1::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(SelfIterationTerminalJournalErrorV1::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn u8(&mut self) -> Result<u8, SelfIterationTerminalJournalErrorV1> {
        self.take(1)?
            .first()
            .copied()
            .ok_or(SelfIterationTerminalJournalErrorV1::Corrupt)
    }
    fn u64(&mut self) -> Result<u64, SelfIterationTerminalJournalErrorV1> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, SelfIterationTerminalJournalErrorV1> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
        ))
    }
    fn id(&mut self) -> Result<StableId, SelfIterationTerminalJournalErrorV1> {
        let length = u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?,
        ) as usize;
        if length == 0 || length > MAX_ID_BYTES {
            return Err(SelfIterationTerminalJournalErrorV1::Corrupt);
        }
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)?;
        StableId::new(value).map_err(|_| SelfIterationTerminalJournalErrorV1::Corrupt)
    }
    fn is_empty(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn parameter_receipt() -> SelfIterationParameterReceiptV1 {
        let mut receipt = SelfIterationParameterReceiptV1 {
            envelope_digest: digest(b"envelope"),
            coverage_receipt_digest: digest(b"coverage"),
            proposal_id: StableId::new("proposal:terminal:1").expect("id"),
            proposal_digest: digest(b"proposal"),
            registry_sequence: 1,
            registry_frame_digest: digest(b"registry-frame"),
            committed_anchor_frame_digest: digest(b"anchor"),
            product_composition_digest: digest(b"composition"),
            terminal: SelfIterationPlasticityTerminalV1::ParameterCandidatesAppended,
            receipt_digest: Digest32::ZERO,
        };
        let record = TerminalRecordV1::from(receipt.clone());
        receipt.receipt_digest = terminal_receipt_digest(&record);
        receipt
    }

    #[test]
    fn journal_is_durable_idempotent_and_generation_monotonic() {
        let temp = tempfile::tempdir().expect("tempdir");
        let home = temp.path().canonicalize().expect("home");
        let receipt = parameter_receipt();
        let anchor = {
            let mut journal = SelfIterationTerminalJournalV1::open_for_parts(
                &home,
                "agent-terminal",
                7,
                8,
            )
            .expect("open");
            let first = journal
                .append_parameter(receipt.clone())
                .expect("append");
            assert_eq!(
                first.disposition,
                SelfIterationTerminalAppendDispositionV1::Inserted
            );
            let replay = journal
                .append_parameter(receipt.clone())
                .expect("replay");
            assert_eq!(
                replay.disposition,
                SelfIterationTerminalAppendDispositionV1::Unchanged
            );
            journal.current_anchor().expect("anchor")
        };
        let journal = SelfIterationTerminalJournalV1::open_for_parts(
            &home,
            "agent-terminal",
            8,
            8,
        )
        .expect("reopen");
        assert_eq!(journal.current_anchor(), Some(anchor));
        assert_eq!(journal.record_count(), 1);
        drop(journal);
        assert!(matches!(
            SelfIterationTerminalJournalV1::open_for_parts(
                &home,
                "agent-terminal",
                6,
                8,
            ),
            Err(SelfIterationTerminalJournalErrorV1::GenerationRollback)
        ));
    }

    #[test]
    fn drift_conflicts_and_incomplete_tail_is_repaired() {
        let temp = tempfile::tempdir().expect("tempdir");
        let home = temp.path().canonicalize().expect("home");
        let valid_length = {
            let mut journal = SelfIterationTerminalJournalV1::open_for_parts(
                &home,
                "agent-terminal",
                3,
                8,
            )
            .expect("open");
            let receipt = parameter_receipt();
            journal
                .append_parameter(receipt.clone())
                .expect("append");
            let mut drift = receipt;
            drift.product_composition_digest = digest(b"drift");
            let mut record = TerminalRecordV1::from(drift.clone());
            drift.receipt_digest = terminal_receipt_digest(&record);
            record = TerminalRecordV1::from(drift.clone());
            assert_eq!(drift.receipt_digest, terminal_receipt_digest(&record));
            assert!(matches!(
                journal.append_parameter(drift),
                Err(SelfIterationTerminalJournalErrorV1::Conflict)
            ));
            journal.file.metadata().expect("metadata").len()
        };
        let path = home.join(FILE_NAME);
        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .expect("tail file");
        file.write_all(&[0, 0, 0]).expect("tail");
        file.sync_all().expect("tail sync");
        drop(file);
        let journal = SelfIterationTerminalJournalV1::open_for_parts(
            &home,
            "agent-terminal",
            3,
            8,
        )
        .expect("repair");
        assert_eq!(journal.file.metadata().expect("metadata").len(), valid_length);
    }

    #[test]
    fn complete_corrupt_frame_fails_closed_without_rewrite() {
        let temp = tempfile::tempdir().expect("tempdir");
        let home = temp.path().canonicalize().expect("home");
        {
            let mut journal = SelfIterationTerminalJournalV1::open_for_parts(
                &home,
                "agent-terminal",
                4,
                8,
            )
            .expect("open");
            journal
                .append_parameter(parameter_receipt())
                .expect("append");
        }
        let path = home.join(FILE_NAME);
        let mut bytes = std::fs::read(&path).expect("read");
        let last = bytes.len() - 1;
        bytes[last] ^= 0x80;
        std::fs::write(&path, &bytes).expect("corrupt");
        assert!(matches!(
            SelfIterationTerminalJournalV1::open_for_parts(
                &home,
                "agent-terminal",
                4,
                8,
            ),
            Err(SelfIterationTerminalJournalErrorV1::Corrupt)
        ));
        assert_eq!(std::fs::read(&path).expect("read again"), bytes);
    }
}
