//! Complete-generation knowledge projection with support lineage.
//!
//! Knowledge graph state is rebuildable and never source truth. A selectable
//! generation must be complete for one source cut, bind the Lane C generation
//! vector, retain every non-revoked support, drop unsupported relations and be
//! published against an exact predecessor. Full and incremental builders share
//! the same canonicalization function so their semantic digests are comparable.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_KNOWLEDGE_NODES_V2: usize = 65_536;
pub const MAX_KNOWLEDGE_EDGES_V2: usize = 262_144;
pub const MAX_SUPPORTS_PER_RELATION_V2: usize = 64;
const GENERATION_DOMAIN: &[u8] = b"hepta.knowledge-generation.v2";
const PUBLICATION_DOMAIN: &[u8] = b"hepta.knowledge-publication.v2";
const QUERY_DOMAIN: &[u8] = b"hepta.knowledge-query-result.v2";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum KnowledgeRelationKindV2 {
    Supports,
    Contradicts,
    TemporalBefore,
    TemporalAfter,
    Causes,
    Enables,
    ProcedureStep,
    PromptComplements,
    PromptSubstitutes,
    PromptConflicts,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct KnowledgeSupportV2 {
    pub source_id: StableId,
    pub source_revision: Revision,
    pub source_fact_digest: Digest32,
    pub validity_digest: Digest32,
    pub tombstoned: bool,
}

impl KnowledgeSupportV2 {
    fn validate(&self) -> Result<(), KnowledgeGenerationErrorV2> {
        ensure_digest("support_fact", self.source_fact_digest)?;
        ensure_digest("support_validity", self.validity_digest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeNodeV2 {
    pub node_id: StableId,
    pub node_kind_id: StableId,
    pub payload_digest: Digest32,
    pub supports: Vec<KnowledgeSupportV2>,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct KnowledgeEdgeIdentityV2 {
    pub source_node_id: StableId,
    pub relation: KnowledgeRelationKindV2,
    pub target_node_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeEdgeV2 {
    pub identity: KnowledgeEdgeIdentityV2,
    pub confidence: ProbabilityQ32,
    pub validity_digest: Digest32,
    pub supports: Vec<KnowledgeSupportV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeProjectionInputV2 {
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub complete_source_cut: bool,
    pub nodes: Vec<KnowledgeNodeV2>,
    pub edges: Vec<KnowledgeEdgeV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeGenerationV2 {
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub nodes: Vec<KnowledgeNodeV2>,
    pub edges: Vec<KnowledgeEdgeV2>,
    pub generation_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl KnowledgeGenerationV2 {
    pub fn validate(&self) -> Result<(), KnowledgeGenerationErrorV2> {
        validate_generation_fields(
            self.source_snapshot_digest,
            self.generation_vector_digest,
            self.graph_profile_digest,
            &self.nodes,
            &self.edges,
        )?;
        if self.authority.grants_any() {
            return Err(KnowledgeGenerationErrorV2::AuthorityGranted);
        }
        if self.generation_digest != compute_generation_digest(self) {
            return Err(KnowledgeGenerationErrorV2::DigestMismatch(
                "generation",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeProjectionDeltaV2 {
    pub expected_predecessor_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    pub remove_node_ids: Vec<StableId>,
    pub upsert_nodes: Vec<KnowledgeNodeV2>,
    pub remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    pub upsert_edges: Vec<KnowledgeEdgeV2>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KnowledgePublicationDispositionV2 {
    Published,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgePublicationReceiptV2 {
    pub generation: Generation,
    pub predecessor_generation: Option<Generation>,
    pub predecessor_digest: Option<Digest32>,
    pub generation_digest: Digest32,
    pub disposition: KnowledgePublicationDispositionV2,
    pub publication_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl KnowledgePublicationReceiptV2 {
    pub fn validate(&self) -> Result<(), KnowledgeGenerationErrorV2> {
        ensure_digest("published_generation", self.generation_digest)?;
        match (self.predecessor_generation, self.predecessor_digest) {
            (None, None) if self.generation.get() == 1 => {}
            (Some(generation), Some(digest))
                if generation.next().ok() == Some(self.generation) =>
            {
                ensure_digest("publication_predecessor", digest)?;
            }
            _ => {
                return Err(KnowledgeGenerationErrorV2::InvalidPredecessor);
            }
        }
        if self.authority.grants_any() {
            return Err(KnowledgeGenerationErrorV2::AuthorityGranted);
        }
        if self.publication_digest != compute_publication_digest(self) {
            return Err(KnowledgeGenerationErrorV2::DigestMismatch(
                "publication",
            ));
        }
        Ok(())
    }
}

pub fn build_complete_generation(
    generation: Generation,
    input: KnowledgeProjectionInputV2,
) -> Result<KnowledgeGenerationV2, KnowledgeGenerationErrorV2> {
    if !input.complete_source_cut {
        return Err(KnowledgeGenerationErrorV2::IncompleteSourceCut);
    }
    canonicalize_generation(
        generation,
        input.source_snapshot_digest,
        input.generation_vector_digest,
        input.graph_profile_digest,
        input.nodes,
        input.edges,
    )
}

pub fn apply_incremental_delta(
    predecessor: &KnowledgeGenerationV2,
    generation: Generation,
    delta: KnowledgeProjectionDeltaV2,
) -> Result<KnowledgeGenerationV2, KnowledgeGenerationErrorV2> {
    predecessor.validate()?;
    if delta.expected_predecessor_digest != predecessor.generation_digest {
        return Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "delta_predecessor",
        ));
    }
    if predecessor.generation.next().ok() != Some(generation) {
        return Err(KnowledgeGenerationErrorV2::InvalidPredecessor);
    }
    if delta.graph_profile_digest != predecessor.graph_profile_digest {
        return Err(KnowledgeGenerationErrorV2::ProfileChangedInDelta);
    }
    ensure_unique_ids("remove_node", &delta.remove_node_ids)?;
    ensure_unique_edge_ids("remove_edge", &delta.remove_edge_identities)?;

    let mut nodes = predecessor
        .nodes
        .iter()
        .cloned()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let mut edges = predecessor
        .edges
        .iter()
        .cloned()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();

    for node_id in delta.remove_node_ids {
        nodes.remove(&node_id);
        edges.retain(|identity, _| {
            identity.source_node_id != node_id && identity.target_node_id != node_id
        });
    }
    for node in delta.upsert_nodes {
        nodes.insert(node.node_id.clone(), node);
    }
    for identity in delta.remove_edge_identities {
        edges.remove(&identity);
    }
    for edge in delta.upsert_edges {
        edges.insert(edge.identity.clone(), edge);
    }

    canonicalize_generation(
        generation,
        delta.source_snapshot_digest,
        delta.generation_vector_digest,
        delta.graph_profile_digest,
        nodes.into_values().collect(),
        edges.into_values().collect(),
    )
}

pub fn publish_generation(
    predecessor: Option<&KnowledgeGenerationV2>,
    candidate: &KnowledgeGenerationV2,
) -> Result<KnowledgePublicationReceiptV2, KnowledgeGenerationErrorV2> {
    candidate.validate()?;
    let (predecessor_generation, predecessor_digest, disposition) = match predecessor {
        None => {
            if candidate.generation.get() != 1 {
                return Err(KnowledgeGenerationErrorV2::InvalidPredecessor);
            }
            (None, None, KnowledgePublicationDispositionV2::Published)
        }
        Some(predecessor) => {
            predecessor.validate()?;
            if predecessor.generation.next().ok() != Some(candidate.generation) {
                return Err(KnowledgeGenerationErrorV2::InvalidPredecessor);
            }
            let semantic_unchanged = predecessor.generation_vector_digest
                == candidate.generation_vector_digest
                && predecessor.graph_profile_digest == candidate.graph_profile_digest
                && predecessor.nodes == candidate.nodes
                && predecessor.edges == candidate.edges;
            (
                Some(predecessor.generation),
                Some(predecessor.generation_digest),
                if semantic_unchanged {
                    KnowledgePublicationDispositionV2::Unchanged
                } else {
                    KnowledgePublicationDispositionV2::Published
                },
            )
        }
    };
    let mut receipt = KnowledgePublicationReceiptV2 {
        generation: candidate.generation,
        predecessor_generation,
        predecessor_digest,
        generation_digest: candidate.generation_digest,
        disposition,
        publication_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.publication_digest = compute_publication_digest(&receipt);
    receipt.validate()?;
    Ok(receipt)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeRelationQueryV2 {
    pub query_id: StableId,
    pub generation_digest: Digest32,
    pub seed_node_ids: Vec<StableId>,
    pub relation_kinds: Vec<KnowledgeRelationKindV2>,
    pub maximum_edges: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeRelationResultV2 {
    pub query_id: StableId,
    pub generation_digest: Digest32,
    pub edges: Vec<KnowledgeEdgeV2>,
    pub omitted_count: u32,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn query_relations(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
    generation.validate()?;
    if query.generation_digest != generation.generation_digest {
        return Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation",
        ));
    }
    ensure_unique_ids("query_seed", &query.seed_node_ids)?;
    let mut relation_kinds = BTreeSet::new();
    for kind in query.relation_kinds {
        if !relation_kinds.insert(kind) {
            return Err(KnowledgeGenerationErrorV2::DuplicateRelationKind);
        }
    }
    let maximum_edges = usize::try_from(query.maximum_edges).unwrap_or(usize::MAX);
    if maximum_edges == 0 || maximum_edges > MAX_KNOWLEDGE_EDGES_V2 {
        return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit);
    }
    let seeds = query.seed_node_ids.into_iter().collect::<BTreeSet<_>>();
    let mut edges = generation
        .edges
        .iter()
        .filter(|edge| {
            (seeds.contains(&edge.identity.source_node_id)
                || seeds.contains(&edge.identity.target_node_id))
                && (relation_kinds.is_empty() || relation_kinds.contains(&edge.identity.relation))
        })
        .cloned()
        .collect::<Vec<_>>();
    let omitted_count = edges.len().saturating_sub(maximum_edges);
    edges.truncate(maximum_edges);
    let mut result = KnowledgeRelationResultV2 {
        query_id: query.query_id,
        generation_digest: generation.generation_digest,
        edges,
        omitted_count: u32::try_from(omitted_count).unwrap_or(u32::MAX),
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = compute_query_result_digest(&result);
    Ok(result)
}

fn canonicalize_generation(
    generation: Generation,
    source_snapshot_digest: Digest32,
    generation_vector_digest: Digest32,
    graph_profile_digest: Digest32,
    nodes: Vec<KnowledgeNodeV2>,
    edges: Vec<KnowledgeEdgeV2>,
) -> Result<KnowledgeGenerationV2, KnowledgeGenerationErrorV2> {
    ensure_digest("source_snapshot", source_snapshot_digest)?;
    ensure_digest("generation_vector", generation_vector_digest)?;
    ensure_digest("graph_profile", graph_profile_digest)?;
    if nodes.len() > MAX_KNOWLEDGE_NODES_V2 {
        return Err(KnowledgeGenerationErrorV2::NodeLimitExceeded);
    }
    if edges.len() > MAX_KNOWLEDGE_EDGES_V2 {
        return Err(KnowledgeGenerationErrorV2::EdgeLimitExceeded);
    }

    let mut canonical_nodes = BTreeMap::<StableId, KnowledgeNodeV2>::new();
    for mut node in nodes {
        ensure_digest("node_payload", node.payload_digest)?;
        canonicalize_supports(&mut node.supports)?;
        node.supports.retain(|support| !support.tombstoned);
        if node.supports.is_empty() {
            continue;
        }
        let node_id = node.node_id.clone();
        if canonical_nodes.insert(node_id.clone(), node).is_some() {
            return Err(KnowledgeGenerationErrorV2::DuplicateNode(
                node_id.to_string(),
            ));
        }
    }

    let node_ids = canonical_nodes.keys().cloned().collect::<BTreeSet<_>>();
    let mut canonical_edges = BTreeMap::<KnowledgeEdgeIdentityV2, KnowledgeEdgeV2>::new();
    for mut edge in edges {
        ensure_digest("edge_validity", edge.validity_digest)?;
        if !node_ids.contains(&edge.identity.source_node_id)
            || !node_ids.contains(&edge.identity.target_node_id)
        {
            return Err(KnowledgeGenerationErrorV2::UnknownEdgeNode);
        }
        canonicalize_supports(&mut edge.supports)?;
        edge.supports.retain(|support| !support.tombstoned);
        if edge.supports.is_empty() {
            continue;
        }
        let identity = edge.identity.clone();
        if canonical_edges.insert(identity.clone(), edge).is_some() {
            return Err(KnowledgeGenerationErrorV2::DuplicateEdge(identity));
        }
    }

    let mut result = KnowledgeGenerationV2 {
        generation,
        source_snapshot_digest,
        generation_vector_digest,
        graph_profile_digest,
        nodes: canonical_nodes.into_values().collect(),
        edges: canonical_edges.into_values().collect(),
        generation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.generation_digest = compute_generation_digest(&result);
    result.validate()?;
    Ok(result)
}

fn validate_generation_fields(
    source_snapshot_digest: Digest32,
    generation_vector_digest: Digest32,
    graph_profile_digest: Digest32,
    nodes: &[KnowledgeNodeV2],
    edges: &[KnowledgeEdgeV2],
) -> Result<(), KnowledgeGenerationErrorV2> {
    ensure_digest("source_snapshot", source_snapshot_digest)?;
    ensure_digest("generation_vector", generation_vector_digest)?;
    ensure_digest("graph_profile", graph_profile_digest)?;
    if nodes.len() > MAX_KNOWLEDGE_NODES_V2 {
        return Err(KnowledgeGenerationErrorV2::NodeLimitExceeded);
    }
    if edges.len() > MAX_KNOWLEDGE_EDGES_V2 {
        return Err(KnowledgeGenerationErrorV2::EdgeLimitExceeded);
    }
    let mut node_ids = BTreeSet::new();
    for node in nodes {
        if !node_ids.insert(node.node_id.clone()) {
            return Err(KnowledgeGenerationErrorV2::DuplicateNode(
                node.node_id.to_string(),
            ));
        }
        ensure_digest("node_payload", node.payload_digest)?;
        validate_live_supports(&node.supports)?;
    }
    let mut edge_ids = BTreeSet::new();
    for edge in edges {
        if !node_ids.contains(&edge.identity.source_node_id)
            || !node_ids.contains(&edge.identity.target_node_id)
        {
            return Err(KnowledgeGenerationErrorV2::UnknownEdgeNode);
        }
        if !edge_ids.insert(edge.identity.clone()) {
            return Err(KnowledgeGenerationErrorV2::DuplicateEdge(
                edge.identity.clone(),
            ));
        }
        ensure_digest("edge_validity", edge.validity_digest)?;
        validate_live_supports(&edge.supports)?;
    }
    Ok(())
}

fn canonicalize_supports(
    supports: &mut Vec<KnowledgeSupportV2>,
) -> Result<(), KnowledgeGenerationErrorV2> {
    if supports.len() > MAX_SUPPORTS_PER_RELATION_V2 {
        return Err(KnowledgeGenerationErrorV2::SupportLimitExceeded);
    }
    supports.sort();
    let mut identities = BTreeSet::new();
    for support in supports.iter() {
        support.validate()?;
        let identity = (support.source_id.clone(), support.source_revision);
        if !identities.insert(identity) {
            return Err(KnowledgeGenerationErrorV2::DuplicateSupport);
        }
    }
    Ok(())
}

fn validate_live_supports(
    supports: &[KnowledgeSupportV2],
) -> Result<(), KnowledgeGenerationErrorV2> {
    if supports.is_empty() || supports.len() > MAX_SUPPORTS_PER_RELATION_V2 {
        return Err(KnowledgeGenerationErrorV2::InvalidSupportSet);
    }
    if supports.iter().any(|support| support.tombstoned) {
        return Err(KnowledgeGenerationErrorV2::TombstonedSupportVisible);
    }
    let mut previous: Option<&KnowledgeSupportV2> = None;
    for support in supports {
        support.validate()?;
        if previous.is_some_and(|value| value >= support) {
            return Err(KnowledgeGenerationErrorV2::NonCanonicalSupportOrder);
        }
        previous = Some(support);
    }
    Ok(())
}

fn compute_generation_digest(generation: &KnowledgeGenerationV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(GENERATION_DOMAIN);
    push_u64(&mut bytes, generation.generation.get());
    push_digest(&mut bytes, generation.source_snapshot_digest);
    push_digest(&mut bytes, generation.generation_vector_digest);
    push_digest(&mut bytes, generation.graph_profile_digest);
    push_len(&mut bytes, generation.nodes.len());
    for node in &generation.nodes {
        push_id(&mut bytes, &node.node_id);
        push_id(&mut bytes, &node.node_kind_id);
        push_digest(&mut bytes, node.payload_digest);
        push_supports(&mut bytes, &node.supports);
    }
    push_len(&mut bytes, generation.edges.len());
    for edge in &generation.edges {
        push_edge_identity(&mut bytes, &edge.identity);
        push_u64(&mut bytes, edge.confidence.raw());
        push_digest(&mut bytes, edge.validity_digest);
        push_supports(&mut bytes, &edge.supports);
    }
    Digest32::of_bytes(&bytes)
}

fn compute_publication_digest(receipt: &KnowledgePublicationReceiptV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(PUBLICATION_DOMAIN);
    push_u64(&mut bytes, receipt.generation.get());
    match (receipt.predecessor_generation, receipt.predecessor_digest) {
        (Some(generation), Some(digest)) => {
            bytes.push(1);
            push_u64(&mut bytes, generation.get());
            push_digest(&mut bytes, digest);
        }
        _ => bytes.push(0),
    }
    push_digest(&mut bytes, receipt.generation_digest);
    bytes.push(match receipt.disposition {
        KnowledgePublicationDispositionV2::Published => 0,
        KnowledgePublicationDispositionV2::Unchanged => 1,
    });
    Digest32::of_bytes(&bytes)
}

fn compute_query_result_digest(result: &KnowledgeRelationResultV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(QUERY_DOMAIN);
    push_id(&mut bytes, &result.query_id);
    push_digest(&mut bytes, result.generation_digest);
    push_u64(&mut bytes, u64::from(result.omitted_count));
    push_len(&mut bytes, result.edges.len());
    for edge in &result.edges {
        push_edge_identity(&mut bytes, &edge.identity);
        push_u64(&mut bytes, edge.confidence.raw());
        push_digest(&mut bytes, edge.validity_digest);
        push_supports(&mut bytes, &edge.supports);
    }
    Digest32::of_bytes(&bytes)
}

fn push_edge_identity(bytes: &mut Vec<u8>, identity: &KnowledgeEdgeIdentityV2) {
    push_id(bytes, &identity.source_node_id);
    bytes.push(relation_code(identity.relation));
    push_id(bytes, &identity.target_node_id);
}

fn push_supports(bytes: &mut Vec<u8>, supports: &[KnowledgeSupportV2]) {
    push_len(bytes, supports.len());
    for support in supports {
        push_id(bytes, &support.source_id);
        push_u64(bytes, support.source_revision.get());
        push_digest(bytes, support.source_fact_digest);
        push_digest(bytes, support.validity_digest);
    }
}

fn ensure_unique_ids(
    _label: &'static str,
    values: &[StableId],
) -> Result<(), KnowledgeGenerationErrorV2> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity);
        }
    }
    Ok(())
}

fn ensure_unique_edge_ids(
    _label: &'static str,
    values: &[KnowledgeEdgeIdentityV2],
) -> Result<(), KnowledgeGenerationErrorV2> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity);
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgeGenerationErrorV2 {
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    IncompleteSourceCut,
    NodeLimitExceeded,
    EdgeLimitExceeded,
    SupportLimitExceeded,
    DuplicateNode(String),
    DuplicateEdge(KnowledgeEdgeIdentityV2),
    DuplicateSupport,
    DuplicateDeltaIdentity,
    UnknownEdgeNode,
    InvalidSupportSet,
    TombstonedSupportVisible,
    NonCanonicalSupportOrder,
    InvalidPredecessor,
    ProfileChangedInDelta,
    DuplicateRelationKind,
    InvalidQueryLimit,
    AuthorityGranted,
}

impl fmt::Display for KnowledgeGenerationErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for KnowledgeGenerationErrorV2 {}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), KnowledgeGenerationErrorV2> {
    if digest.is_zero() {
        return Err(KnowledgeGenerationErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn relation_code(value: KnowledgeRelationKindV2) -> u8 {
    match value {
        KnowledgeRelationKindV2::Supports => 0,
        KnowledgeRelationKindV2::Contradicts => 1,
        KnowledgeRelationKindV2::TemporalBefore => 2,
        KnowledgeRelationKindV2::TemporalAfter => 3,
        KnowledgeRelationKindV2::Causes => 4,
        KnowledgeRelationKindV2::Enables => 5,
        KnowledgeRelationKindV2::ProcedureStep => 6,
        KnowledgeRelationKindV2::PromptComplements => 7,
        KnowledgeRelationKindV2::PromptSubstitutes => 8,
        KnowledgeRelationKindV2::PromptConflicts => 9,
    }
}

#[cfg(test)]
#[path = "generation_tests.rs"]
mod tests;
