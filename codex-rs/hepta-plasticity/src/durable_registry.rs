//! Host-authorized append-only durable storage for parameter proposal V2 records.
//!
//! The file is generation/fence scoped, checksum chained, bounded and locked for
//! the lifetime of the handle. Persistence proves only byte durability and local
//! conflict semantics; it grants no independent acceptance, selection, runtime
//! mutation, promotion or release authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
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

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CandidateNormMetricsV2;
use crate::Error;
use crate::LayerNormDenominatorV2;
use crate::LayerRelativeNormV2;
use crate::ParameterCandidateKindV2;
use crate::ParameterCandidateV2;
use crate::ParameterDeltaV2;
use crate::ParameterNormProfileV2;
use crate::ParameterProposalV2;
use crate::ProposalRegistry;
use crate::ProposalStatus;
use crate::ProposalWindowV2;
use crate::types::MAX_CANDIDATES;
use crate::types::MAX_NORM_LAYERS;
use crate::types::MAX_PARAMETER_DELTAS;
use crate::types::MAX_PROPOSALS;
use crate::verify_parameter_proposal_v2;

const MAGIC: &[u8; 8] = b"HPTPRJ02";
const FORMAT_VERSION: u16 = 2;
const HEADER_SIZE: usize = 8 + 2 + 8 + 4 + 32 + 32;
const MAX_PAYLOAD_BYTES: usize = 4 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 8 + 32 + 4 + MAX_PAYLOAD_BYTES + 32;
const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;
const PAYLOAD_MAGIC: &[u8; 8] = b"HPTPPV02";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DurableRegistryAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableProposalAppendReceiptV1 {
    pub registry_scope_digest: Digest32,
    pub writer_fence: u64,
    pub sequence: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window_id: StableId,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub disposition: AppendDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DurableProposalRegistryError {
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

impl fmt::Display for DurableProposalRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for DurableProposalRegistryError {}
impl From<io::Error> for DurableProposalRegistryError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<Error> for DurableProposalRegistryError {
    fn from(value: Error) -> Self {
        Self::Proposal(value)
    }
}

#[derive(Clone, Copy)]
enum RecoveryPolicy {
    Unanchored,
    Require(DurableRegistryAnchorV1),
}

struct LockedFile(File);

impl LockedFile {
    fn acquire(file: File) -> Result<Self, DurableProposalRegistryError> {
        if !file.metadata()?.is_file() {
            return Err(DurableProposalRegistryError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(DurableProposalRegistryError::Busy),
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

/// A bounded, append-only V2 proposal registry over one host-owned file.
///
/// The host owns path enrollment, directory durability, permissions, backup,
/// revocation, deletion and fence issuance. `open_anchored` must be used after
/// the host has externally acknowledged a frame; the file alone cannot detect
/// replacement by an older valid prefix.
pub struct DurableProposalRegistry {
    file: LockedFile,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    maximum_records: usize,
    registry: ProposalRegistry,
    frame_digests: Vec<Digest32>,
    receipts: BTreeMap<StableId, DurableProposalAppendReceiptV1>,
    poisoned: bool,
}

impl DurableProposalRegistry {
    pub fn open(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableProposalRegistryError> {
        Self::open_with_policy(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            RecoveryPolicy::Unanchored,
        )
    }

    pub fn open_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableRegistryAnchorV1,
    ) -> Result<Self, DurableProposalRegistryError> {
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
    ) -> Result<Self, DurableProposalRegistryError> {
        if !(1..=MAX_PROPOSALS).contains(&maximum_records) {
            return Err(DurableProposalRegistryError::InvalidLimit);
        }
        if registry_scope_digest.is_zero() {
            return Err(DurableProposalRegistryError::InvalidScope);
        }
        if writer_fence == 0 {
            return Err(DurableProposalRegistryError::InvalidWriterFence);
        }
        if let RecoveryPolicy::Require(anchor) = policy
            && (anchor.sequence == 0
                || anchor.sequence > maximum_records as u64
                || anchor.frame_digest.is_zero())
        {
            return Err(DurableProposalRegistryError::InvalidAnchor);
        }

        let expected_header = encode_header(registry_scope_digest, writer_fence, maximum_records)?;
        let mut file = LockedFile::acquire(file)?;
        let file_len = file.metadata()?.len();
        if file_len > MAX_FILE_BYTES {
            return Err(DurableProposalRegistryError::Capacity);
        }
        file.seek(SeekFrom::Start(0))?;
        if file_len == 0 {
            if matches!(policy, RecoveryPolicy::Require(_)) {
                return Err(DurableProposalRegistryError::AcknowledgedHistoryMissing);
            }
            file.write_all(&expected_header)
                .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        } else {
            if file_len < HEADER_SIZE as u64 {
                return Err(DurableProposalRegistryError::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.read_exact(&mut actual)?;
            validate_header(&actual)?;
            if actual != expected_header {
                return Err(DurableProposalRegistryError::ContextMismatch);
            }
        }

        let mut store = Self {
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            registry: ProposalRegistry::new(maximum_records),
            frame_digests: Vec::new(),
            receipts: BTreeMap::new(),
            poisoned: false,
        };
        let mut offset = HEADER_SIZE as u64;
        let physical_len = store.file.metadata()?.len();
        while offset < physical_len {
            if store.frame_digests.len() >= maximum_records {
                return Err(DurableProposalRegistryError::Capacity);
            }
            let remaining = physical_len - offset;
            if remaining < 4 {
                truncate_incomplete_tail(&mut store.file, offset)?;
                break;
            }
            store.file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            store.file.read_exact(&mut length_bytes)?;
            let frame_len = usize::try_from(u32::from_be_bytes(length_bytes))
                .map_err(|_| DurableProposalRegistryError::Corrupt)?;
            if !(8 + 32 + 4 + 32..=MAX_FRAME_BYTES).contains(&frame_len) {
                return Err(DurableProposalRegistryError::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_len as u64)
                .ok_or(DurableProposalRegistryError::Capacity)?;
            if remaining < total {
                truncate_incomplete_tail(&mut store.file, offset)?;
                break;
            }
            let mut frame = vec![0_u8; frame_len];
            store.file.read_exact(&mut frame)?;
            let decoded = decode_frame(&frame)?;
            let expected_sequence = store.frame_digests.len() as u64 + 1;
            if decoded.sequence != expected_sequence
                || decoded.predecessor_frame_digest
                    != store
                        .frame_digests
                        .last()
                        .copied()
                        .unwrap_or(Digest32::ZERO)
            {
                return Err(DurableProposalRegistryError::Corrupt);
            }
            let disposition = store.registry.append_v2(decoded.proposal.clone())?;
            if disposition != AppendDisposition::Inserted {
                return Err(DurableProposalRegistryError::Corrupt);
            }
            let receipt = DurableProposalAppendReceiptV1 {
                registry_scope_digest,
                writer_fence,
                sequence: decoded.sequence,
                proposal_id: decoded.proposal.proposal_id.clone(),
                proposal_digest: decoded.proposal.proposal_digest,
                selected_artifact_digest: decoded.proposal.selected_artifact_digest,
                window_id: decoded.proposal.window.window_id.clone(),
                predecessor_frame_digest: decoded.predecessor_frame_digest,
                frame_digest: decoded.frame_digest,
                disposition: AppendDisposition::Inserted,
                authority: AuthorityPosture::DENY_ALL,
            };
            if store
                .receipts
                .insert(receipt.proposal_id.clone(), receipt)
                .is_some()
            {
                return Err(DurableProposalRegistryError::Corrupt);
            }
            store.frame_digests.push(decoded.frame_digest);
            offset = offset
                .checked_add(total)
                .ok_or(DurableProposalRegistryError::Capacity)?;
        }

        if let RecoveryPolicy::Require(anchor) = policy {
            let Some(recovered) = anchor
                .sequence
                .checked_sub(1)
                .and_then(|index| usize::try_from(index).ok())
                .and_then(|index| store.frame_digests.get(index))
            else {
                return Err(DurableProposalRegistryError::AcknowledgedHistoryMissing);
            };
            if *recovered != anchor.frame_digest {
                return Err(DurableProposalRegistryError::AnchorMismatch);
            }
        }
        store
            .file
            .sync_data()
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        Ok(store)
    }

    /// Append one verified proposal after the exact durable predecessor.
    ///
    /// An identical retry returns the original frame as an unchanged observation,
    /// even when later records exist. Any semantic drift in an occupied slot or
    /// proposal identity fails closed. A write/sync failure poisons this handle;
    /// reopen and reconcile against an external anchor before retrying.
    pub fn append_v2(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
        if self.poisoned {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        verify_parameter_proposal_v2(&proposal)?;
        if let Some(existing) = self.receipts.get(&proposal.proposal_id) {
            let stored = self
                .registry
                .get_v2_by_proposal_id(&proposal.proposal_id)
                .ok_or(DurableProposalRegistryError::Corrupt)?;
            if stored == &proposal {
                let mut observed = existing.clone();
                observed.disposition = AppendDisposition::Unchanged;
                return Ok(observed);
            }
        }
        let current = self.frame_digests.last().copied().unwrap_or(Digest32::ZERO);
        if current != expected_predecessor_frame_digest {
            return Err(DurableProposalRegistryError::Conflict);
        }
        if self.frame_digests.len() >= self.maximum_records {
            return Err(DurableProposalRegistryError::Capacity);
        }

        let mut candidate_registry = self.registry.clone();
        let disposition = candidate_registry.append_v2(proposal.clone())?;
        if disposition != AppendDisposition::Inserted {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        let sequence = self.frame_digests.len() as u64 + 1;
        let (frame, frame_digest) =
            encode_frame(sequence, expected_predecessor_frame_digest, &proposal)?;
        let frame_total = 4_u64
            .checked_add(frame.len() as u64)
            .ok_or(DurableProposalRegistryError::Capacity)?;
        let expected_offset = self.file.metadata()?.len();
        if expected_offset < HEADER_SIZE as u64
            || expected_offset
                .checked_add(frame_total)
                .is_none_or(|length| length > MAX_FILE_BYTES)
        {
            return Err(DurableProposalRegistryError::Capacity);
        }

        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&(frame.len() as u32).to_be_bytes())
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        self.file
            .write_all(&frame)
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| DurableProposalRegistryError::Indeterminate)?;

        let receipt = DurableProposalAppendReceiptV1 {
            registry_scope_digest: self.registry_scope_digest,
            writer_fence: self.writer_fence,
            sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_artifact_digest: proposal.selected_artifact_digest,
            window_id: proposal.window.window_id.clone(),
            predecessor_frame_digest: expected_predecessor_frame_digest,
            frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        self.registry = candidate_registry;
        self.frame_digests.push(frame_digest);
        self.receipts.insert(proposal.proposal_id, receipt.clone());
        self.poisoned = false;
        Ok(receipt)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, DurableProposalRegistryError> {
        if self.poisoned {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        Ok(self
            .frame_digests
            .last()
            .copied()
            .map(|frame_digest| DurableRegistryAnchorV1 {
                sequence: self.frame_digests.len() as u64,
                frame_digest,
            }))
    }

    pub fn get_v2_by_proposal_id(
        &self,
        proposal_id: &StableId,
    ) -> Result<Option<&ParameterProposalV2>, DurableProposalRegistryError> {
        if self.poisoned {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        Ok(self.registry.get_v2_by_proposal_id(proposal_id))
    }

    pub fn record_count(&self) -> Result<usize, DurableProposalRegistryError> {
        if self.poisoned {
            return Err(DurableProposalRegistryError::Poisoned);
        }
        Ok(self.registry.record_count())
    }
}

fn encode_header(
    scope: Digest32,
    writer_fence: u64,
    maximum_records: usize,
) -> Result<Vec<u8>, DurableProposalRegistryError> {
    let maximum_records =
        u32::try_from(maximum_records).map_err(|_| DurableProposalRegistryError::InvalidLimit)?;
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

fn validate_header(bytes: &[u8]) -> Result<(), DurableProposalRegistryError> {
    if bytes.len() != HEADER_SIZE
        || &bytes[..8] != MAGIC
        || u16::from_be_bytes([bytes[8], bytes[9]]) != FORMAT_VERSION
        || Digest32::of_bytes(&bytes[..HEADER_SIZE - 32]).as_array() != &bytes[HEADER_SIZE - 32..]
    {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    Ok(())
}

fn truncate_incomplete_tail(
    file: &mut LockedFile,
    offset: u64,
) -> Result<(), DurableProposalRegistryError> {
    file.set_len(offset)
        .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| DurableProposalRegistryError::Indeterminate)?;
    Ok(())
}

struct DecodedFrame {
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: ParameterProposalV2,
    frame_digest: Digest32,
}

fn encode_frame(
    sequence: u64,
    predecessor_frame_digest: Digest32,
    proposal: &ParameterProposalV2,
) -> Result<(Vec<u8>, Digest32), DurableProposalRegistryError> {
    let payload = encode_proposal(proposal)?;
    if payload.len() > MAX_PAYLOAD_BYTES {
        return Err(DurableProposalRegistryError::Capacity);
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

fn decode_frame(frame: &[u8]) -> Result<DecodedFrame, DurableProposalRegistryError> {
    if frame.len() < 8 + 32 + 4 + 32 || frame.len() > MAX_FRAME_BYTES {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    let digest_offset = frame.len() - 32;
    let expected = Digest32::of_bytes(&frame[..digest_offset]);
    if expected.as_array() != &frame[digest_offset..] {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    let mut cursor = ByteReader::new(&frame[..digest_offset]);
    let sequence = cursor.u64()?;
    let predecessor_frame_digest = cursor.digest()?;
    let payload_len = cursor.u32()? as usize;
    if payload_len > MAX_PAYLOAD_BYTES || cursor.remaining() != payload_len {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    let payload = cursor.take(payload_len)?;
    let proposal = decode_proposal(payload)?;
    Ok(DecodedFrame {
        sequence,
        predecessor_frame_digest,
        proposal,
        frame_digest: expected,
    })
}

fn encode_proposal(
    proposal: &ParameterProposalV2,
) -> Result<Vec<u8>, DurableProposalRegistryError> {
    verify_parameter_proposal_v2(proposal)?;
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
    for digest in [
        proposal.dataset_digest,
        proposal.update_rule_digest,
        proposal.modulator_digest,
        proposal.modulator_broadcast_digest,
        proposal.eligibility_digest,
        proposal.evaluation_digest,
        proposal.rollback_predecessor_digest,
    ] {
        writer.digest(digest);
    }
    writer.digest(proposal.norm_profile.profile_digest);
    writer.u32(proposal.norm_profile.per_layer_max_relative_ppm);
    writer.u32(proposal.norm_profile.global_max_relative_ppm);
    writer.len(proposal.norm_profile.layers.len())?;
    for layer in &proposal.norm_profile.layers {
        writer.id(&layer.layer_id)?;
        writer.u128(layer.baseline_squared_l2_raw_q64);
    }
    writer.u128(proposal.norm_profile.global_baseline_squared_l2_raw_q64);
    writer.len(proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        writer.id(&candidate.candidate_id)?;
        writer.u8(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
        writer.len(candidate.parameter_deltas.len())?;
        for delta in &candidate.parameter_deltas {
            writer.id(&delta.layer_id)?;
            writer.id(&delta.parameter_id)?;
            writer.i64(delta.delta.raw());
            writer.i64(delta.lower_bound.raw());
            writer.i64(delta.upper_bound.raw());
            writer.digest(delta.evidence_digest);
        }
        writer.len(candidate.norm_metrics.layers.len())?;
        for layer in &candidate.norm_metrics.layers {
            writer.id(&layer.layer_id)?;
            writer.u128(layer.delta_squared_l2_raw_q64);
            writer.u128(layer.baseline_squared_l2_raw_q64);
        }
        writer.u128(candidate.norm_metrics.global_delta_squared_l2_raw_q64);
        writer.u128(candidate.norm_metrics.global_baseline_squared_l2_raw_q64);
    }
    writer.digest(proposal.proposal_digest);
    writer.u8(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    writer.u8(u8::from(proposal.authority.grants_any()));
    let bytes = writer.finish();
    if bytes.len() > MAX_PAYLOAD_BYTES {
        return Err(DurableProposalRegistryError::Capacity);
    }
    Ok(bytes)
}

fn decode_proposal(bytes: &[u8]) -> Result<ParameterProposalV2, DurableProposalRegistryError> {
    let mut reader = ByteReader::new(bytes);
    if reader.take(PAYLOAD_MAGIC.len())? != PAYLOAD_MAGIC {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    let proposal_id = reader.id()?;
    let proposer_id = reader.id()?;
    let evaluator_id = reader.id()?;
    let selected_artifact_digest = reader.digest()?;
    let window = ProposalWindowV2 {
        window_id: reader.id()?,
        window_digest: reader.digest()?,
    };
    let baseline_generation =
        Generation::new(reader.u64()?).map_err(|_| DurableProposalRegistryError::Corrupt)?;
    let candidate_generation =
        Generation::new(reader.u64()?).map_err(|_| DurableProposalRegistryError::Corrupt)?;
    let dataset_digest = reader.digest()?;
    let update_rule_digest = reader.digest()?;
    let modulator_digest = reader.digest()?;
    let modulator_broadcast_digest = reader.digest()?;
    let eligibility_digest = reader.digest()?;
    let evaluation_digest = reader.digest()?;
    let rollback_predecessor_digest = reader.digest()?;
    let profile_digest = reader.digest()?;
    let per_layer_max_relative_ppm = reader.u32()?;
    let global_max_relative_ppm = reader.u32()?;
    let layer_count = reader.bounded_len(MAX_NORM_LAYERS)?;
    let mut norm_layers = Vec::with_capacity(layer_count);
    for _ in 0..layer_count {
        norm_layers.push(LayerNormDenominatorV2 {
            layer_id: reader.id()?,
            baseline_squared_l2_raw_q64: reader.u128()?,
        });
    }
    let norm_profile = ParameterNormProfileV2 {
        profile_digest,
        per_layer_max_relative_ppm,
        global_max_relative_ppm,
        layers: norm_layers,
        global_baseline_squared_l2_raw_q64: reader.u128()?,
    };
    let candidate_count = reader.bounded_len(MAX_CANDIDATES)?;
    let mut candidates = Vec::with_capacity(candidate_count);
    let mut total_deltas = 0_usize;
    for _ in 0..candidate_count {
        let candidate_id = reader.id()?;
        let kind = match reader.u8()? {
            0 => ParameterCandidateKindV2::NoChange,
            1 => ParameterCandidateKindV2::Update,
            _ => return Err(DurableProposalRegistryError::Corrupt),
        };
        let delta_count = reader.bounded_len(MAX_PARAMETER_DELTAS)?;
        total_deltas = total_deltas
            .checked_add(delta_count)
            .filter(|count| *count <= MAX_PARAMETER_DELTAS)
            .ok_or(DurableProposalRegistryError::Corrupt)?;
        let mut deltas = Vec::with_capacity(delta_count);
        for _ in 0..delta_count {
            deltas.push(ParameterDeltaV2 {
                layer_id: reader.id()?,
                parameter_id: reader.id()?,
                delta: FixedQ32::from_raw(reader.i64()?),
                lower_bound: FixedQ32::from_raw(reader.i64()?),
                upper_bound: FixedQ32::from_raw(reader.i64()?),
                evidence_digest: reader.digest()?,
            });
        }
        let metric_count = reader.bounded_len(MAX_NORM_LAYERS)?;
        let mut metrics = Vec::with_capacity(metric_count);
        for _ in 0..metric_count {
            metrics.push(LayerRelativeNormV2 {
                layer_id: reader.id()?,
                delta_squared_l2_raw_q64: reader.u128()?,
                baseline_squared_l2_raw_q64: reader.u128()?,
            });
        }
        candidates.push(ParameterCandidateV2 {
            candidate_id,
            kind,
            parameter_deltas: deltas,
            norm_metrics: CandidateNormMetricsV2 {
                layers: metrics,
                global_delta_squared_l2_raw_q64: reader.u128()?,
                global_baseline_squared_l2_raw_q64: reader.u128()?,
            },
        });
    }
    let proposal_digest = reader.digest()?;
    let status = match reader.u8()? {
        0 => ProposalStatus::RequiresIndependentAcceptance,
        _ => return Err(DurableProposalRegistryError::Corrupt),
    };
    if reader.u8()? != 0 || reader.remaining() != 0 {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    let proposal = ParameterProposalV2 {
        proposal_id,
        proposer_id,
        evaluator_id,
        selected_artifact_digest,
        window,
        baseline_generation,
        candidate_generation,
        dataset_digest,
        update_rule_digest,
        modulator_digest,
        modulator_broadcast_digest,
        eligibility_digest,
        evaluation_digest,
        rollback_predecessor_digest,
        norm_profile,
        candidates,
        proposal_digest,
        status,
        authority: AuthorityPosture::DENY_ALL,
    };
    verify_parameter_proposal_v2(&proposal)?;
    Ok(proposal)
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
    fn u32(&mut self, value: u32) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
    fn u64(&mut self, value: u64) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
    fn u128(&mut self, value: u128) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
    fn i64(&mut self, value: i64) {
        self.bytes.extend_from_slice(&value.to_be_bytes());
    }
    fn digest(&mut self, value: Digest32) {
        self.bytes.extend_from_slice(value.as_array());
    }
    fn len(&mut self, value: usize) -> Result<(), DurableProposalRegistryError> {
        self.u32(u32::try_from(value).map_err(|_| DurableProposalRegistryError::Capacity)?);
        Ok(())
    }
    fn id(&mut self, value: &StableId) -> Result<(), DurableProposalRegistryError> {
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
    fn take(&mut self, count: usize) -> Result<&'a [u8], DurableProposalRegistryError> {
        let end = self
            .offset
            .checked_add(count)
            .filter(|end| *end <= self.bytes.len())
            .ok_or(DurableProposalRegistryError::Corrupt)?;
        let value = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(value)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], DurableProposalRegistryError> {
        self.take(N)?
            .try_into()
            .map_err(|_| DurableProposalRegistryError::Corrupt)
    }
    fn u8(&mut self) -> Result<u8, DurableProposalRegistryError> {
        Ok(self.array::<1>()?[0])
    }
    fn u32(&mut self) -> Result<u32, DurableProposalRegistryError> {
        Ok(u32::from_be_bytes(self.array()?))
    }
    fn u64(&mut self) -> Result<u64, DurableProposalRegistryError> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn u128(&mut self) -> Result<u128, DurableProposalRegistryError> {
        Ok(u128::from_be_bytes(self.array()?))
    }
    fn i64(&mut self) -> Result<i64, DurableProposalRegistryError> {
        Ok(i64::from_be_bytes(self.array()?))
    }
    fn digest(&mut self) -> Result<Digest32, DurableProposalRegistryError> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn bounded_len(&mut self, maximum: usize) -> Result<usize, DurableProposalRegistryError> {
        let value =
            usize::try_from(self.u32()?).map_err(|_| DurableProposalRegistryError::Corrupt)?;
        if value > maximum {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        Ok(value)
    }
    fn id(&mut self) -> Result<StableId, DurableProposalRegistryError> {
        let length = self.bounded_len(128)?;
        let raw = std::str::from_utf8(self.take(length)?)
            .map_err(|_| DurableProposalRegistryError::Corrupt)?;
        StableId::new(raw.to_string()).map_err(|_| DurableProposalRegistryError::Corrupt)
    }
}

#[cfg(test)]
#[path = "durable_registry_tests.rs"]
mod tests;

