//! Crash-recoverable append-only storage for topology V3 proposals.
//!
//! Persistence is intentionally separate from selection and runtime activation.
//! The host supplies a non-zero scope digest and writer fence, and retains the
//! returned anchor outside this file to detect valid-prefix rollback.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::{self, Read, Seek, SeekFrom, Write};

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{
    AppendDisposition, Error, ProposalStatus, TopologyCandidateKindV3,
    TopologyCandidateV3, TopologyDeltaV3, TopologyOperationV3, TopologyProposalV3,
    verify_topology_proposal_v3,
};
use crate::types::{MAX_CANDIDATES, MAX_PROPOSALS, MAX_TOPOLOGY_DELTAS};

const MAGIC: &[u8; 8] = b"HPTTPV03";
const VERSION: u16 = 3;
const HEADER_SIZE: usize = 8 + 2 + 8 + 4 + 32 + 32;
const MAX_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 8 + 32 + 4 + MAX_PAYLOAD_BYTES + 32;
const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;
const PAYLOAD_MAGIC: &[u8; 8] = b"HPTTOP03";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurableTopologyAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableTopologyAppendReceiptV1 {
    pub registry_scope_digest: Digest32,
    pub writer_fence: u64,
    pub sequence: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub selected_topology_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub disposition: AppendDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableTopologyRegistryError {
    Busy,
    NotRegular,
    InvalidLimit,
    InvalidScope,
    InvalidWriterFence,
    InvalidAnchor,
    AcknowledgedHistoryMissing,
    AnchorMismatch,
    ContextMismatch,
    Corrupt,
    Capacity,
    Conflict,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    Proposal(Error),
}

impl fmt::Display for DurableTopologyRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableTopologyRegistryError {}
impl From<io::Error> for DurableTopologyRegistryError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<Error> for DurableTopologyRegistryError {
    fn from(value: Error) -> Self {
        Self::Proposal(value)
    }
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableTopologyRegistryError> {
        if !file.metadata()?.is_file() {
            return Err(DurableTopologyRegistryError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableTopologyRegistryError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct DurableTopologyProposalRegistryV1 {
    file: LockedFile,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    proposals: BTreeMap<StableId, TopologyProposalV3>,
    slots: BTreeMap<(Digest32, u64), StableId>,
    frame_digests: Vec<Digest32>,
    receipts: BTreeMap<StableId, DurableTopologyAppendReceiptV1>,
    poisoned: bool,
}

impl DurableTopologyProposalRegistryV1 {
    pub fn open(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableTopologyRegistryError> {
        Self::open_inner(file, registry_scope_digest, writer_fence, maximum_records, None)
    }

    pub fn open_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableTopologyAnchorV1,
    ) -> Result<Self, DurableTopologyRegistryError> {
        Self::open_inner(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            Some(anchor),
        )
    }

    fn open_inner(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: Option<DurableTopologyAnchorV1>,
    ) -> Result<Self, DurableTopologyRegistryError> {
        if !(1..=MAX_PROPOSALS).contains(&maximum_records) {
            return Err(DurableTopologyRegistryError::InvalidLimit);
        }
        if registry_scope_digest.is_zero() {
            return Err(DurableTopologyRegistryError::InvalidScope);
        }
        if writer_fence == 0 {
            return Err(DurableTopologyRegistryError::InvalidWriterFence);
        }
        if anchor.is_some_and(|value| {
            value.sequence == 0
                || value.sequence > maximum_records as u64
                || value.frame_digest.is_zero()
        }) {
            return Err(DurableTopologyRegistryError::InvalidAnchor);
        }

        let expected_header = encode_header(registry_scope_digest, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let physical_len = file.0.metadata()?.len();
        if physical_len > MAX_FILE_BYTES {
            return Err(DurableTopologyRegistryError::Capacity);
        }
        file.0.seek(SeekFrom::Start(0))?;
        if physical_len == 0 {
            if anchor.is_some() {
                return Err(DurableTopologyRegistryError::AcknowledgedHistoryMissing);
            }
            file.0
                .write_all(&expected_header)
                .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
            file.0
                .sync_all()
                .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
        } else {
            if physical_len < HEADER_SIZE as u64 {
                return Err(DurableTopologyRegistryError::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.0.read_exact(&mut actual)?;
            validate_header(&actual)?;
            if actual != expected_header {
                return Err(DurableTopologyRegistryError::ContextMismatch);
            }
        }

        let mut store = Self {
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            proposals: BTreeMap::new(),
            slots: BTreeMap::new(),
            frame_digests: Vec::new(),
            receipts: BTreeMap::new(),
            poisoned: false,
        };
        let mut offset = HEADER_SIZE as u64;
        let physical_len = store.file.0.metadata()?.len();
        let mut incomplete_tail = false;
        while offset < physical_len {
            let remaining = physical_len - offset;
            if remaining < 4 {
                incomplete_tail = true;
                break;
            }
            store.file.0.seek(SeekFrom::Start(offset))?;
            let mut len = [0_u8; 4];
            store.file.0.read_exact(&mut len)?;
            let frame_len = u32::from_be_bytes(len) as usize;
            if !(8 + 32 + 4 + 32..=MAX_FRAME_BYTES).contains(&frame_len) {
                return Err(DurableTopologyRegistryError::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_len as u64)
                .ok_or(DurableTopologyRegistryError::Capacity)?;
            if remaining < total {
                incomplete_tail = true;
                break;
            }
            if store.frame_digests.len() >= maximum_records {
                return Err(DurableTopologyRegistryError::Capacity);
            }
            let mut frame = vec![0_u8; frame_len];
            store.file.0.read_exact(&mut frame)?;
            let decoded = decode_frame(&frame)?;
            let expected_sequence = store.frame_digests.len() as u64 + 1;
            let expected_predecessor = store
                .frame_digests
                .last()
                .copied()
                .unwrap_or(Digest32::ZERO);
            if decoded.sequence != expected_sequence
                || decoded.predecessor_frame_digest != expected_predecessor
            {
                return Err(DurableTopologyRegistryError::Corrupt);
            }
            store.insert_recovered(decoded)?;
            offset = offset
                .checked_add(total)
                .ok_or(DurableTopologyRegistryError::Capacity)?;
        }

        if let Some(anchor) = anchor {
            let Some(recovered) = anchor
                .sequence
                .checked_sub(1)
                .and_then(|index| usize::try_from(index).ok())
                .and_then(|index| store.frame_digests.get(index))
            else {
                return Err(DurableTopologyRegistryError::AcknowledgedHistoryMissing);
            };
            if *recovered != anchor.frame_digest {
                return Err(DurableTopologyRegistryError::AnchorMismatch);
            }
        }
        if incomplete_tail {
            store
                .file
                .0
                .set_len(offset)
                .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
            store
                .file
                .0
                .sync_all()
                .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
        }
        Ok(store)
    }

    pub fn append(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: TopologyProposalV3,
    ) -> Result<DurableTopologyAppendReceiptV1, DurableTopologyRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyRegistryError::Poisoned);
        }
        verify_topology_proposal_v3(&proposal)?;
        if let Some(existing) = self.receipts.get(&proposal.proposal_id) {
            if self.proposals.get(&proposal.proposal_id) == Some(&proposal) {
                let mut observed = existing.clone();
                observed.disposition = AppendDisposition::Unchanged;
                return Ok(observed);
            }
            return Err(DurableTopologyRegistryError::Conflict);
        }
        let slot = (
            proposal.selected_topology_digest,
            proposal.baseline_generation.get(),
        );
        if self.slots.contains_key(&slot) {
            return Err(DurableTopologyRegistryError::Conflict);
        }
        let current = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableTopologyRegistryError::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableTopologyRegistryError::Capacity);
        }

        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &proposal)?;
        let current_len = self.file.0.metadata()?.len();
        let new_len = current_len
            .checked_add(4 + frame.len() as u64)
            .ok_or(DurableTopologyRegistryError::Capacity)?;
        if new_len > MAX_FILE_BYTES {
            return Err(DurableTopologyRegistryError::Capacity);
        }

        self.poisoned = true;
        self.file.0.seek(SeekFrom::End(0))?;
        self.file
            .0
            .write_all(&(frame.len() as u32).to_be_bytes())
            .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
        self.file
            .0
            .write_all(&frame)
            .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;
        self.file
            .0
            .sync_data()
            .map_err(|_| DurableTopologyRegistryError::Indeterminate)?;

        let receipt = DurableTopologyAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_topology_digest: proposal.selected_topology_digest,
            predecessor_frame_digest: expected_predecessor_frame_digest,
            frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.slots.insert(slot, proposal.proposal_id.clone());
        self.proposals
            .insert(proposal.proposal_id.clone(), proposal);
        self.frame_digests.push(frame_digest);
        self.receipts.insert(receipt.proposal_id.clone(), receipt.clone());
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableTopologyAnchorV1>, DurableTopologyRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyRegistryError::Poisoned);
        }
        Ok(self
            .frame_digests
            .last()
            .copied()
            .map(|frame_digest| DurableTopologyAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            }))
    }

    pub fn get(
        &self,
        proposal_id: &StableId,
    ) -> Result<Option<&TopologyProposalV3>, DurableTopologyRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyRegistryError::Poisoned);
        }
        Ok(self.proposals.get(proposal_id))
    }

    pub fn record_count(&self) -> Result<usize, DurableTopologyRegistryError> {
        if self.poisoned {
            return Err(DurableTopologyRegistryError::Poisoned);
        }
        Ok(self.proposals.len())
    }

    fn insert_recovered(
        &mut self,
        decoded: DecodedFrame,
    ) -> Result<(), DurableTopologyRegistryError> {
        let proposal = decoded.proposal;
        let slot = (
            proposal.selected_topology_digest,
            proposal.baseline_generation.get(),
        );
        if self.proposals.contains_key(&proposal.proposal_id)
            || self.slots.contains_key(&slot)
        {
            return Err(DurableTopologyRegistryError::Corrupt);
        }
        let receipt = DurableTopologyAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence: decoded.sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_topology_digest: proposal.selected_topology_digest,
            predecessor_frame_digest: decoded.predecessor_frame_digest,
            frame_digest: decoded.frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.slots.insert(slot, proposal.proposal_id.clone());
        self.proposals
            .insert(proposal.proposal_id.clone(), proposal);
        self.frame_digests.push(decoded.frame_digest);
        self.receipts.insert(receipt.proposal_id.clone(), receipt);
        Ok(())
    }
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableTopologyRegistryError> {
    let maximum_records =
        u32::try_from(maximum_records).map_err(|_| DurableTopologyRegistryError::InvalidLimit)?;
    let mut bytes = Vec::with_capacity(HEADER_SIZE);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&VERSION.to_be_bytes());
    bytes.extend_from_slice(&writer_fence.to_be_bytes());
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    bytes.extend_from_slice(scope.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    Ok(bytes)
}

fn validate_header(bytes: &[u8]) -> Result<(), DurableTopologyRegistryError> {
    if bytes.len() != HEADER_SIZE
        || &bytes[..8] != MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != VERSION
        || Digest32::of_bytes(&bytes[..HEADER_SIZE - 32]).as_array()
            != &bytes[HEADER_SIZE - 32..]
    {
        return Err(DurableTopologyRegistryError::Corrupt);
    }
    Ok(())
}

struct DecodedFrame {
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: TopologyProposalV3,
    frame_digest: Digest32,
}

fn encode_frame(
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: &TopologyProposalV3,
) -> Result<(Vec<u8>, Digest32), DurableTopologyRegistryError> {
    let payload = encode_proposal(proposal)?;
    let mut frame = Vec::with_capacity(8 + 32 + 4 + payload.len() + 32);
    frame.extend_from_slice(&sequence.to_be_bytes());
    frame.extend_from_slice(predecessor_frame_digest.as_array());
    frame.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    frame.extend_from_slice(&payload);
    let digest = Digest32::of_bytes(&frame);
    frame.extend_from_slice(digest.as_array());
    Ok((frame, digest))
}

fn decode_frame(frame: &[u8]) -> Result<DecodedFrame, DurableTopologyRegistryError> {
    if frame.len() < 8 + 32 + 4 + 32 || frame.len() > MAX_FRAME_BYTES {
        return Err(DurableTopologyRegistryError::Corrupt);
    }
    let digest_offset = frame.len() - 32;
    let expected = Digest32::of_bytes(&frame[..digest_offset]);
    if expected.as_array() != &frame[digest_offset..] {
        return Err(DurableTopologyRegistryError::Corrupt);
    }
    let mut reader = Reader::new(&frame[..digest_offset]);
    let sequence = reader.u64()?;
    let predecessor_frame_digest = reader.digest()?;
    let payload_len = reader.u32()? as usize;
    if payload_len > MAX_PAYLOAD_BYTES || reader.remaining() != payload_len {
        return Err(DurableTopologyRegistryError::Corrupt);
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
    proposal: &TopologyProposalV3,
) -> Result<Vec<u8>, DurableTopologyRegistryError> {
    verify_topology_proposal_v3(proposal)?;
    let mut writer = Writer::default();
    writer.bytes(PAYLOAD_MAGIC);
    writer.id(&proposal.proposal_id)?;
    writer.id(&proposal.proposer_id)?;
    writer.id(&proposal.evaluator_id)?;
    writer.digest(proposal.selected_topology_digest);
    writer.u64(proposal.baseline_generation.get());
    writer.u64(proposal.candidate_generation.get());
    writer.digest(proposal.evaluation_digest);
    writer.digest(proposal.rollback_predecessor_digest);
    writer.len(proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        writer.id(&candidate.candidate_id)?;
        writer.u8(match candidate.kind {
            TopologyCandidateKindV3::NoChange => 0,
            TopologyCandidateKindV3::Change => 1,
        });
        writer.len(candidate.topology_deltas.len())?;
        for delta in &candidate.topology_deltas {
            writer.id(&delta.module_id)?;
            writer.u8(match delta.operation {
                TopologyOperationV3::Add => 0,
                TopologyOperationV3::Replace => 1,
                TopologyOperationV3::Retire => 2,
                TopologyOperationV3::Rewire => 3,
                TopologyOperationV3::Split => 4,
                TopologyOperationV3::Merge => 5,
            });
            writer.len(delta.related_module_ids.len())?;
            for related in &delta.related_module_ids {
                writer.id(related)?;
            }
            writer.digest(delta.predecessor_digest);
            writer.digest(delta.candidate_digest);
            writer.digest(delta.evidence_digest);
        }
        writer.digest(candidate.candidate_digest);
    }
    writer.digest(proposal.proposal_digest);
    writer.u8(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    writer.u8(u8::from(proposal.authority.grants_any()));
    if writer.0.len() > MAX_PAYLOAD_BYTES {
        return Err(DurableTopologyRegistryError::Capacity);
    }
    Ok(writer.0)
}

fn decode_proposal(bytes: &[u8]) -> Result<TopologyProposalV3, DurableTopologyRegistryError> {
    let mut reader = Reader::new(bytes);
    if reader.take(PAYLOAD_MAGIC.len())? != PAYLOAD_MAGIC {
        return Err(DurableTopologyRegistryError::Corrupt);
    }
    let proposal_id = reader.id()?;
    let proposer_id = reader.id()?;
    let evaluator_id = reader.id()?;
    let selected_topology_digest = reader.digest()?;
    let baseline_generation =
        Generation::new(reader.u64()?).map_err(|_| DurableTopologyRegistryError::Corrupt)?;
    let candidate_generation =
        Generation::new(reader.u64()?).map_err(|_| DurableTopologyRegistryError::Corrupt)?;
    let evaluation_digest = reader.digest()?;
    let rollback_predecessor_digest = reader.digest()?;
    let candidate_count = reader.bounded_len(MAX_CANDIDATES)?;
    let mut candidates = Vec::with_capacity(candidate_count);
    let mut total_deltas = 0_usize;
    for _ in 0..candidate_count {
        let candidate_id = reader.id()?;
        let kind = match reader.u8()? {
            0 => TopologyCandidateKindV3::NoChange,
            1 => TopologyCandidateKindV3::Change,
            _ => return Err(DurableTopologyRegistryError::Corrupt),
        };
        let delta_count = reader.bounded_len(MAX_TOPOLOGY_DELTAS)?;
        total_deltas = total_deltas
            .checked_add(delta_count)
            .filter(|count| *count <= MAX_TOPOLOGY_DELTAS)
            .ok_or(DurableTopologyRegistryError::Corrupt)?;
        let mut topology_deltas = Vec::with_capacity(delta_count);
        for _ in 0..delta_count {
            let module_id = reader.id()?;
            let operation = match reader.u8()? {
                0 => TopologyOperationV3::Add,
                1 => TopologyOperationV3::Replace,
                2 => TopologyOperationV3::Retire,
                3 => TopologyOperationV3::Rewire,
                4 => TopologyOperationV3::Split,
                5 => TopologyOperationV3::Merge,
                _ => return Err(DurableTopologyRegistryError::Corrupt),
            };
            let related_count = reader.bounded_len(MAX_TOPOLOGY_DELTAS)?;
            let mut related_module_ids = Vec::with_capacity(related_count);
            for _ in 0..related_count {
                related_module_ids.push(reader.id()?);
            }
            topology_deltas.push(TopologyDeltaV3 {
                module_id,
                operation,
                related_module_ids,
                predecessor_digest: reader.digest()?,
                candidate_digest: reader.digest()?,
                evidence_digest: reader.digest()?,
            });
        }
        candidates.push(TopologyCandidateV3 {
            candidate_id,
            kind,
            topology_deltas,
            candidate_digest: reader.digest()?,
        });
    }
    let proposal_digest = reader.digest()?;
    let status = match reader.u8()? {
        0 => ProposalStatus::RequiresIndependentAcceptance,
        _ => return Err(DurableTopologyRegistryError::Corrupt),
    };
    if reader.u8()? != 0 || reader.remaining() != 0 {
        return Err(DurableTopologyRegistryError::Corrupt);
    }
    let proposal = TopologyProposalV3 {
        proposal_id,
        proposer_id,
        evaluator_id,
        selected_topology_digest,
        baseline_generation,
        candidate_generation,
        evaluation_digest,
        rollback_predecessor_digest,
        candidates,
        proposal_digest,
        status,
        authority: AuthorityPosture::DENY_ALL,
    };
    verify_topology_proposal_v3(&proposal)?;
    Ok(proposal)
}

#[derive(Default)]
struct Writer(Vec<u8>);
impl Writer {
    fn bytes(&mut self, value: &[u8]) { self.0.extend_from_slice(value); }
    fn u8(&mut self, value: u8) { self.0.push(value); }
    fn u32(&mut self, value: u32) { self.0.extend_from_slice(&value.to_be_bytes()); }
    fn u64(&mut self, value: u64) { self.0.extend_from_slice(&value.to_be_bytes()); }
    fn digest(&mut self, value: Digest32) { self.0.extend_from_slice(value.as_array()); }
    fn len(&mut self, value: usize) -> Result<(), DurableTopologyRegistryError> {
        self.u32(u32::try_from(value).map_err(|_| DurableTopologyRegistryError::Capacity)?);
        Ok(())
    }
    fn id(&mut self, value: &StableId) -> Result<(), DurableTopologyRegistryError> {
        let bytes = value.as_str().as_bytes();
        self.len(bytes.len())?;
        self.bytes(bytes);
        Ok(())
    }
}

struct Reader<'a> { bytes: &'a [u8], offset: usize }
impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self { Self { bytes, offset: 0 } }
    fn remaining(&self) -> usize { self.bytes.len().saturating_sub(self.offset) }
    fn take(&mut self, count: usize) -> Result<&'a [u8], DurableTopologyRegistryError> {
        let end = self.offset.checked_add(count).ok_or(DurableTopologyRegistryError::Corrupt)?;
        if end > self.bytes.len() { return Err(DurableTopologyRegistryError::Corrupt); }
        let value = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(value)
    }
    fn u8(&mut self) -> Result<u8, DurableTopologyRegistryError> { Ok(self.take(1)?[0]) }
    fn u32(&mut self) -> Result<u32, DurableTopologyRegistryError> {
        Ok(u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| DurableTopologyRegistryError::Corrupt)?))
    }
    fn u64(&mut self) -> Result<u64, DurableTopologyRegistryError> {
        Ok(u64::from_be_bytes(self.take(8)?.try_into().map_err(|_| DurableTopologyRegistryError::Corrupt)?))
    }
    fn digest(&mut self) -> Result<Digest32, DurableTopologyRegistryError> {
        Ok(Digest32::from_array(self.take(32)?.try_into().map_err(|_| DurableTopologyRegistryError::Corrupt)?))
    }
    fn bounded_len(&mut self, maximum: usize) -> Result<usize, DurableTopologyRegistryError> {
        let value = self.u32()? as usize;
        if value > maximum { return Err(DurableTopologyRegistryError::Corrupt); }
        Ok(value)
    }
    fn id(&mut self) -> Result<StableId, DurableTopologyRegistryError> {
        let len = self.bounded_len(4096)?;
        let value = std::str::from_utf8(self.take(len)?).map_err(|_| DurableTopologyRegistryError::Corrupt)?;
        StableId::new(value).map_err(|_| DurableTopologyRegistryError::Corrupt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        TopologyCandidateRequestV3, TopologyProposalRequestV3, propose_topology_v3,
    };

    fn id(value: &str) -> StableId { StableId::new(value).expect("id") }
    fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
    fn generation(value: u64) -> Generation { Generation::new(value).expect("generation") }

    fn proposal() -> TopologyProposalV3 {
        let selected = digest("topology-v1");
        propose_topology_v3(TopologyProposalRequestV3 {
            proposal_id: id("topology-proposal-1"),
            proposer_id: id("generator"),
            evaluator_id: id("evaluator"),
            selected_topology_digest: selected,
            baseline_generation: generation(4),
            candidate_generation: generation(5),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: selected,
            candidates: vec![
                TopologyCandidateRequestV3 {
                    candidate_id: id("no-change"),
                    kind: TopologyCandidateKindV3::NoChange,
                    topology_deltas: Vec::new(),
                },
                TopologyCandidateRequestV3 {
                    candidate_id: id("replace-memory"),
                    kind: TopologyCandidateKindV3::Change,
                    topology_deltas: vec![TopologyDeltaV3 {
                        module_id: id("memory.retrieval"),
                        operation: TopologyOperationV3::Replace,
                        related_module_ids: Vec::new(),
                        predecessor_digest: digest("memory-v1"),
                        candidate_digest: digest("memory-v2"),
                        evidence_digest: digest("memory-evidence"),
                    }],
                },
            ],
        }).expect("proposal")
    }

    fn file(temp: &tempfile::TempDir) -> File {
        std::fs::OpenOptions::new()
            .read(true).write(true).create(true)
            .open(temp.path().join("topology-proposals.log"))
            .expect("file")
    }

    #[test]
    fn durable_topology_reopens_exact_history_and_idempotent_retry() {
        let temp = tempfile::tempdir().expect("temp");
        let scope = digest("scope");
        let proposal = proposal();
        let anchor = {
            let mut store =
                DurableTopologyProposalRegistryV1::open(file(&temp), scope, 7, 32).expect("open");
            let receipt = store.append(Digest32::ZERO, proposal.clone()).expect("append");
            assert_eq!(receipt.disposition, AppendDisposition::Inserted);
            let retry = store.append(Digest32::ZERO, proposal.clone()).expect("retry");
            assert_eq!(retry.disposition, AppendDisposition::Unchanged);
            store.current_anchor().expect("anchor").expect("some")
        };
        let reopened = DurableTopologyProposalRegistryV1::open_anchored(
            file(&temp), scope, 7, 32, anchor,
        ).expect("reopen");
        assert_eq!(reopened.record_count().expect("count"), 1);
        assert_eq!(reopened.get(&proposal.proposal_id).expect("get"), Some(&proposal));
    }

    #[test]
    fn durable_topology_rejects_wrong_anchor_and_competing_slot() {
        let temp = tempfile::tempdir().expect("temp");
        let scope = digest("scope");
        let proposal = proposal();
        let mut store =
            DurableTopologyProposalRegistryV1::open(file(&temp), scope, 9, 32).expect("open");
        let receipt = store.append(Digest32::ZERO, proposal.clone()).expect("append");
        drop(store);
        assert!(matches!(
            DurableTopologyProposalRegistryV1::open_anchored(
                file(&temp),
                scope,
                9,
                32,
                DurableTopologyAnchorV1 {
                    sequence: receipt.sequence,
                    frame_digest: digest("wrong"),
                },
            ),
            Err(DurableTopologyRegistryError::AnchorMismatch)
        ));
    }
}
