//! Anchored durable registry for governed topology proposals.
//!
//! Stores the full governed proposal (typed writer handoffs plus authenticated
//! admission digests), not merely a detached proposal digest. The registry is
//! proposal-only and exposes no topology-application authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::{File, TryLockError};
use std::io::{Read, Seek, SeekFrom, Write};
use std::ops::{Deref, DerefMut};

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{
    AppendDisposition, GovernedTopologyProposalV1, ProposalStatus, ProposalWindowV2,
    TopologyCandidateKindV2, TopologyCandidateV2, TopologyChangeV2, TopologyGovernanceErrorV1,
    TopologyOperationV2, TopologyProposalV2, admit_governed_topology_v1,
};

const MAGIC: &[u8; 8] = b"HPTTOP02";
const PAYLOAD_MAGIC: &[u8; 8] = b"HPTTGV01";
const FORMAT_VERSION: u16 = 1;
const HEADER_SIZE: usize = 8 + 2 + 8 + 4 + 32 + 32;
const MAX_RECORDS: usize = 4_096;
const MAX_PAYLOAD_BYTES: usize = 2 * 1024 * 1024;
const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurableTopologyRegistryAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableTopologyAppendReceiptV1 {
    pub sequence: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub admission_digest: Digest32,
    pub frame_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub disposition: AppendDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableTopologyRegistryErrorV1 {
    Busy,
    NotRegular,
    InvalidScope,
    InvalidFence,
    InvalidLimit,
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
    Io(std::io::ErrorKind),
    Governance(TopologyGovernanceErrorV1),
}

impl fmt::Display for DurableTopologyRegistryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableTopologyRegistryErrorV1 {}
impl From<std::io::Error> for DurableTopologyRegistryErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<TopologyGovernanceErrorV1> for DurableTopologyRegistryErrorV1 {
    fn from(value: TopologyGovernanceErrorV1) -> Self {
        Self::Governance(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
struct TopologySlotV1 {
    selected_artifact_digest: Digest32,
    window_id: StableId,
}

#[derive(Clone, Copy)]
enum RecoveryPolicy {
    BootstrapEmpty,
    Require(DurableTopologyRegistryAnchorV1),
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableTopologyRegistryErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(DurableTopologyRegistryErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableTopologyRegistryErrorV1::Busy),
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

pub struct DurableTopologyProposalRegistryV1 {
    file: LockedFile,
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    by_slot: BTreeMap<TopologySlotV1, GovernedTopologyProposalV1>,
    by_id: BTreeMap<StableId, TopologySlotV1>,
    receipts: BTreeMap<StableId, DurableTopologyAppendReceiptV1>,
    frame_digests: Vec<Digest32>,
    poisoned: bool,
}

impl DurableTopologyProposalRegistryV1 {
    pub fn bootstrap_empty(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableTopologyRegistryErrorV1> {
        Self::open_with_policy(
            file,
            scope,
            writer_fence,
            maximum_records,
            RecoveryPolicy::BootstrapEmpty,
        )
    }

    pub fn reopen_anchored(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableTopologyRegistryAnchorV1,
    ) -> Result<Self, DurableTopologyRegistryErrorV1> {
        Self::open_with_policy(
            file,
            scope,
            writer_fence,
            maximum_records,
            RecoveryPolicy::Require(anchor),
        )
    }

    fn open_with_policy(
        file: File,
        scope: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        policy: RecoveryPolicy,
    ) -> Result<Self, DurableTopologyRegistryErrorV1> {
        if scope.is_zero() {
            return Err(DurableTopologyRegistryErrorV1::InvalidScope);
        }
        if writer_fence == 0 {
            return Err(DurableTopologyRegistryErrorV1::InvalidFence);
        }
        if !(1..=MAX_RECORDS).contains(&maximum_records) {
            return Err(DurableTopologyRegistryErrorV1::InvalidLimit);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && (anchor.sequence == 0
                || anchor.sequence > maximum_records as u64
                || anchor.frame_digest.is_zero())
        {
            return Err(DurableTopologyRegistryErrorV1::InvalidAnchor);
        }

        let expected_header = encode_header(scope, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let length = file.metadata()?.len();
        if length > MAX_FILE_BYTES {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }
        if matches!(policy, RecoveryPolicy::BootstrapEmpty) && length != 0 {
            return Err(DurableTopologyRegistryErrorV1::BootstrapRequiresEmptyFile);
        }
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            if matches!(policy, RecoveryPolicy::Require(_)) {
                return Err(DurableTopologyRegistryErrorV1::AcknowledgedHistoryMissing);
            }
            file.write_all(&expected_header)
                .and_then(|_| file.sync_all())
                .map_err(|_| DurableTopologyRegistryErrorV1::Indeterminate)?;
        } else {
            if length < HEADER_SIZE as u64 {
                return Err(DurableTopologyRegistryErrorV1::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.read_exact(&mut actual)?;
            validate_header(&actual)?;
            if actual != expected_header {
                return Err(DurableTopologyRegistryErrorV1::ContextMismatch);
            }
        }

        let mut store = Self {
            file,
            scope,
            writer_fence,
            maximum_records,
            by_slot: BTreeMap::new(),
            by_id: BTreeMap::new(),
            receipts: BTreeMap::new(),
            frame_digests: Vec::new(),
            poisoned: false,
        };
        let physical_length = store.file.metadata()?.len();
        let mut offset = HEADER_SIZE as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            store.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            store.file.read_exact(&mut length_bytes)?;
            let frame_len = u32::from_be_bytes(length_bytes) as usize;
            if frame_len < 8 + 32 + 4 + 32 || frame_len > MAX_PAYLOAD_BYTES + 76 {
                return Err(DurableTopologyRegistryErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_len as u64)
                .ok_or(DurableTopologyRegistryErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if store.frame_digests.len() >= maximum_records {
                return Err(DurableTopologyRegistryErrorV1::Capacity);
            }
            let mut frame = vec![0_u8; frame_len];
            store.file.read_exact(&mut frame)?;
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
                return Err(DurableTopologyRegistryErrorV1::Corrupt);
            }
            let proposal_id = decoded.record.proposal.proposal_id.clone();
            let proposal_digest = decoded.record.proposal.proposal_digest;
            let admission_digest = decoded.record.admission_digest;
            if store.insert_memory(decoded.record)? != AppendDisposition::Inserted {
                return Err(DurableTopologyRegistryErrorV1::Corrupt);
            }
            let replay_receipt = DurableTopologyAppendReceiptV1 {
                sequence: decoded.sequence,
                proposal_id: proposal_id.clone(),
                proposal_digest,
                admission_digest,
                frame_digest: decoded.frame_digest,
                predecessor_frame_digest: decoded.predecessor_frame_digest,
                disposition: AppendDisposition::Inserted,
                authority: AuthorityPosture::DENY_ALL,
            };
            if store.receipts.insert(proposal_id, replay_receipt).is_some() {
                return Err(DurableTopologyRegistryErrorV1::Corrupt);
            }
            store.frame_digests.push(decoded.frame_digest);
            offset = offset
                .checked_add(total)
                .ok_or(DurableTopologyRegistryErrorV1::Capacity)?;
        }

        if let RecoveryPolicy::Require(anchor) = policy {
            let recovered = anchor
                .sequence
                .checked_sub(1)
                .and_then(|value| usize::try_from(value).ok())
                .and_then(|index| store.frame_digests.get(index))
                .ok_or(DurableTopologyRegistryErrorV1::AcknowledgedHistoryMissing)?;
            if *recovered != anchor.frame_digest {
                return Err(DurableTopologyRegistryErrorV1::AnchorMismatch);
            }
        }
        if incomplete_tail {
            store
                .file
                .set_len(offset)
                .and_then(|_| store.file.sync_all())
                .map_err(|_| DurableTopologyRegistryErrorV1::Indeterminate)?;
        }
        Ok(store)
    }

    pub fn append(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        record: GovernedTopologyProposalV1,
    ) -> Result<DurableTopologyAppendReceiptV1, DurableTopologyRegistryErrorV1> {
        if self.poisoned {
            return Err(DurableTopologyRegistryErrorV1::Poisoned);
        }
        let verified = admit_governed_topology_v1(
            record.proposal.clone(),
            record.handoffs.clone(),
            record.source_authentication_digest,
            record.evaluation_authentication_digest,
        )?;
        if verified != record {
            return Err(DurableTopologyRegistryErrorV1::Corrupt);
        }
        if let Some(slot) = self.by_id.get(&record.proposal.proposal_id)
            && let Some(existing) = self.by_slot.get(slot)
            && existing == &record
        {
            let mut receipt = self
                .receipts
                .get(&record.proposal.proposal_id)
                .cloned()
                .ok_or(DurableTopologyRegistryErrorV1::Corrupt)?;
            receipt.disposition = AppendDisposition::Unchanged;
            return Ok(receipt);
        }
        let current = self
            .frame_digests
            .last()
            .copied()
            .unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableTopologyRegistryErrorV1::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }

        let mut candidate_slots = self.by_slot.clone();
        let mut candidate_ids = self.by_id.clone();
        insert_maps(&mut candidate_slots, &mut candidate_ids, record.clone(), self.maximum_records)?;

        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &record)?;
        let offset = self.file.metadata()?.len();
        let next = offset
            .checked_add(4 + frame.len() as u64)
            .ok_or(DurableTopologyRegistryErrorV1::Capacity)?;
        if next > MAX_FILE_BYTES {
            return Err(DurableTopologyRegistryErrorV1::Capacity);
        }

        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(frame.len() as u32).to_be_bytes())
            .and_then(|_| self.file.write_all(&frame))
            .and_then(|_| self.file.sync_data())
            .map_err(|_| DurableTopologyRegistryErrorV1::Indeterminate)?;
        let receipt = DurableTopologyAppendReceiptV1 {
            sequence,
            proposal_id: record.proposal.proposal_id.clone(),
            proposal_digest: record.proposal.proposal_digest,
            admission_digest: record.admission_digest,
            frame_digest,
            predecessor_frame_digest: expected_predecessor_frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.by_slot = candidate_slots;
        self.by_id = candidate_ids;
        self.receipts.insert(receipt.proposal_id.clone(), receipt.clone());
        self.frame_digests.push(frame_digest);
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableTopologyRegistryAnchorV1>, DurableTopologyRegistryErrorV1> {
        if self.poisoned {
            return Err(DurableTopologyRegistryErrorV1::Poisoned);
        }
        Ok(self.frame_digests.last().copied().map(|frame_digest| {
            DurableTopologyRegistryAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            }
        }))
    }

    pub fn record_count(&self) -> Result<usize, DurableTopologyRegistryErrorV1> {
        if self.poisoned {
            Err(DurableTopologyRegistryErrorV1::Poisoned)
        } else {
            Ok(self.by_slot.len())
        }
    }

    fn insert_memory(
        &mut self,
        record: GovernedTopologyProposalV1,
    ) -> Result<AppendDisposition, DurableTopologyRegistryErrorV1> {
        insert_maps(
            &mut self.by_slot,
            &mut self.by_id,
            record,
            self.maximum_records,
        )
    }
}

fn insert_maps(
    by_slot: &mut BTreeMap<TopologySlotV1, GovernedTopologyProposalV1>,
    by_id: &mut BTreeMap<StableId, TopologySlotV1>,
    record: GovernedTopologyProposalV1,
    maximum_records: usize,
) -> Result<AppendDisposition, DurableTopologyRegistryErrorV1> {
    let slot = TopologySlotV1 {
        selected_artifact_digest: record.proposal.selected_artifact_digest,
        window_id: record.proposal.window.window_id.clone(),
    };
    if let Some(existing) = by_slot.get(&slot) {
        if existing == &record {
            return Ok(AppendDisposition::Unchanged);
        }
        return Err(DurableTopologyRegistryErrorV1::Conflict);
    }
    if by_id.contains_key(&record.proposal.proposal_id) || by_slot.len() >= maximum_records {
        return Err(DurableTopologyRegistryErrorV1::Conflict);
    }
    by_id.insert(record.proposal.proposal_id.clone(), slot.clone());
    by_slot.insert(slot, record);
    Ok(AppendDisposition::Inserted)
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableTopologyRegistryErrorV1> {
    let maximum_records =
        u32::try_from(maximum_records).map_err(|_| DurableTopologyRegistryErrorV1::InvalidLimit)?;
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

fn validate_header(bytes: &[u8]) -> Result<(), DurableTopologyRegistryErrorV1> {
    if bytes.len() != HEADER_SIZE
        || &bytes[..8] != MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != FORMAT_VERSION
        || Digest32::of_bytes(&bytes[..HEADER_SIZE - 32]).as_array() != &bytes[HEADER_SIZE - 32..]
    {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    Ok(())
}

struct DecodedFrame {
    sequence: u64,
    predecessor_frame_digest: Digest32,
    record: GovernedTopologyProposalV1,
    frame_digest: Digest32,
}

fn encode_frame(
    sequence: u64,
    predecessor_frame_digest: Digest32,
    record: &GovernedTopologyProposalV1,
) -> Result<(Vec<u8>, Digest32), DurableTopologyRegistryErrorV1> {
    let payload = encode_record(record)?;
    if payload.len() > MAX_PAYLOAD_BYTES {
        return Err(DurableTopologyRegistryErrorV1::Capacity);
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

fn decode_frame(frame: &[u8]) -> Result<DecodedFrame, DurableTopologyRegistryErrorV1> {
    if frame.len() < 8 + 32 + 4 + 32 {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let digest_offset = frame.len() - 32;
    let digest = Digest32::of_bytes(&frame[..digest_offset]);
    if digest.as_array() != &frame[digest_offset..] {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let mut reader = Reader::new(&frame[..digest_offset]);
    let sequence = reader.u64()?;
    let predecessor_frame_digest = reader.digest()?;
    let payload_len = reader.u32()? as usize;
    if payload_len > MAX_PAYLOAD_BYTES || reader.remaining() != payload_len {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let record = decode_record(reader.take(payload_len)?)?;
    Ok(DecodedFrame {
        sequence,
        predecessor_frame_digest,
        record,
        frame_digest: digest,
    })
}

fn encode_record(
    record: &GovernedTopologyProposalV1,
) -> Result<Vec<u8>, DurableTopologyRegistryErrorV1> {
    let verified = admit_governed_topology_v1(
        record.proposal.clone(),
        record.handoffs.clone(),
        record.source_authentication_digest,
        record.evaluation_authentication_digest,
    )?;
    if &verified != record {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let mut w = Writer::new();
    w.bytes(PAYLOAD_MAGIC);
    encode_proposal(&mut w, &record.proposal)?;
    w.len(record.handoffs.len())?;
    for handoff in &record.handoffs {
        w.id(&handoff.module_id)?;
        w.id(&handoff.from_owner)?;
        w.id(&handoff.to_owner)?;
        w.u64(handoff.predecessor_writer_fence);
        w.u64(handoff.successor_writer_fence);
        w.digest(handoff.source_store_digest);
        w.digest(handoff.migration_digest);
        w.digest(handoff.rollback_digest);
        w.digest(handoff.acknowledgement_contract_digest);
        w.digest(handoff.plan_digest);
    }
    w.digest(record.handoff_set_digest);
    w.digest(record.source_authentication_digest);
    w.digest(record.evaluation_authentication_digest);
    w.digest(record.admission_digest);
    Ok(w.finish())
}

fn decode_record(bytes: &[u8]) -> Result<GovernedTopologyProposalV1, DurableTopologyRegistryErrorV1> {
    let mut r = Reader::new(bytes);
    if r.take(PAYLOAD_MAGIC.len())? != PAYLOAD_MAGIC {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let proposal = decode_proposal(&mut r)?;
    let handoff_count = r.bounded_len(31)?;
    let mut handoffs = Vec::with_capacity(handoff_count);
    for _ in 0..handoff_count {
        handoffs.push(crate::WriterHandoffPlanV1 {
            module_id: r.id()?,
            from_owner: r.id()?,
            to_owner: r.id()?,
            predecessor_writer_fence: r.u64()?,
            successor_writer_fence: r.u64()?,
            source_store_digest: r.digest()?,
            migration_digest: r.digest()?,
            rollback_digest: r.digest()?,
            acknowledgement_contract_digest: r.digest()?,
            plan_digest: r.digest()?,
        });
    }
    let handoff_set_digest = r.digest()?;
    let source_authentication_digest = r.digest()?;
    let evaluation_authentication_digest = r.digest()?;
    let admission_digest = r.digest()?;
    if r.remaining() != 0 {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    let expected = admit_governed_topology_v1(
        proposal,
        handoffs,
        source_authentication_digest,
        evaluation_authentication_digest,
    )?;
    if expected.handoff_set_digest != handoff_set_digest
        || expected.admission_digest != admission_digest
    {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    Ok(expected)
}

fn encode_proposal(
    w: &mut Writer,
    proposal: &TopologyProposalV2,
) -> Result<(), DurableTopologyRegistryErrorV1> {
    w.id(&proposal.proposal_id)?;
    w.id(&proposal.proposer_id)?;
    w.id(&proposal.evaluator_id)?;
    w.digest(proposal.selected_artifact_digest);
    w.id(&proposal.window.window_id)?;
    w.digest(proposal.window.window_digest);
    w.u64(proposal.baseline_generation.get());
    w.u64(proposal.candidate_generation.get());
    w.digest(proposal.evaluation_digest);
    w.digest(proposal.rollback_predecessor_digest);
    w.len(proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        w.id(&candidate.candidate_id)?;
        w.u8(match candidate.kind {
            TopologyCandidateKindV2::NoChange => 0,
            TopologyCandidateKindV2::Update => 1,
        });
        w.len(candidate.changes.len())?;
        for change in &candidate.changes {
            w.id(&change.module_id)?;
            w.u8(operation_tag(change.operation));
            w.optional_digest(change.predecessor_digest);
            w.optional_digest(change.candidate_digest);
            w.digest(change.migration_digest);
            w.digest(change.rollback_digest);
            w.digest(change.writer_handoff_digest);
            w.digest(change.evidence_digest);
        }
    }
    w.digest(proposal.proposal_digest);
    w.u8(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    w.u8(u8::from(proposal.authority.grants_any()));
    Ok(())
}

fn decode_proposal(r: &mut Reader<'_>) -> Result<TopologyProposalV2, DurableTopologyRegistryErrorV1> {
    let proposal_id = r.id()?;
    let proposer_id = r.id()?;
    let evaluator_id = r.id()?;
    let selected_artifact_digest = r.digest()?;
    let window = ProposalWindowV2 {
        window_id: r.id()?,
        window_digest: r.digest()?,
    };
    let baseline_generation =
        Generation::new(r.u64()?).map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)?;
    let candidate_generation =
        Generation::new(r.u64()?).map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)?;
    let evaluation_digest = r.digest()?;
    let rollback_predecessor_digest = r.digest()?;
    let candidate_count = r.bounded_len(32)?;
    let mut candidates = Vec::with_capacity(candidate_count);
    for _ in 0..candidate_count {
        let candidate_id = r.id()?;
        let kind = match r.u8()? {
            0 => TopologyCandidateKindV2::NoChange,
            1 => TopologyCandidateKindV2::Update,
            _ => return Err(DurableTopologyRegistryErrorV1::Corrupt),
        };
        let change_count = r.bounded_len(1)?;
        let mut changes = Vec::with_capacity(change_count);
        for _ in 0..change_count {
            changes.push(TopologyChangeV2 {
                module_id: r.id()?,
                operation: decode_operation(r.u8()?)?,
                predecessor_digest: r.optional_digest()?,
                candidate_digest: r.optional_digest()?,
                migration_digest: r.digest()?,
                rollback_digest: r.digest()?,
                writer_handoff_digest: r.digest()?,
                evidence_digest: r.digest()?,
            });
        }
        candidates.push(TopologyCandidateV2 {
            candidate_id,
            kind,
            changes,
        });
    }
    let proposal_digest = r.digest()?;
    let status = match r.u8()? {
        0 => ProposalStatus::RequiresIndependentAcceptance,
        _ => return Err(DurableTopologyRegistryErrorV1::Corrupt),
    };
    if r.u8()? != 0 {
        return Err(DurableTopologyRegistryErrorV1::Corrupt);
    }
    Ok(TopologyProposalV2 {
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
    })
}

fn operation_tag(operation: TopologyOperationV2) -> u8 {
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
fn decode_operation(value: u8) -> Result<TopologyOperationV2, DurableTopologyRegistryErrorV1> {
    match value {
        0 => Ok(TopologyOperationV2::Add),
        1 => Ok(TopologyOperationV2::Remove),
        2 => Ok(TopologyOperationV2::Replace),
        3 => Ok(TopologyOperationV2::Split),
        4 => Ok(TopologyOperationV2::Merge),
        5 => Ok(TopologyOperationV2::Rewire),
        6 => Ok(TopologyOperationV2::Retire),
        _ => Err(DurableTopologyRegistryErrorV1::Corrupt),
    }
}

struct Writer {
    bytes: Vec<u8>,
}
impl Writer {
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
    fn len(&mut self, value: usize) -> Result<(), DurableTopologyRegistryErrorV1> {
        let value = u32::try_from(value).map_err(|_| DurableTopologyRegistryErrorV1::Capacity)?;
        self.bytes.extend_from_slice(&value.to_be_bytes());
        Ok(())
    }
    fn id(&mut self, value: &StableId) -> Result<(), DurableTopologyRegistryErrorV1> {
        self.len(value.as_str().len())?;
        self.bytes.extend_from_slice(value.as_str().as_bytes());
        Ok(())
    }
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Reader<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }
    fn remaining(&self) -> usize {
        self.bytes.len().saturating_sub(self.offset)
    }
    fn take(&mut self, count: usize) -> Result<&'a [u8], DurableTopologyRegistryErrorV1> {
        let end = self
            .offset
            .checked_add(count)
            .filter(|end| *end <= self.bytes.len())
            .ok_or(DurableTopologyRegistryErrorV1::Corrupt)?;
        let value = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(value)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], DurableTopologyRegistryErrorV1> {
        self.take(N)?
            .try_into()
            .map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)
    }
    fn u8(&mut self) -> Result<u8, DurableTopologyRegistryErrorV1> {
        Ok(self.array::<1>()?[0])
    }
    fn u32(&mut self) -> Result<u32, DurableTopologyRegistryErrorV1> {
        Ok(u32::from_be_bytes(self.array()?))
    }
    fn u64(&mut self) -> Result<u64, DurableTopologyRegistryErrorV1> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn digest(&mut self) -> Result<Digest32, DurableTopologyRegistryErrorV1> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn optional_digest(&mut self) -> Result<Option<Digest32>, DurableTopologyRegistryErrorV1> {
        match self.u8()? {
            0 => Ok(None),
            1 => Ok(Some(self.digest()?)),
            _ => Err(DurableTopologyRegistryErrorV1::Corrupt),
        }
    }
    fn bounded_len(&mut self, maximum: usize) -> Result<usize, DurableTopologyRegistryErrorV1> {
        let value = self.u32()? as usize;
        if value > maximum {
            return Err(DurableTopologyRegistryErrorV1::Corrupt);
        }
        Ok(value)
    }
    fn id(&mut self) -> Result<StableId, DurableTopologyRegistryErrorV1> {
        let length = self.bounded_len(128)?;
        let raw = std::str::from_utf8(self.take(length)?)
            .map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)?;
        StableId::new(raw.to_owned()).map_err(|_| DurableTopologyRegistryErrorV1::Corrupt)
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        ProposalWindowV2, TopologyChangeV2, TopologyOperationV2, TopologyProposalRequestV2,
        admit_governed_topology_v1, build_writer_handoff_plan_v1, propose_topology_v2,
    };
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TestFile(PathBuf);
    impl TestFile {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos();
            Self(std::env::temp_dir().join(format!(
                "hepta-topology-registry-{}-{nonce}.journal",
                std::process::id()
            )))
        }
        fn create(&self) -> File {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(&self.0)
                .expect("create")
        }
        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .expect("open")
        }
    }
    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn governed(label: &str) -> GovernedTopologyProposalV1 {
        let module_id = id(&format!("module:{label}"));
        let migration = digest(&format!("migration:{label}"));
        let rollback = digest(&format!("rollback:{label}"));
        let handoff = build_writer_handoff_plan_v1(
            module_id.clone(),
            id("owner:old"),
            id("owner:new"),
            10,
            11,
            digest(&format!("source:{label}")),
            migration,
            rollback,
            digest(&format!("ack:{label}")),
        )
        .expect("handoff");
        let artifact = digest(&format!("artifact:{label}"));
        let proposal = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id(&format!("proposal:{label}")),
            proposer_id: id("generator:topology"),
            evaluator_id: id("evaluator:topology"),
            selected_artifact_digest: artifact,
            window: ProposalWindowV2 {
                window_id: id(&format!("window:{label}")),
                window_digest: digest(&format!("window-digest:{label}")),
            },
            baseline_generation: generation(10),
            candidate_generation: generation(11),
            evaluation_digest: digest(&format!("evaluation:{label}")),
            rollback_predecessor_digest: artifact,
            changes: vec![TopologyChangeV2 {
                module_id,
                operation: TopologyOperationV2::Replace,
                predecessor_digest: Some(digest(&format!("old:{label}"))),
                candidate_digest: Some(digest(&format!("new:{label}"))),
                migration_digest: migration,
                rollback_digest: rollback,
                writer_handoff_digest: handoff.plan_digest,
                evidence_digest: digest(&format!("evidence:{label}")),
            }],
        })
        .expect("proposal");
        admit_governed_topology_v1(
            proposal,
            vec![handoff],
            digest(&format!("source-auth:{label}")),
            digest(&format!("eval-auth:{label}")),
        )
        .expect("governed")
    }

    #[test]
    fn topology_registry_reopen_and_old_idempotent_retry_preserve_original_frame() {
        let file = TestFile::new();
        let scope = digest("scope");
        let first = governed("z-first");
        let second = governed("a-second");
        let (first_receipt, second_receipt, anchor) = {
            let mut store =
                DurableTopologyProposalRegistryV1::bootstrap_empty(file.create(), scope, 21, 8)
                    .expect("bootstrap");
            let first_receipt = store
                .append(Digest32::ZERO, first.clone())
                .expect("first");
            let second_receipt = store
                .append(first_receipt.frame_digest, second.clone())
                .expect("second");
            let replay = store
                .append(second_receipt.frame_digest, first.clone())
                .expect("replay");
            assert_eq!(replay.disposition, AppendDisposition::Unchanged);
            assert_eq!(replay.sequence, first_receipt.sequence);
            assert_eq!(replay.frame_digest, first_receipt.frame_digest);
            let anchor = store.current_anchor().expect("anchor").expect("head");
            (first_receipt, second_receipt, anchor)
        };
        assert_eq!(first_receipt.sequence, 1);
        assert_eq!(second_receipt.sequence, 2);
        let reopened = DurableTopologyProposalRegistryV1::reopen_anchored(
            file.open(),
            scope,
            21,
            8,
            anchor,
        )
        .expect("reopen");
        assert_eq!(reopened.record_count(), Ok(2));
    }
}
