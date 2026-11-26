//! Bounded relation queries over canonical, immutable generation snapshots.

use super::AuthorityPosture;
use super::Digest32;
use super::KnowledgeEdgeV2;
use super::KnowledgeGenerationErrorV2;
use super::KnowledgeGenerationV2;
use super::KnowledgeRelationKindV2;
use super::MAX_KNOWLEDGE_EDGES_V2;
use super::MAX_KNOWLEDGE_NODES_V2;
use super::QUERY_DOMAIN;
use super::QUERY_REQUEST_DOMAIN;
use super::StableId;
use super::ensure_unique_ids;
use super::push_digest;
use super::push_edge_identity;
use super::push_i64;
use super::push_id;
use super::push_len;
use super::push_relation_kind;
use super::push_supports;
use super::push_u64;
use std::collections::BTreeSet;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeRelationQueryV2 {
    pub query_id: StableId,
    pub generation_digest: Digest32,
    /// At most `MAX_KNOWLEDGE_NODES_V2` distinct seed identities.
    pub seed_node_ids: Vec<StableId>,
    /// At most `MAX_KNOWLEDGE_EDGES_V2` distinct relation filters.
    pub relation_kinds: Vec<KnowledgeRelationKindV2>,
    /// Optional query-time validity cut. `None` performs a structural query;
    /// `Some(t)` returns only nodes/edge supports visible at `t`.
    pub valid_at_unix_seconds: Option<i64>,
    pub maximum_edges: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeRelationResultV2 {
    pub query_id: StableId,
    pub generation_digest: Digest32,
    pub valid_at_unix_seconds: Option<i64>,
    /// Canonical digest of the complete request, including seeds, relation
    /// filters, temporal cut and edge bound.
    pub request_digest: Digest32,
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
    query_relations_validated(generation, query)
}

pub(super) fn query_relations_validated(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
    if query.generation_digest != generation.generation_digest {
        return Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation",
        ));
    }
    if query.seed_node_ids.len() > MAX_KNOWLEDGE_NODES_V2
        || query.relation_kinds.len() > MAX_KNOWLEDGE_EDGES_V2
    {
        return Err(KnowledgeGenerationErrorV2::QueryInputLimitExceeded);
    }
    let seeds = ensure_unique_ids("query_seed", &query.seed_node_ids)?;
    let mut relation_kinds = BTreeSet::new();
    for kind in query.relation_kinds.iter().cloned() {
        if !relation_kinds.insert(kind) {
            return Err(KnowledgeGenerationErrorV2::DuplicateRelationKind);
        }
    }
    let maximum_edges = usize::try_from(query.maximum_edges).unwrap_or(usize::MAX);
    if maximum_edges == 0 || maximum_edges > MAX_KNOWLEDGE_EDGES_V2 {
        return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit);
    }
    let request_digest = compute_query_request_digest(&query, &seeds, &relation_kinds);
    let visible_nodes = query.valid_at_unix_seconds.map(|at| {
        generation
            .nodes
            .iter()
            .filter(|node| node.supports.iter().any(|support| support.visible_at(at)))
            .map(|node| node.node_id.clone())
            .collect::<BTreeSet<_>>()
    });
    let mut edges = Vec::new();
    let mut omitted_count = 0_u32;
    for edge in &generation.edges {
        if !(seeds.contains(&edge.identity.source_node_id)
            || seeds.contains(&edge.identity.target_node_id))
            || !(relation_kinds.is_empty() || relation_kinds.contains(&edge.identity.relation))
            || visible_nodes.as_ref().is_some_and(|visible| {
                !visible.contains(&edge.identity.source_node_id)
                    || !visible.contains(&edge.identity.target_node_id)
            })
            || query
                .valid_at_unix_seconds
                .is_some_and(|at| !edge.supports.iter().any(|support| support.visible_at(at)))
        {
            continue;
        }
        if edges.len() == maximum_edges {
            omitted_count += 1;
            continue;
        }
        let edge = match query.valid_at_unix_seconds {
            Some(at) => KnowledgeEdgeV2 {
                identity: edge.identity.clone(),
                confidence: edge.confidence,
                validity_digest: edge.validity_digest,
                supports: edge
                    .supports
                    .iter()
                    .filter(|support| support.visible_at(at))
                    .cloned()
                    .collect(),
            },
            None => edge.clone(),
        };
        edges.push(edge);
    }
    let mut result = KnowledgeRelationResultV2 {
        query_id: query.query_id,
        generation_digest: generation.generation_digest,
        valid_at_unix_seconds: query.valid_at_unix_seconds,
        request_digest,
        edges,
        omitted_count,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = compute_query_result_digest(&result);
    Ok(result)
}

fn compute_query_request_digest(
    query: &KnowledgeRelationQueryV2,
    seeds: &BTreeSet<StableId>,
    relation_kinds: &BTreeSet<KnowledgeRelationKindV2>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(QUERY_REQUEST_DOMAIN);
    push_id(&mut bytes, &query.query_id);
    push_digest(&mut bytes, query.generation_digest);
    push_len(&mut bytes, seeds.len());
    for seed in seeds {
        push_id(&mut bytes, seed);
    }
    push_len(&mut bytes, relation_kinds.len());
    for relation in relation_kinds {
        push_relation_kind(&mut bytes, relation);
    }
    match query.valid_at_unix_seconds {
        Some(valid_at) => {
            bytes.push(1);
            push_i64(&mut bytes, valid_at);
        }
        None => bytes.push(0),
    }
    push_u64(&mut bytes, u64::from(query.maximum_edges));
    Digest32::of_bytes(&bytes)
}

fn compute_query_result_digest(result: &KnowledgeRelationResultV2) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(QUERY_DOMAIN);
    push_id(&mut bytes, &result.query_id);
    push_digest(&mut bytes, result.generation_digest);
    push_digest(&mut bytes, result.request_digest);
    match result.valid_at_unix_seconds {
        Some(valid_at) => {
            bytes.push(1);
            push_i64(&mut bytes, valid_at);
        }
        None => bytes.push(0),
    }
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
