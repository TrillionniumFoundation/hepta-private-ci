//! Bounded byte custody for derived MemoryCell state in the existing owner.
//! Content hashes do not establish a RecallPacket codec or model execution.

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::memory_cell::MemoryCellManifestV1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveStoreError;
use crate::ProductionWriterError;

pub const MAX_MEMORY_CELL_CHECKPOINT_STATE_BYTES: usize = 1_048_576;
pub const MAX_MEMORY_CELL_CHECKPOINT_RECALL_BYTES: usize = 524_288;
pub(crate) const MAX_HEADER_BYTES: usize = 16_384;
pub(crate) const MAX_CHECKPOINTS: i64 = 1_024;
pub(crate) const MAX_STORED_BYTES: i64 = 64 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellCheckpointHeaderV1 {
    pub manifest: MemoryCellManifestV1,
    pub logical_sequence: u64,
    pub predecessor_digest: Option<ContractDigestV1>,
    /// The complete, owner-observed Lane C cut, independently retained by the caller.
    pub owner_cut_digest: ContractDigestV1,
    /// Logical packet identity; the composition layer must validate its codec.
    pub recall_packet_digest: ContractDigestV1,
    pub state_content_digest: ContractDigestV1,
    pub recall_content_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellCheckpointDraftV1 {
    pub header: MemoryCellCheckpointHeaderV1,
    pub state_bytes: Vec<u8>,
    pub recall_bytes: Vec<u8>,
}

impl MemoryCellCheckpointDraftV1 {
    pub(crate) fn encode_header(&self) -> Result<String, MemoryCellStateErrorV1> {
        self.header
            .manifest
            .validate()
            .map_err(|error| MemoryCellStateErrorV1::Invalid(error.to_string()))?;
        if self.header.logical_sequence == 0
            || self.header.logical_sequence > i64::MAX as u64
            || (self.header.logical_sequence == 1) != self.header.predecessor_digest.is_none()
            || self.state_bytes.is_empty()
            || self.state_bytes.len() > self.header.manifest.max_state_bytes as usize
            || self.state_bytes.len() > MAX_MEMORY_CELL_CHECKPOINT_STATE_BYTES
            || self.recall_bytes.is_empty()
            || self.recall_bytes.len() > MAX_MEMORY_CELL_CHECKPOINT_RECALL_BYTES
        {
            return Err(MemoryCellStateErrorV1::Invalid(
                "checkpoint sequence or byte budget".into(),
            ));
        }
        if Digest32::of_bytes(&self.state_bytes) != self.header.state_content_digest.digest()
            || Digest32::of_bytes(&self.recall_bytes) != self.header.recall_content_digest.digest()
        {
            return Err(MemoryCellStateErrorV1::Invalid(
                "checkpoint content digest".into(),
            ));
        }
        let json = serde_json::to_string(&self.header)
            .map_err(|error| MemoryCellStateErrorV1::Invalid(error.to_string()))?;
        if json.len() > MAX_HEADER_BYTES {
            return Err(MemoryCellStateErrorV1::Invalid(
                "checkpoint header budget".into(),
            ));
        }
        Ok(json)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellCheckpointReadPinsV1 {
    pub manifest: MemoryCellManifestV1,
    pub checkpoint_digest: ContractDigestV1,
    pub owner_cut_digest: ContractDigestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellCheckpointReceiptV1 {
    pub cell_id: ContractIdV1,
    pub logical_sequence: u64,
    pub checkpoint_digest: ContractDigestV1,
    pub owner_cut_digest: ContractDigestV1,
    pub source_frontier: u64,
    pub tombstone_frontier: u64,
    pub state_content_digest: ContractDigestV1,
    pub recall_content_digest: ContractDigestV1,
    pub writer_lease_digest: Sha256Digest,
    pub authority_grant_digest: Sha256Digest,
    pub replayed: bool,
}

impl MemoryCellCheckpointReceiptV1 {
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Point-in-time bytes read from the exact current owner checkpoint. The caller
/// must validate its codec and re-read after any source/forget frontier change.
#[derive(Debug)]
pub struct LoadedMemoryCellCheckpointV1 {
    pub(crate) draft: MemoryCellCheckpointDraftV1,
    pub(crate) receipt: MemoryCellCheckpointReceiptV1,
}

impl LoadedMemoryCellCheckpointV1 {
    pub fn header(&self) -> &MemoryCellCheckpointHeaderV1 {
        &self.draft.header
    }
    pub fn state_bytes(&self) -> &[u8] {
        &self.draft.state_bytes
    }
    pub fn recall_bytes(&self) -> &[u8] {
        &self.draft.recall_bytes
    }
    pub fn receipt(&self) -> &MemoryCellCheckpointReceiptV1 {
        &self.receipt
    }
}

#[derive(Debug, thiserror::Error)]
pub enum MemoryCellStateErrorV1 {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Writer(#[from] ProductionWriterError),
    #[error("invalid MemoryCell checkpoint: {0}")]
    Invalid(String),
    #[error("MemoryCell checkpoint conflict: {0}")]
    Conflict(&'static str),
    #[error("MemoryCell checkpoint is corrupt: {0}")]
    Corrupt(&'static str),
}

pub(crate) fn checkpoint_digest(header: &str) -> Result<ContractDigestV1, MemoryCellStateErrorV1> {
    ContractDigestV1::from_digest(Digest32::of_parts(&[
        b"hepta.memory-cell.persisted-checkpoint.v1\0",
        &(header.len() as u64).to_be_bytes(),
        header.as_bytes(),
    ]))
    .map_err(|error| MemoryCellStateErrorV1::Invalid(error.to_string()))
}
