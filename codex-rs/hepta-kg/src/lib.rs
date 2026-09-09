//! Rebuildable knowledge-graph projection.

#![forbid(unsafe_code)]

mod generation;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub use generation::KnowledgeEdgeIdentityV2;
pub use generation::KnowledgeEdgeV2;
pub use generation::KnowledgeGenerationErrorV2;
pub use generation::KnowledgeGenerationV2;
pub use generation::KnowledgeNodeV2;
pub use generation::KnowledgeProjectionDeltaV2;
pub use generation::KnowledgeProjectionInputV2;
pub use generation::KnowledgePublicationDispositionV2;
pub use generation::KnowledgePublicationReceiptV2;
pub use generation::KnowledgeRelationKindV2;
pub use generation::KnowledgeRelationQueryV2;
pub use generation::KnowledgeRelationResultV2;
pub use generation::KnowledgeSupportV2;
pub use generation::MAX_KNOWLEDGE_EDGES_V2;
pub use generation::MAX_KNOWLEDGE_NODES_V2;
pub use generation::MAX_SUPPORTS_PER_RELATION_V2;
pub use generation::apply_incremental_delta;
pub use generation::build_complete_generation;
pub use generation::publish_generation;
pub use generation::query_relations;

const MAX_EDGES: usize = 65_536;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct KnowledgeEdge {
    pub source_id: StableId,
    pub relation_id: StableId,
    pub target_id: StableId,
    pub source_fact_digest: Digest32,
    pub live: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeProjection {
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub edges: Vec<KnowledgeEdge>,
    pub projection_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptySourceSnapshot,
    EdgeLimitExceeded,
    EmptyFactDigest(String),
    DuplicateEdge(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn rebuild(
    generation: Generation,
    source_snapshot_digest: Digest32,
    mut edges: Vec<KnowledgeEdge>,
) -> Result<KnowledgeProjection, Error> {
    if source_snapshot_digest.is_zero() {
        return Err(Error::EmptySourceSnapshot);
    }
    if edges.len() > MAX_EDGES {
        return Err(Error::EdgeLimitExceeded);
    }
    edges.sort();
    let mut seen = BTreeSet::new();
    for edge in &edges {
        if edge.source_fact_digest.is_zero() {
            return Err(Error::EmptyFactDigest(edge.source_id.to_string()));
        }
        let identity = (
            edge.source_id.clone(),
            edge.relation_id.clone(),
            edge.target_id.clone(),
        );
        if !seen.insert(identity) {
            return Err(Error::DuplicateEdge(edge.source_id.to_string()));
        }
    }
    edges.retain(|edge| edge.live);

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.knowledge.projection.v1");
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(source_snapshot_digest.as_array());
    for edge in &edges {
        push_id(&mut bytes, &edge.source_id);
        push_id(&mut bytes, &edge.relation_id);
        push_id(&mut bytes, &edge.target_id);
        bytes.extend_from_slice(edge.source_fact_digest.as_array());
    }
    Ok(KnowledgeProjection {
        generation,
        source_snapshot_digest,
        edges,
        projection_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
