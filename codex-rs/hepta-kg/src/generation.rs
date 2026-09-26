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
/// Hard cap for retained explicit supports on one canonical node or edge.
///
/// The composed cognitive SQLite owner admits at most 50,000 edge occurrences
/// per scope. Keeping the kernel ceiling at least that large prevents the
/// canonical adapter from introducing a stricter hidden production limit while
/// still bounding sort/digest work and retained lineage.
pub const MAX_SUPPORTS_PER_RELATION_V2: usize = 50_000;
const GENERATION_DOMAIN: &[u8] = b"hepta.knowledge-generation.v2";
const PUBLICATION_DOMAIN: &[u8] = b"hepta.knowledge-publication.v2";
const QUERY_REQUEST_DOMAIN: &[u8] = b"hepta.knowledge-query-request.v2";
const QUERY_DOMAIN: &[u8] = b"hepta.knowledge-query-result.v2";

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
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
    /// Product-owned relation identity that does not fit one of the closed
    /// semantic classes above. The identifier must already be canonical and
    /// stable for the source graph profile.
    Custom(StableId),
    PromptRequires,
    PromptDominates,
    PromptRedundant,
    PromptSupersedes,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct KnowledgeSupportV2 {
    pub source_id: StableId,
    pub source_revision: Revision,
    pub source_fact_digest: Digest32,
    pub validity_digest: Digest32,
    /// Inclusive temporal visibility bound when this support is time-scoped.
    /// `None` means the source contract does not impose a clock lower bound.
    pub valid_from_unix_seconds: Option<i64>,
    /// Exclusive temporal visibility bound. `None` means no time expiry.
    pub valid_to_unix_seconds: Option<i64>,
    pub tombstoned: bool,
}

impl KnowledgeSupportV2 {
    fn validate(&self) -> Result<(), KnowledgeGenerationErrorV2> {
        ensure_digest("support_fact", self.source_fact_digest)?;
        ensure_digest("support_validity", self.validity_digest)?;
        if self
            .valid_from_unix_seconds
            .zip(self.valid_to_unix_seconds)
            .is_some_and(|(valid_from, valid_to)| valid_to <= valid_from)
        {
            return Err(KnowledgeGenerationErrorV2::InvalidValidityWindow);
        }
        Ok(())
    }

    fn visible_at(&self, unix_seconds: i64) -> bool {
        self.valid_from_unix_seconds
            .is_none_or(|valid_from| valid_from <= unix_seconds)
            && self
                .valid_to_unix_seconds
                .is_none_or(|valid_to| unix_seconds < valid_to)
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
            return Err(KnowledgeGenerationErrorV2::DigestMismatch("generation"));
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
            (Some(generation), Some(digest)) if generation.next().ok() == Some(self.generation) => {
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
            return Err(KnowledgeGenerationErrorV2::DigestMismatch("publication"));
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
    let mut upsert_node_ids = BTreeSet::new();
    if delta
        .upsert_nodes
        .iter()
        .any(|node| !upsert_node_ids.insert(node.node_id.clone()))
    {
        return Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity);
    }
    let mut upsert_edge_ids = BTreeSet::new();
    if delta
        .upsert_edges
        .iter()
        .any(|edge| !upsert_edge_ids.insert(edge.identity.clone()))
    {
        return Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity);
    }

    // Resolve removals and replacements before copying retained payloads.
    // Repeated per-node `retain` scanned all edges once for every deletion.
    // The sets preserve remove-before-upsert semantics with one history pass.
    let removed_nodes = delta.remove_node_ids.iter().collect::<BTreeSet<_>>();
    let removed_edges = delta.remove_edge_identities.iter().collect::<BTreeSet<_>>();
    let nodes = predecessor
        .nodes
        .iter()
        .filter(|node| {
            !removed_nodes.contains(&node.node_id) && !upsert_node_ids.contains(&node.node_id)
        })
        .cloned()
        .chain(delta.upsert_nodes)
        .collect();
    let edges = predecessor
        .edges
        .iter()
        .filter(|edge| {
            !removed_nodes.contains(&edge.identity.source_node_id)
                && !removed_nodes.contains(&edge.identity.target_node_id)
                && !removed_edges.contains(&edge.identity)
                && !upsert_edge_ids.contains(&edge.identity)
        })
        .cloned()
        .chain(delta.upsert_edges)
        .collect();

    canonicalize_generation(
        generation,
        delta.source_snapshot_digest,
        delta.generation_vector_digest,
        delta.graph_profile_digest,
        nodes,
        edges,
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

/// Deterministic work counters for one accepted relation query.
///
/// The validation fields count records in the generation that is fully checked
/// before selection. The visibility and relation fields count the actual
/// selection-loop inspections. This is diagnostic evidence only and grants no
/// authority or host-independent latency claim.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct KnowledgeRelationQueryWorkV2 {
    pub validated_nodes: u64,
    pub validated_edges: u64,
    pub validated_supports: u64,
    pub visibility_nodes_scanned: u64,
    pub visibility_supports_inspected: u64,
    pub relation_edges_scanned: u64,
    pub relation_supports_inspected: u64,
    pub matching_edges: u64,
    pub selected_edges_cloned: u64,
    pub selected_supports_cloned: u64,
    pub omitted_edges: u64,
}

pub fn query_relations(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
    query_relations_impl::<false>(generation, query).map(|(result, _work)| result)
}

/// Query with deterministic work diagnostics; result bytes match `query_relations`.
pub fn query_relations_with_work(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<(KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2), KnowledgeGenerationErrorV2> {
    query_relations_impl::<true>(generation, query)
}

fn query_relations_impl<const MEASURE_WORK: bool>(
    generation: &KnowledgeGenerationV2,
    query: KnowledgeRelationQueryV2,
) -> Result<(KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2), KnowledgeGenerationErrorV2> {
    generation.validate()?;
    let mut work = KnowledgeRelationQueryWorkV2::default();
    if MEASURE_WORK {
        work.validated_nodes = saturating_u64(generation.nodes.len());
        work.validated_edges = saturating_u64(generation.edges.len());
        work.validated_supports = generation
            .nodes
            .iter()
            .map(|node| saturating_u64(node.supports.len()))
            .chain(
                generation
                    .edges
                    .iter()
                    .map(|edge| saturating_u64(edge.supports.len())),
            )
            .fold(0_u64, u64::saturating_add);
    }
    if query.generation_digest != generation.generation_digest {
        return Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation",
        ));
    }
    ensure_unique_ids("query_seed", &query.seed_node_ids)?;
    let seeds = query.seed_node_ids.iter().cloned().collect::<BTreeSet<_>>();
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
        let mut visible = BTreeSet::new();
        for node in &generation.nodes {
            if MEASURE_WORK {
                work.visibility_nodes_scanned = work.visibility_nodes_scanned.saturating_add(1);
            }
            let mut node_is_visible = false;
            for support in &node.supports {
                if MEASURE_WORK {
                    work.visibility_supports_inspected =
                        work.visibility_supports_inspected.saturating_add(1);
                }
                if support.visible_at(at) {
                    node_is_visible = true;
                    break;
                }
            }
            if node_is_visible {
                visible.insert(node.node_id.clone());
            }
        }
        visible
    });
    let (edges, omitted_count) = collect_relation_query_edges::<MEASURE_WORK>(
        generation,
        &seeds,
        &relation_kinds,
        visible_nodes.as_ref(),
        query.valid_at_unix_seconds,
        maximum_edges,
        &mut work,
    );
    let mut result = KnowledgeRelationResultV2 {
        query_id: query.query_id,
        generation_digest: generation.generation_digest,
        valid_at_unix_seconds: query.valid_at_unix_seconds,
        request_digest,
        edges,
        omitted_count: u32::try_from(omitted_count).unwrap_or(u32::MAX),
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = compute_query_result_digest(&result);
    if MEASURE_WORK {
        debug_assert_eq!(work.omitted_edges, saturating_u64(omitted_count));
    }
    Ok((result, work))
}

fn collect_relation_query_edges<const MEASURE_WORK: bool>(
    generation: &KnowledgeGenerationV2,
    seeds: &BTreeSet<StableId>,
    relation_kinds: &BTreeSet<KnowledgeRelationKindV2>,
    visible_nodes: Option<&BTreeSet<StableId>>,
    valid_at_unix_seconds: Option<i64>,
    maximum_edges: usize,
    work: &mut KnowledgeRelationQueryWorkV2,
) -> (Vec<KnowledgeEdgeV2>, usize) {
    let mut selected_edges = Vec::with_capacity(maximum_edges.min(generation.edges.len()));
    let mut omitted_count = 0usize;
    for edge in &generation.edges {
        if MEASURE_WORK {
            work.relation_edges_scanned = work.relation_edges_scanned.saturating_add(1);
        }
        let identity = &edge.identity;
        if !(seeds.contains(&identity.source_node_id) || seeds.contains(&identity.target_node_id))
            || !(relation_kinds.is_empty() || relation_kinds.contains(&identity.relation))
            || visible_nodes.is_some_and(|visible| {
                !visible.contains(&identity.source_node_id)
                    || !visible.contains(&identity.target_node_id)
            })
        {
            continue;
        }

        if selected_edges.len() == maximum_edges {
            if let Some(at) = valid_at_unix_seconds {
                let mut visible = false;
                for support in &edge.supports {
                    if MEASURE_WORK {
                        work.relation_supports_inspected =
                            work.relation_supports_inspected.saturating_add(1);
                    }
                    if support.visible_at(at) {
                        visible = true;
                        break;
                    }
                }
                if !visible {
                    continue;
                }
            }
            if MEASURE_WORK {
                work.matching_edges = work.matching_edges.saturating_add(1);
                work.omitted_edges = work.omitted_edges.saturating_add(1);
            }
            omitted_count = omitted_count.saturating_add(1);
            continue;
        }

        let selected = if let Some(at) = valid_at_unix_seconds {
            let mut supports = Vec::new();
            for support in &edge.supports {
                if MEASURE_WORK {
                    work.relation_supports_inspected =
                        work.relation_supports_inspected.saturating_add(1);
                }
                if support.visible_at(at) {
                    supports.push(support.clone());
                }
            }
            if supports.is_empty() {
                continue;
            }
            if MEASURE_WORK {
                work.selected_supports_cloned = work
                    .selected_supports_cloned
                    .saturating_add(saturating_u64(supports.len()));
            }
            KnowledgeEdgeV2 {
                identity: edge.identity.clone(),
                confidence: edge.confidence,
                validity_digest: edge.validity_digest,
                supports,
            }
        } else {
            if MEASURE_WORK {
                work.selected_supports_cloned = work
                    .selected_supports_cloned
                    .saturating_add(saturating_u64(edge.supports.len()));
            }
            edge.clone()
        };
        if MEASURE_WORK {
            work.matching_edges = work.matching_edges.saturating_add(1);
            work.selected_edges_cloned = work.selected_edges_cloned.saturating_add(1);
        }
        selected_edges.push(selected);
    }
    (selected_edges, omitted_count)
}

fn saturating_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
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
    supports: &mut [KnowledgeSupportV2],
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

fn push_edge_identity(bytes: &mut Vec<u8>, identity: &KnowledgeEdgeIdentityV2) {
    push_id(bytes, &identity.source_node_id);
    push_relation_kind(bytes, &identity.relation);
    push_id(bytes, &identity.target_node_id);
}

fn push_supports(bytes: &mut Vec<u8>, supports: &[KnowledgeSupportV2]) {
    push_len(bytes, supports.len());
    for support in supports {
        push_id(bytes, &support.source_id);
        push_u64(bytes, support.source_revision.get());
        push_digest(bytes, support.source_fact_digest);
        push_digest(bytes, support.validity_digest);
        match support.valid_from_unix_seconds {
            Some(valid_from) => {
                bytes.push(1);
                push_i64(bytes, valid_from);
            }
            None => bytes.push(0),
        }
        match support.valid_to_unix_seconds {
            Some(valid_to) => {
                bytes.push(1);
                push_i64(bytes, valid_to);
            }
            None => bytes.push(0),
        }
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
    InvalidValidityWindow,
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

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), KnowledgeGenerationErrorV2> {
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

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_relation_kind(bytes: &mut Vec<u8>, value: &KnowledgeRelationKindV2) {
    match value {
        KnowledgeRelationKindV2::Supports => bytes.push(0),
        KnowledgeRelationKindV2::Contradicts => bytes.push(1),
        KnowledgeRelationKindV2::TemporalBefore => bytes.push(2),
        KnowledgeRelationKindV2::TemporalAfter => bytes.push(3),
        KnowledgeRelationKindV2::Causes => bytes.push(4),
        KnowledgeRelationKindV2::Enables => bytes.push(5),
        KnowledgeRelationKindV2::ProcedureStep => bytes.push(6),
        KnowledgeRelationKindV2::PromptComplements => bytes.push(7),
        KnowledgeRelationKindV2::PromptSubstitutes => bytes.push(8),
        KnowledgeRelationKindV2::PromptConflicts => bytes.push(9),
        KnowledgeRelationKindV2::Custom(relation_id) => {
            bytes.push(10);
            push_id(bytes, relation_id);
        }
        KnowledgeRelationKindV2::PromptRequires => bytes.push(11),
        KnowledgeRelationKindV2::PromptDominates => bytes.push(12),
        KnowledgeRelationKindV2::PromptRedundant => bytes.push(13),
        KnowledgeRelationKindV2::PromptSupersedes => bytes.push(14),
    }
}

#[cfg(test)]
#[path = "generation_tests.rs"]
mod tests;
