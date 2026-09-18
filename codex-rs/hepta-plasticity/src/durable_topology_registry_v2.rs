//! Durable, authority-free storage for topology V2 proposal records.
//!
//! This journal persists structural proposals only. It has no apply, writer
//! transfer, activation, selection, promotion or release operation.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::{File, TryLockError};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::ops::{Deref, DerefMut};

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{
    AppendDisposition, DurableRegistryAnchorV1, ProposalStatus, ProposalWindowV2,
    TopologyCandidateKindV2, TopologyCandidateV2, TopologyChangeV2, TopologyOperationV2,
    TopologyProposalErrorV2, TopologyProposalV2, verify_topology_proposal_v2,
};

const MAGIC: &[u8; 8] = b"HPTOPV02";
const PAYLOAD_MAGIC: &[u8; 8] = b"HPTOPP02";
const FORMAT_VERSION: u16 = 2;
const HEADER_SIZE: usize = 8 + 2 + 8 + 4 + 32 + 32;
const MAX_RECORDS: usize = 4_096;
const MAX_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableTopologyProposalAppendReceiptV1 {
    pub registry_scope_digest: Digest32,
    pub writer_fence: u64,
    pub sequence: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub disposition: AppendDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableTopologyProposalRegistryError {
    Busy,
    NotRegular,
    InvalidLimit,
    InvalidScope,
    InvalidWriterFence,
    InvalidAnchor,
    BootstrapRequiresEmptyFile,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    ContextMismatch,
    Corrupt,
    Capacity,
    Conflict,
    Poisoned,
    Indeterminate,
    Io(io::ErrorKind),
    Proposal(TopologyProposalErrorV2),
}
impl fmt::Display for DurableTopologyProposalRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableTopologyProposalRegistryError {}
impl From<io::Error> for DurableTopologyProposalRegistryError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<TopologyProposalErrorV2> for DurableTopologyProposalRegistryError {
    fn from(value: TopologyProposalErrorV2) -> Self {
        Self::Proposal(value)
    }
}

#[derive(Clone, Copy)]
enum RecoveryPolicy {
    Unanchored,
    BootstrapEmpty,
    Require(DurableRegistryAnchorV1),
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableTopologyProposalRegistryError> {
        if !file.metadata()?.is_file() {
            return Err(DurableTopologyProposalRegistryError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableTopologyProposalRegistryError::Busy),
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

pub struct DurableTopologyProposalRegistryV2 {
    file: LockedFile,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    records: BTreeMap<StableId, TopologyProposalV2>,
    frames: Vec<Digest32>,
    receipts: BTreeMap<StableId, DurableTopologyProposalAppendReceiptV1>,
    poisoned: bool,
}

impl DurableTopologyProposalRegistryV2 {
    pub fn open(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        Self::open_with_policy(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            RecoveryPolicy::Unanchored,
        )
    }

    /// Enroll a new product registry only when the exclusively locked file is
    /// physically empty. The check happens after lock acquisition.
    pub fn open_bootstrap_empty(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        Self::open_with_policy(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            RecoveryPolicy::BootstrapEmpty,
        )
    }

    pub fn open_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableRegistryAnchorV1,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        Self::open_with_policy(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            RecoveryPolicy::Require(anchor),
        )
    }

    fn open_with_policy(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        policy: RecoveryPolicy,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        if !(1..=MAX_RECORDS).contains(&maximum_records) {
            return Err(DurableTopologyProposalRegistryError::InvalidLimit);
        }
        if registry_scope_digest.is_zero() {
            return Err(DurableTopologyProposalRegistryError::InvalidScope);
        }
        if writer_fence == 0 {
            return Err(DurableTopologyProposalRegistryError::InvalidWriterFence);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && (anchor.sequence == 0
                || anchor.sequence > maximum_records as u64
                || anchor.frame_digest.is_zero())
        {
            return Err(DurableTopologyProposalRegistryError::InvalidAnchor);
        }
        let expected_header = encode_header(registry_scope_digest, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let file_len = file.metadata()?.len();
        if file_len > MAX_FILE_BYTES {
            return Err(DurableTopologyProposalRegistryError::Capacity);
        }
        if matches!(policy, RecoveryPolicy::BootstrapEmpty) && file_len != 0 {
            return Err(DurableTopologyProposalRegistryError::BootstrapRequiresEmptyFile);
        }
        if file_len == 0 {
            if matches!(policy, RecoveryPolicy::Require(_)) {
                return Err(DurableTopologyProposalRegistryError::AcknowledgedHistoryMissing);
            }
            file.write_all(&expected_header)
                .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
        } else {
            if file_len < HEADER_SIZE as u64 {
                return Err(DurableTopologyProposalRegistryError::Corrupt);
            }
            file.seek(SeekFrom::Start(0))?;
            let mut header = vec![0_u8; HEADER_SIZE];
            file.read_exact(&mut header)?;
            validate_header(&header)?;
            if header != expected_header {
                return Err(DurableTopologyProposalRegistryError::ContextMismatch);
            }
        }

        let mut store = Self {
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            records: BTreeMap::new(),
            frames: Vec::new(),
            receipts: BTreeMap::new(),
            poisoned: false,
        };
        let physical_len = store.file.metadata()?.len();
        let mut offset = HEADER_SIZE as u64;
        let mut incomplete_tail = false;
        while offset < physical_len {
            let remaining = physical_len - offset;
            if remaining < 4 {
                incomplete_tail = true;
                break;
            }
            store.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            store.file.read_exact(&mut length_bytes)?;
            let frame_len = u32::from_be_bytes(length_bytes) as usize;
            if frame_len < 8 + 32 + 4 + 32 || frame_len > MAX_PAYLOAD_BYTES + 76 {
                return Err(DurableTopologyProposalRegistryError::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_len as u64)
                .ok_or(DurableTopologyProposalRegistryError::Capacity)?;
            if remaining < total {
                incomplete_tail = true;
                break;
            }
            if store.frames.len() >= maximum_records {
                return Err(DurableTopologyProposalRegistryError::Capacity);
            }
            let mut frame = vec![0_u8; frame_len];
            store.file.read_exact(&mut frame)?;
            let decoded = decode_frame(&frame)?;
            let expected_sequence = store.frames.len() as u64 + 1;
            let expected_predecessor = store.frames.last().copied().unwrap_or(Digest32::ZERO);
            if decoded.sequence != expected_sequence
                || decoded.predecessor_frame_digest != expected_predecessor
            {
                return Err(DurableTopologyProposalRegistryError::Corrupt);
            }
            store.insert_recovered(decoded.proposal.clone())?;
            let receipt = DurableTopologyProposalAppendReceiptV1 {
                registry_scope_digest,
                writer_fence,
                sequence: decoded.sequence,
                proposal_id: decoded.proposal.proposal_id.clone(),
                proposal_digest: decoded.proposal.proposal_digest,
                predecessor_frame_digest: decoded.predecessor_frame_digest,
                frame_digest: decoded.frame_digest,
                disposition: AppendDisposition::Inserted,
                authority: AuthorityPosture::DENY_ALL,
            };
            store.receipts.insert(receipt.proposal_id.clone(), receipt);
            store.frames.push(decoded.frame_digest);
            offset += total;
        }
        if let RecoveryPolicy::Require(anchor) = policy {
            let recovered = anchor
                .sequence
                .checked_sub(1)
                .and_then(|index| usize::try_from(index).ok())
                .and_then(|index| store.frames.get(index))
                .ok_or(DurableTopologyProposalRegistryError::AcknowledgedHistoryMissing)?;
            if *recovered != anchor.frame_digest {
                return Err(DurableTopologyProposalRegistryError::AnchorMismatch);
            }
        }
        if incomplete_tail {
            store
                .file
                .set_len(offset)
                .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
            store
                .file
                .sync_all()
                .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
        }
        Ok(store)
    }

    pub fn append_v2(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: TopologyProposalV2,
    ) -> Result<DurableTopologyProposalAppendReceiptV1, DurableTopologyProposalRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyProposalRegistryError::Poisoned);
        }
        verify_topology_proposal_v2(&proposal)?;
        if let Some(existing) = self.records.get(&proposal.proposal_id) {
            if existing == &proposal {
                let mut receipt = self
                    .receipts
                    .get(&proposal.proposal_id)
                    .cloned()
                    .ok_or(DurableTopologyProposalRegistryError::Corrupt)?;
                receipt.disposition = AppendDisposition::Unchanged;
                return Ok(receipt);
            }
            return Err(DurableTopologyProposalRegistryError::Conflict);
        }
        if self.records.values().any(|record| {
            record.selected_artifact_digest == proposal.selected_artifact_digest
                && record.window.window_id == proposal.window.window_id
        }) {
            return Err(DurableTopologyProposalRegistryError::Conflict);
        }
        let current = self.frames.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableTopologyProposalRegistryError::Conflict);
        }
        if self.records.len() >= self.maximum_records {
            return Err(DurableTopologyProposalRegistryError::Capacity);
        }
        let sequence = self.frames.len() as u64 + 1;
        let (frame, frame_digest) = encode_frame(sequence, current, &proposal)?;
        let physical = self.file.metadata()?.len();
        let required = physical
            .checked_add(4 + frame.len() as u64)
            .ok_or(DurableTopologyProposalRegistryError::Capacity)?;
        if required > MAX_FILE_BYTES {
            return Err(DurableTopologyProposalRegistryError::Capacity);
        }
        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(frame.len() as u32).to_be_bytes())
            .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
        self.file
            .write_all(&frame)
            .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| DurableTopologyProposalRegistryError::Indeterminate)?;
        self.records
            .insert(proposal.proposal_id.clone(), proposal.clone());
        self.frames.push(frame_digest);
        let receipt = DurableTopologyProposalAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            predecessor_frame_digest: current,
            frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.receipts.insert(proposal.proposal_id, receipt.clone());
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, DurableTopologyProposalRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyProposalRegistryError::Poisoned);
        }
        Ok(self.frames.last().copied().map(|frame_digest| DurableRegistryAnchorV1 {
            sequence: self.frames.len() as u64,
            frame_digest,
        }))
    }

    pub fn get(
        &self,
        proposal_id: &StableId,
    ) -> Result<Option<&TopologyProposalV2>, DurableTopologyProposalRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyProposalRegistryError::Poisoned);
        }
        Ok(self.records.get(proposal_id))
    }

    pub fn record_count(&self) -> Result<usize, DurableTopologyProposalRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyProposalRegistryError::Poisoned);
        }
        Ok(self.records.len())
    }

    fn insert_recovered(
        &mut self,
        proposal: TopologyProposalV2,
    ) -> Result<(), DurableTopologyProposalRegistryError> {
        verify_topology_proposal_v2(&proposal)?;
        if self.records.contains_key(&proposal.proposal_id)
            || self.records.values().any(|record| {
                record.selected_artifact_digest == proposal.selected_artifact_digest
                    && record.window.window_id == proposal.window.window_id
            })
        {
            return Err(DurableTopologyProposalRegistryError::Corrupt);
        }
        self.records.insert(proposal.proposal_id.clone(), proposal);
        Ok(())
    }
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableTopologyProposalRegistryError> {
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| DurableTopologyProposalRegistryError::InvalidLimit)?;
    let mut bytes = Vec::with_capacity(HEADER_SIZE);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&FORMAT_VERSION.to_be_bytes());
    bytes.extend_from_slice(&writer_fence.to_be_bytes());
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    bytes.extend_from_slice(scope.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), DurableTopologyProposalRegistryError> {
    if bytes.len() != HEADER_SIZE
        || &bytes[..8] != MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != FORMAT_VERSION
        || Digest32::of_bytes(&bytes[..HEADER_SIZE - 32]).as_array() != &bytes[HEADER_SIZE - 32..]
    {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    Ok(())
}

struct DecodedFrame {
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: TopologyProposalV2,
    frame_digest: Digest32,
}

fn encode_frame(
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: &TopologyProposalV2,
) -> Result<(Vec<u8>, Digest32), DurableTopologyProposalRegistryError> {
    let payload = encode_proposal(proposal)?;
    if payload.len() > MAX_PAYLOAD_BYTES {
        return Err(DurableTopologyProposalRegistryError::Capacity);
    }
    let mut frame = Vec::with_capacity(8 + 32 + 4 + payload.len() + 32);
    frame.extend_from_slice(&sequence.to_be_bytes());
    frame.extend_from_slice(predecessor_frame_digest.as_array());
    frame.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    frame.extend_from_slice(&payload);
    let digest = Digest32::of_bytes(&frame);
    frame.extend_from_slice(digest.as_array());
    Ok((frame, digest))
}

fn decode_frame(frame: &[u8]) -> Result<DecodedFrame, DurableTopologyProposalRegistryError> {
    if frame.len() < 8 + 32 + 4 + 32 {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    let digest_offset = frame.len() - 32;
    let expected = Digest32::of_bytes(&frame[..digest_offset]);
    if expected.as_array() != &frame[digest_offset..] {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    let mut reader = ByteReader::new(&frame[..digest_offset]);
    let sequence = reader.u64()?;
    let predecessor_frame_digest = reader.digest()?;
    let payload_len = reader.u32()? as usize;
    if payload_len > MAX_PAYLOAD_BYTES || reader.remaining() != payload_len {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    let proposal = decode_proposal(reader.take(payload_len)?)?;
    Ok(DecodedFrame {
        sequence,
        predecessor_frame_digest,
        proposal,
        frame_digest: expected,
    })
}

fn encode_proposal(
    proposal: &TopologyProposalV2,
) -> Result<Vec<u8>, DurableTopologyProposalRegistryError> {
    verify_topology_proposal_v2(proposal)?;
    let mut writer = ByteWriter::new();
    writer.bytes(PAYLOAD_MAGIC);
    writer.id(&proposal.proposal_id)?;
    writer.id(&proposal.proposer_id)?;
    writer.id(&proposal.evaluator_id)?;
    writer.digest(proposal.selected_artifact_digest);
    writer.id(&proposal.window.window_id)?;
    writer.digest(proposal.window.window_digest);
    writer.u64(proposal.baseline_generation.get());
    writer.u64(proposal.candidate_generation.get());
    writer.digest(proposal.evaluation_digest);
    writer.digest(proposal.rollback_predecessor_digest);
    writer.len(proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        writer.id(&candidate.candidate_id)?;
        writer.u8(match candidate.kind {
            TopologyCandidateKindV2::NoChange => 0,
            TopologyCandidateKindV2::Update => 1,
        });
        writer.len(candidate.changes.len())?;
        for change in &candidate.changes {
            writer.id(&change.module_id)?;
            writer.u8(topology_operation_tag(change.operation));
            writer.optional_digest(change.predecessor_digest);
            writer.optional_digest(change.candidate_digest);
            writer.digest(change.migration_digest);
            writer.digest(change.rollback_digest);
            writer.digest(change.writer_handoff_digest);
            writer.digest(change.evidence_digest);
        }
    }
    writer.digest(proposal.proposal_digest);
    writer.u8(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    writer.u8(u8::from(proposal.authority.grants_any()));
    Ok(writer.finish())
}

fn decode_proposal(bytes: &[u8]) -> Result<TopologyProposalV2, DurableTopologyProposalRegistryError> {
    let mut reader = ByteReader::new(bytes);
    if reader.take(PAYLOAD_MAGIC.len())? != PAYLOAD_MAGIC {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    let proposal_id = reader.id()?;
    let proposer_id = reader.id()?;
    let evaluator_id = reader.id()?;
    let selected_artifact_digest = reader.digest()?;
    let window = ProposalWindowV2 {
        window_id: reader.id()?,
        window_digest: reader.digest()?,
    };
    let baseline_generation = Generation::new(reader.u64()?)
        .map_err(|_| DurableTopologyProposalRegistryError::Corrupt)?;
    let candidate_generation = Generation::new(reader.u64()?)
        .map_err(|_| DurableTopologyProposalRegistryError::Corrupt)?;
    let evaluation_digest = reader.digest()?;
    let rollback_predecessor_digest = reader.digest()?;
    let candidate_count = reader.bounded_len(32)?;
    let mut candidates = Vec::with_capacity(candidate_count);
    for _ in 0..candidate_count {
        let candidate_id = reader.id()?;
        let kind = match reader.u8()? {
            0 => TopologyCandidateKindV2::NoChange,
            1 => TopologyCandidateKindV2::Update,
            _ => return Err(DurableTopologyProposalRegistryError::Corrupt),
        };
        let change_count = reader.bounded_len(1)?;
        let mut changes = Vec::with_capacity(change_count);
        for _ in 0..change_count {
            changes.push(TopologyChangeV2 {
                module_id: reader.id()?,
                operation: topology_operation_from_tag(reader.u8()?)?,
                predecessor_digest: reader.optional_digest()?,
                candidate_digest: reader.optional_digest()?,
                migration_digest: reader.digest()?,
                rollback_digest: reader.digest()?,
                writer_handoff_digest: reader.digest()?,
                evidence_digest: reader.digest()?,
            });
        }
        candidates.push(TopologyCandidateV2 {
            candidate_id,
            kind,
            changes,
        });
    }
    let proposal_digest = reader.digest()?;
    let status = match reader.u8()? {
        0 => ProposalStatus::RequiresIndependentAcceptance,
        _ => return Err(DurableTopologyProposalRegistryError::Corrupt),
    };
    if reader.u8()? != 0 || reader.remaining() != 0 {
        return Err(DurableTopologyProposalRegistryError::Corrupt);
    }
    let proposal = TopologyProposalV2 {
        proposal_id,
        proposer_id,
        evaluator_id,
        selected_artifact_digest,
        window,
        baseline_generation,
        candidate_generation,
        evaluation_digest,
        rollback_predecessor_digest,
        candidates,
        proposal_digest,
        status,
        authority: AuthorityPosture::DENY_ALL,
    };
    verify_topology_proposal_v2(&proposal)?;
    Ok(proposal)
}

fn topology_operation_tag(operation: TopologyOperationV2) -> u8 {
    match operation {
        TopologyOperationV2::Add => 0,
        TopologyOperationV2::Remove => 1,
        TopologyOperationV2::Replace => 2,
        TopologyOperationV2::Split => 3,
        TopologyOperationV2::Merge => 4,
        TopologyOperationV2::Rewire => 5,
        TopologyOperationV2::Retire => 6,
    }
}
fn topology_operation_from_tag(
    tag: u8,
) -> Result<TopologyOperationV2, DurableTopologyProposalRegistryError> {
    match tag {
        0 => Ok(TopologyOperationV2::Add),
        1 => Ok(TopologyOperationV2::Remove),
        2 => Ok(TopologyOperationV2::Replace),
        3 => Ok(TopologyOperationV2::Split),
        4 => Ok(TopologyOperationV2::Merge),
        5 => Ok(TopologyOperationV2::Rewire),
        6 => Ok(TopologyOperationV2::Retire),
        _ => Err(DurableTopologyProposalRegistryError::Corrupt),
    }
}

struct ByteWriter {
    bytes: Vec<u8>,
}
impl ByteWriter {
    fn new() -> Self {
        Self { bytes: Vec::new() }
    }
    fn finish(self) -> Vec<u8> {
        self.bytes
    }
    fn bytes(&mut self, value: &[u8]) {
        self.bytes.extend_from_slice(value);
    }
    fn u8(&mut self, value: u8) {
        self.bytes.push(value);
    }
    fn u64(&mut self, value: u64) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
    fn digest(&mut self, value: Digest32) {
        self.bytes.extend_from_slice(value.as_array());
    }
    fn optional_digest(&mut self, value: Option<Digest32>) {
        match value {
            Some(value) => {
                self.u8(1);
                self.digest(value);
            }
            None => self.u8(0),
        }
    }
    fn len(&mut self, value: usize) -> Result<(), DurableTopologyProposalRegistryError> {
        let value = u32::try_from(value).map_err(|_| DurableTopologyProposalRegistryError::Capacity)?;
        self.bytes.extend_from_slice(&value.to_be_bytes());
        Ok(())
    }
    fn id(&mut self, value: &StableId) -> Result<(), DurableTopologyProposalRegistryError> {
        self.len(value.as_str().len())?;
        self.bytes.extend_from_slice(value.as_str().as_bytes());
        Ok(())
    }
}

struct ByteReader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> ByteReader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn remaining(&self) -> usize {
        self.bytes.len().saturating_sub(self.offset)
    }
    fn take(&mut self, count: usize) -> Result<&'a [u8], DurableTopologyProposalRegistryError> {
        let end = self
            .offset
            .checked_add(count)
            .filter(|end| *end <= self.bytes.len())
            .ok_or(DurableTopologyProposalRegistryError::Corrupt)?;
        let value = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(value)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], DurableTopologyProposalRegistryError> {
        self.take(N)?
            .try_into()
            .map_err(|_| DurableTopologyProposalRegistryError::Corrupt)
    }
    fn u8(&mut self) -> Result<u8, DurableTopologyProposalRegistryError> {
        Ok(self.array::<1>()?[0])
    }
    fn u32(&mut self) -> Result<u32, DurableTopologyProposalRegistryError> {
        Ok(u32::from_be_bytes(self.array()?))
    }
    fn u64(&mut self) -> Result<u64, DurableTopologyProposalRegistryError> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn digest(&mut self) -> Result<Digest32, DurableTopologyProposalRegistryError> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn optional_digest(&mut self) -> Result<Option<Digest32>, DurableTopologyProposalRegistryError> {
        match self.u8()? {
            0 => Ok(None),
            1 => Ok(Some(self.digest()?)),
            _ => Err(DurableTopologyProposalRegistryError::Corrupt),
        }
    }
    fn bounded_len(&mut self, maximum: usize) -> Result<usize, DurableTopologyProposalRegistryError> {
        let value = self.u32()? as usize;
        if value > maximum {
            return Err(DurableTopologyProposalRegistryError::Corrupt);
        }
        Ok(value)
    }
    fn id(&mut self) -> Result<StableId, DurableTopologyProposalRegistryError> {
        let length = self.bounded_len(128)?;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| DurableTopologyProposalRegistryError::Corrupt)?;
        StableId::new(value.to_owned()).map_err(|_| DurableTopologyProposalRegistryError::Corrupt)
    }
}
