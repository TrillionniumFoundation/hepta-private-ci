use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeNodeV2;
use crate::MAX_KNOWLEDGE_EDGES_V2;
use crate::MAX_KNOWLEDGE_NODES_V2;

use super::canonical::is_canonical_edge;
use super::canonical::is_canonical_node;
use super::canonical::strictly_sorted_edges;
use super::canonical::strictly_sorted_nodes;
use super::canonical::strictly_sorted_unique;
use super::digest::compute_preparation_digest;
use super::digest::compute_receipt_digest;
use super::digest::usize_to_u64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeProjectionDeltaV3 {
    pub expected_predecessor_generation: Generation,
    pub expected_predecessor_state_root: Digest32,
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub remove_node_ids: Vec<codex_hepta_types::StableId>,
    pub upsert_nodes: Vec<KnowledgeNodeV2>,
    pub remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    pub upsert_edges: Vec<KnowledgeEdgeV2>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct KnowledgeLocalMutationWorkV3 {
    pub predecessor_nodes_read: u64,
    pub predecessor_edges_read: u64,
    pub supports_inspected: u64,
    pub treap_leaf_updates: u64,
    pub treap_nodes_rehashed: u64,
    /// Always zero for local preparation. Complete scans belong to V2 audit.
    pub full_entries_scanned: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeLocalStorageDeltaV3 {
    pub expected_predecessor_generation: Generation,
    pub expected_predecessor_state_root: Digest32,
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    /// Storage owners apply edge removals before node removals.
    pub remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    pub remove_node_ids: Vec<codex_hepta_types::StableId>,
    /// Storage owners apply node upserts before edge upserts.
    pub upsert_nodes: Vec<KnowledgeNodeV2>,
    pub upsert_edges: Vec<KnowledgeEdgeV2>,
    pub resulting_state_root: Digest32,
    pub resulting_node_count: u64,
    pub resulting_edge_count: u64,
    pub full_rebuild_audit_due: bool,
    pub work: KnowledgeLocalMutationWorkV3,
    pub preparation_digest: Digest32,
}

impl KnowledgeLocalStorageDeltaV3 {
    pub fn validate(&self) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
        ensure_nonzero("local_predecessor_root", self.expected_predecessor_state_root)?;
        ensure_nonzero("local_resulting_root", self.resulting_state_root)?;
        ensure_nonzero("local_source_snapshot", self.source_snapshot_digest)?;
        ensure_nonzero("local_generation_vector", self.generation_vector_digest)?;
        ensure_nonzero("local_graph_profile", self.graph_profile_digest)?;
        if self.expected_predecessor_generation.next().ok() != Some(self.generation) {
            return Err(KnowledgeLocalIncrementalErrorV3::InvalidPredecessor);
        }
        if !strictly_sorted_unique(&self.remove_node_ids)
            || !strictly_sorted_unique(&self.remove_edge_identities)
            || !strictly_sorted_nodes(&self.upsert_nodes)
            || !strictly_sorted_edges(&self.upsert_edges)
            || self.work.full_entries_scanned != 0
            || self.resulting_node_count > usize_to_u64(MAX_KNOWLEDGE_NODES_V2)
            || self.resulting_edge_count > usize_to_u64(MAX_KNOWLEDGE_EDGES_V2)
        {
            return Err(KnowledgeLocalIncrementalErrorV3::NonCanonicalPreparedDelta);
        }
        if self.upsert_nodes.iter().any(|node| !is_canonical_node(node))
            || self.upsert_edges.iter().any(|edge| !is_canonical_edge(edge))
        {
            return Err(KnowledgeLocalIncrementalErrorV3::NonCanonicalPreparedDelta);
        }
        if self.preparation_digest != compute_preparation_digest(self) {
            return Err(KnowledgeLocalIncrementalErrorV3::PreparationDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeLocalMutationReceiptV3 {
    pub predecessor_generation: Generation,
    pub predecessor_state_root: Digest32,
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub state_root: Digest32,
    pub node_count: u64,
    pub edge_count: u64,
    pub full_rebuild_audit_due: bool,
    pub preparation_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl KnowledgeLocalMutationReceiptV3 {
    pub fn validate(&self) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
        ensure_nonzero("local_receipt_predecessor_root", self.predecessor_state_root)?;
        ensure_nonzero("local_receipt_state_root", self.state_root)?;
        ensure_nonzero("local_receipt_source_snapshot", self.source_snapshot_digest)?;
        ensure_nonzero("local_receipt_generation_vector", self.generation_vector_digest)?;
        ensure_nonzero("local_receipt_graph_profile", self.graph_profile_digest)?;
        ensure_nonzero("local_receipt_preparation", self.preparation_digest)?;
        if self.predecessor_generation.next().ok() != Some(self.generation) {
            return Err(KnowledgeLocalIncrementalErrorV3::InvalidPredecessor);
        }
        if self.receipt_digest != compute_receipt_digest(self) {
            return Err(KnowledgeLocalIncrementalErrorV3::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgeLocalIncrementalErrorV3 {
    Generation(KnowledgeGenerationErrorV2),
    InvalidPredecessor,
    ProfileChanged,
    StalePreparedMutation,
    DuplicateDeltaIdentity,
    NonCanonicalPreparedDelta,
    CommitmentKeyCollision,
    CommitmentDepthExceeded,
    ResultingStateRootMismatch {
        expected: Digest32,
        observed: Digest32,
    },
    ResultingCountMismatch,
    PreparationDigestMismatch,
    ReceiptDigestMismatch,
    InvalidAuditInterval,
    AuditRootMismatch {
        expected: Digest32,
        observed: Digest32,
    },
}

impl From<KnowledgeGenerationErrorV2> for KnowledgeLocalIncrementalErrorV3 {
    fn from(error: KnowledgeGenerationErrorV2) -> Self {
        Self::Generation(error)
    }
}

impl fmt::Display for KnowledgeLocalIncrementalErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for KnowledgeLocalIncrementalErrorV3 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Generation(error) => Some(error),
            Self::InvalidPredecessor
            | Self::ProfileChanged
            | Self::StalePreparedMutation
            | Self::DuplicateDeltaIdentity
            | Self::NonCanonicalPreparedDelta
            | Self::CommitmentKeyCollision
            | Self::CommitmentDepthExceeded
            | Self::ResultingStateRootMismatch { .. }
            | Self::ResultingCountMismatch
            | Self::PreparationDigestMismatch
            | Self::ReceiptDigestMismatch
            | Self::InvalidAuditInterval
            | Self::AuditRootMismatch { .. } => None,
        }
    }
}

pub(super) fn ensure_nonzero(
    label: &'static str,
    digest: Digest32,
) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
    if digest.is_zero() {
        Err(KnowledgeGenerationErrorV2::EmptyDigest(label).into())
    } else {
        Ok(())
    }
}
