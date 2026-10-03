//! Complete original row observation; decoding proves integrity, never custody.
use super::*;

const MAGIC: &[u8; 8] = b"HPTPCO01";
pub const MAX_COMPLETED_PROPOSAL_BYTES_V1: usize = MAX_FRAME_BYTES + 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompletedProposalV1 {
    pub proposal: ParameterProposalV2,
    pub receipt: DurableProposalAppendReceiptV1,
    /// The actual acknowledged head covering this row, possibly a later row.
    pub acknowledged_head: DurableRegistryAnchorV1,
}

impl DurableProposalRegistry {
    /// Read the same retained writer. No append, fence issuance or anchor update.
    /// Absence is an observation and does not prove that an earlier effect ended.
    pub fn observe_completed_v1(
        &self,
        proposal_id: &StableId,
        acknowledged_head: Option<DurableRegistryAnchorV1>,
    ) -> Result<Option<DurableCompletedProposalV1>, DurableProposalRegistryError> {
        if self.current_anchor()? != acknowledged_head {
            return Err(DurableProposalRegistryError::AnchorMismatch);
        }
        let Some(proposal) = self.get_v2_by_proposal_id(proposal_id)? else {
            return Ok(None);
        };
        let receipt = self
            .receipts
            .get(proposal_id)
            .ok_or(DurableProposalRegistryError::Corrupt)?;
        let observation = DurableCompletedProposalV1 {
            proposal: proposal.clone(),
            receipt: receipt.clone(),
            acknowledged_head: acknowledged_head.ok_or(DurableProposalRegistryError::Corrupt)?,
        };
        observation.to_bytes()?;
        Ok(Some(observation))
    }
}

impl DurableCompletedProposalV1 {
    /// Bounded encoding using the original full proposal frame codec.
    pub fn to_bytes(&self) -> Result<Vec<u8>, DurableProposalRegistryError> {
        let corrupt = DurableProposalRegistryError::Corrupt;
        let (frame, digest) = encode_frame(
            self.receipt.sequence,
            self.receipt.predecessor_frame_digest,
            &self.proposal,
        )?;
        if self.receipt.sequence == 0
            || self.receipt.writer_fence == 0
            || self.receipt.registry_scope_digest.is_zero()
            || self.receipt.sequence > self.acknowledged_head.sequence
            || self.acknowledged_head.frame_digest.is_zero()
            || digest != self.receipt.frame_digest
            || self.receipt.proposal_id != self.proposal.proposal_id
            || self.receipt.proposal_digest != self.proposal.proposal_digest
            || self.receipt.selected_artifact_digest != self.proposal.selected_artifact_digest
            || self.receipt.window_id != self.proposal.window.window_id
            || self.receipt.authority != AuthorityPosture::DENY_ALL
            || self.receipt.disposition != AppendDisposition::Inserted
            || (self.receipt.sequence == 1 && !self.receipt.predecessor_frame_digest.is_zero())
            || (self.receipt.sequence > 1 && self.receipt.predecessor_frame_digest.is_zero())
            || (self.receipt.sequence == self.acknowledged_head.sequence
                && digest != self.acknowledged_head.frame_digest)
        {
            return Err(corrupt);
        }
        let mut bytes = Vec::with_capacity(frame.len() + 128);
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(self.receipt.registry_scope_digest.as_array());
        bytes.extend_from_slice(&self.receipt.writer_fence.to_be_bytes());
        bytes.extend_from_slice(&self.acknowledged_head.sequence.to_be_bytes());
        bytes.extend_from_slice(self.acknowledged_head.frame_digest.as_array());
        bytes.extend_from_slice(&(frame.len() as u32).to_be_bytes());
        bytes.extend_from_slice(&frame);
        bytes.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
        Ok(bytes)
    }

    /// Untrusted bytes cannot establish that the head was actually acknowledged.
    /// A consumer must authenticate the original owner and independent anchor.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, DurableProposalRegistryError> {
        if bytes.len() < 124
            || bytes.len() > MAX_COMPLETED_PROPOSAL_BYTES_V1
            || &bytes[..8] != MAGIC
            || Digest32::of_bytes(&bytes[..bytes.len() - 32]).as_array()
                != &bytes[bytes.len() - 32..]
        {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        let mut reader = ByteReader::new(&bytes[8..bytes.len() - 32]);
        let registry_scope_digest = reader.digest()?;
        let writer_fence = reader.u64()?;
        let acknowledged_head = DurableRegistryAnchorV1 {
            sequence: reader.u64()?,
            frame_digest: reader.digest()?,
        };
        let length = reader.u32()? as usize;
        if reader.remaining() != length {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        let decoded = decode_frame(reader.take(length)?)?;
        let proposal = decoded.proposal;
        let receipt = DurableProposalAppendReceiptV1 {
            registry_scope_digest,
            writer_fence,
            sequence: decoded.sequence,
            proposal_id: proposal.proposal_id.clone(),
            proposal_digest: proposal.proposal_digest,
            selected_artifact_digest: proposal.selected_artifact_digest,
            window_id: proposal.window.window_id.clone(),
            predecessor_frame_digest: decoded.predecessor_frame_digest,
            frame_digest: decoded.frame_digest,
            disposition: AppendDisposition::Inserted,
            authority: AuthorityPosture::DENY_ALL,
        };
        let result = Self {
            proposal,
            receipt,
            acknowledged_head,
        };
        if result.to_bytes()? != bytes {
            return Err(DurableProposalRegistryError::Corrupt);
        }
        Ok(result)
    }
}
