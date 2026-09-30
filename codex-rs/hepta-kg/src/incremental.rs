//! Reverse dependency index and bounded incremental publication plan.
//!
//! This module identifies the exact node/edge closure affected by changed
//! supports and emits an ordered storage delta. Full rebuild remains an oracle
//! and periodic audit path rather than the default mutation contract.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionDeltaV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeSupportV2;
use crate::apply_incremental_delta;
use crate::build_complete_generation;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct KnowledgeSupportIdentityV2 {
    pub source_id: StableId,
    pub source_revision: Revision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeDependencyIndexV2 {
    generation_digest: Digest32,
    support_to_nodes: BTreeMap<KnowledgeSupportIdentityV2, BTreeSet<StableId>>,
    support_to_edges: BTreeMap<KnowledgeSupportIdentityV2, BTreeSet<KnowledgeEdgeIdentityV2>>,
    node_to_edges: BTreeMap<StableId, BTreeSet<KnowledgeEdgeIdentityV2>>,
}

impl KnowledgeDependencyIndexV2 {
    pub fn build(generation: &KnowledgeGenerationV2) -> Result<Self, KnowledgeGenerationErrorV2> {
        generation.validate()?;
        let mut support_to_nodes =
            BTreeMap::<KnowledgeSupportIdentityV2, BTreeSet<StableId>>::new();
        let mut support_to_edges =
            BTreeMap::<KnowledgeSupportIdentityV2, BTreeSet<KnowledgeEdgeIdentityV2>>::new();
        let mut node_to_edges = BTreeMap::<StableId, BTreeSet<KnowledgeEdgeIdentityV2>>::new();
        for node in &generation.nodes {
            for support in &node.supports {
                support_to_nodes
                    .entry(support_identity(support))
                    .or_default()
                    .insert(node.node_id.clone());
            }
        }
        for edge in &generation.edges {
            node_to_edges
                .entry(edge.identity.source_node_id.clone())
                .or_default()
                .insert(edge.identity.clone());
            node_to_edges
                .entry(edge.identity.target_node_id.clone())
                .or_default()
                .insert(edge.identity.clone());
            for support in &edge.supports {
                support_to_edges
                    .entry(support_identity(support))
                    .or_default()
                    .insert(edge.identity.clone());
            }
        }
        Ok(Self {
            generation_digest: generation.generation_digest,
            support_to_nodes,
            support_to_edges,
            node_to_edges,
        })
    }

    pub fn generation_digest(&self) -> Digest32 {
        self.generation_digest
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct KnowledgeMutationFrontierV2 {
    pub changed_supports: Vec<KnowledgeSupportIdentityV2>,
    pub changed_node_ids: Vec<StableId>,
    pub changed_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct KnowledgeImpactClosureV2 {
    pub node_ids: BTreeSet<StableId>,
    pub edge_identities: BTreeSet<KnowledgeEdgeIdentityV2>,
}

/// Compute the directly affected storage closure.
///
/// A changed node reaches its incident predecessor edges, and a changed edge
/// reaches its two endpoint nodes. The traversal deliberately stops there:
/// recursively expanding through the newly reached endpoint nodes would turn a
/// local mutation into the entire connected component and would no longer be a
/// bounded incremental plan.
pub fn compute_impact_closure_v2(
    index: &KnowledgeDependencyIndexV2,
    frontier: &KnowledgeMutationFrontierV2,
) -> KnowledgeImpactClosureV2 {
    let mut closure = KnowledgeImpactClosureV2 {
        node_ids: frontier.changed_node_ids.iter().cloned().collect(),
        edge_identities: frontier.changed_edge_identities.iter().cloned().collect(),
    };
    for support in &frontier.changed_supports {
        if let Some(nodes) = index.support_to_nodes.get(support) {
            closure.node_ids.extend(nodes.iter().cloned());
        }
        if let Some(edges) = index.support_to_edges.get(support) {
            closure.edge_identities.extend(edges.iter().cloned());
        }
    }

    let directly_changed_nodes = closure.node_ids.clone();
    for node_id in directly_changed_nodes {
        if let Some(edges) = index.node_to_edges.get(&node_id) {
            closure.edge_identities.extend(edges.iter().cloned());
        }
    }

    let directly_changed_edges = closure.edge_identities.clone();
    for edge in directly_changed_edges {
        closure.node_ids.insert(edge.source_node_id);
        closure.node_ids.insert(edge.target_node_id);
    }
    closure
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeStorageDeltaV2 {
    pub expected_predecessor_digest: Digest32,
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub graph_profile_digest: Digest32,
    /// Digest of the exact canonical generation produced by this delta.
    pub generation_digest: Digest32,
    /// Storage owners delete edges before nodes to preserve referential safety.
    pub remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    pub remove_node_ids: Vec<StableId>,
    /// Storage owners upsert nodes before edges for the same reason.
    pub upsert_nodes: Vec<KnowledgeNodeV2>,
    pub upsert_edges: Vec<KnowledgeEdgeV2>,
    pub impact: KnowledgeImpactClosureV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeIncrementalPlanV2 {
    pub storage_delta: KnowledgeStorageDeltaV2,
    pub candidate: KnowledgeGenerationV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgeIncrementalErrorV2 {
    Generation(KnowledgeGenerationErrorV2),
    IndexGenerationMismatch,
    StorageDeltaDigestMismatch {
        expected: Digest32,
        observed: Digest32,
    },
    FullRebuildDiverged {
        incremental_digest: Digest32,
        full_digest: Digest32,
    },
    InvalidAuditInterval,
}

impl From<KnowledgeGenerationErrorV2> for KnowledgeIncrementalErrorV2 {
    fn from(error: KnowledgeGenerationErrorV2) -> Self {
        Self::Generation(error)
    }
}

impl fmt::Display for KnowledgeIncrementalErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for KnowledgeIncrementalErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Generation(error) => Some(error),
            Self::IndexGenerationMismatch
            | Self::StorageDeltaDigestMismatch { .. }
            | Self::FullRebuildDiverged { .. }
            | Self::InvalidAuditInterval => None,
        }
    }
}

/// Apply one semantic mutation and derive the exact canonical storage delta.
///
/// The caller-supplied mutation is never reused as a storage program. The
/// mutation first passes through canonical generation construction; the storage
/// delta is then computed from the predecessor and that canonical candidate.
/// This includes implicit incident-edge deletion and excludes entries removed by
/// tombstone/support canonicalization.
pub fn plan_incremental_publication_v2(
    predecessor: &KnowledgeGenerationV2,
    index: &KnowledgeDependencyIndexV2,
    generation: Generation,
    delta: KnowledgeProjectionDeltaV2,
) -> Result<KnowledgeIncrementalPlanV2, KnowledgeIncrementalErrorV2> {
    let candidate = apply_incremental_delta(predecessor, generation, delta)?;
    plan_generation_transition_v2(predecessor, index, &candidate)
}

/// Derive an exact storage transition for an already canonical candidate.
pub fn plan_generation_transition_v2(
    predecessor: &KnowledgeGenerationV2,
    index: &KnowledgeDependencyIndexV2,
    candidate: &KnowledgeGenerationV2,
) -> Result<KnowledgeIncrementalPlanV2, KnowledgeIncrementalErrorV2> {
    predecessor.validate()?;
    candidate.validate()?;
    if index.generation_digest != predecessor.generation_digest {
        return Err(KnowledgeIncrementalErrorV2::IndexGenerationMismatch);
    }
    if predecessor.generation.next().ok() != Some(candidate.generation) {
        return Err(KnowledgeGenerationErrorV2::InvalidPredecessor.into());
    }
    if predecessor.graph_profile_digest != candidate.graph_profile_digest {
        return Err(KnowledgeGenerationErrorV2::ProfileChangedInDelta.into());
    }

    let storage_delta = derive_storage_delta_v2(predecessor, index, candidate);
    let rebuilt = apply_storage_delta_v2(predecessor, &storage_delta)?;
    if rebuilt != *candidate {
        return Err(KnowledgeIncrementalErrorV2::FullRebuildDiverged {
            incremental_digest: rebuilt.generation_digest,
            full_digest: candidate.generation_digest,
        });
    }
    Ok(KnowledgeIncrementalPlanV2 {
        storage_delta,
        candidate: candidate.clone(),
    })
}

/// Reconstruct the canonical generation represented by a storage delta.
///
/// Durable owners can run this before commit or during recovery. A delta whose
/// payload no longer produces its bound generation digest fails closed.
pub fn apply_storage_delta_v2(
    predecessor: &KnowledgeGenerationV2,
    delta: &KnowledgeStorageDeltaV2,
) -> Result<KnowledgeGenerationV2, KnowledgeIncrementalErrorV2> {
    let candidate = apply_incremental_delta(
        predecessor,
        delta.generation,
        KnowledgeProjectionDeltaV2 {
            expected_predecessor_digest: delta.expected_predecessor_digest,
            source_snapshot_digest: delta.source_snapshot_digest,
            generation_vector_digest: delta.generation_vector_digest,
            graph_profile_digest: delta.graph_profile_digest,
            remove_node_ids: delta.remove_node_ids.clone(),
            upsert_nodes: delta.upsert_nodes.clone(),
            remove_edge_identities: delta.remove_edge_identities.clone(),
            upsert_edges: delta.upsert_edges.clone(),
        },
    )?;
    if candidate.generation_digest != delta.generation_digest {
        return Err(KnowledgeIncrementalErrorV2::StorageDeltaDigestMismatch {
            expected: delta.generation_digest,
            observed: candidate.generation_digest,
        });
    }
    Ok(candidate)
}

pub fn verify_incremental_equivalence_v2(
    predecessor: &KnowledgeGenerationV2,
    generation: Generation,
    delta: KnowledgeProjectionDeltaV2,
    full_input: KnowledgeProjectionInputV2,
) -> Result<KnowledgeGenerationV2, KnowledgeIncrementalErrorV2> {
    let incremental = apply_incremental_delta(predecessor, generation, delta)?;
    let full = build_complete_generation(generation, full_input)?;
    if incremental != full {
        return Err(KnowledgeIncrementalErrorV2::FullRebuildDiverged {
            incremental_digest: incremental.generation_digest,
            full_digest: full.generation_digest,
        });
    }
    Ok(incremental)
}

pub fn should_run_full_rebuild_audit_v2(
    generation: Generation,
    every_generations: u64,
) -> Result<bool, KnowledgeIncrementalErrorV2> {
    if every_generations == 0 {
        return Err(KnowledgeIncrementalErrorV2::InvalidAuditInterval);
    }
    Ok(generation.get().is_multiple_of(every_generations))
}

fn derive_storage_delta_v2(
    predecessor: &KnowledgeGenerationV2,
    index: &KnowledgeDependencyIndexV2,
    candidate: &KnowledgeGenerationV2,
) -> KnowledgeStorageDeltaV2 {
    let predecessor_nodes = predecessor
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let candidate_nodes = candidate
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let predecessor_edges = predecessor
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();
    let candidate_edges = candidate
        .edges
        .iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>();

    let mut remove_node_ids = Vec::new();
    for node_id in predecessor_nodes.keys() {
        if !candidate_nodes.contains_key(node_id) {
            remove_node_ids.push(node_id.clone());
        }
    }
    let mut upsert_nodes = Vec::new();
    for (node_id, node) in &candidate_nodes {
        if predecessor_nodes
            .get(node_id)
            .is_none_or(|old| *old != *node)
        {
            upsert_nodes.push((*node).clone());
        }
    }
    let mut remove_edge_identities = Vec::new();
    for identity in predecessor_edges.keys() {
        if !candidate_edges.contains_key(identity) {
            remove_edge_identities.push(identity.clone());
        }
    }
    let mut upsert_edges = Vec::new();
    for (identity, edge) in &candidate_edges {
        if predecessor_edges
            .get(identity)
            .is_none_or(|old| *old != *edge)
        {
            upsert_edges.push((*edge).clone());
        }
    }

    let changed_node_ids = remove_node_ids
        .iter()
        .cloned()
        .chain(upsert_nodes.iter().map(|node| node.node_id.clone()))
        .collect::<BTreeSet<_>>();
    let changed_edge_identities = remove_edge_identities
        .iter()
        .cloned()
        .chain(upsert_edges.iter().map(|edge| edge.identity.clone()))
        .collect::<BTreeSet<_>>();
    let frontier = frontier_from_transition(
        &predecessor_nodes,
        &candidate_nodes,
        &predecessor_edges,
        &candidate_edges,
        changed_node_ids,
        changed_edge_identities,
    );
    let impact = compute_impact_closure_v2(index, &frontier);

    KnowledgeStorageDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        generation: candidate.generation,
        source_snapshot_digest: candidate.source_snapshot_digest,
        generation_vector_digest: candidate.generation_vector_digest,
        graph_profile_digest: candidate.graph_profile_digest,
        generation_digest: candidate.generation_digest,
        remove_edge_identities,
        remove_node_ids,
        upsert_nodes,
        upsert_edges,
        impact,
    }
}

fn frontier_from_transition(
    predecessor_nodes: &BTreeMap<StableId, &KnowledgeNodeV2>,
    candidate_nodes: &BTreeMap<StableId, &KnowledgeNodeV2>,
    predecessor_edges: &BTreeMap<KnowledgeEdgeIdentityV2, &KnowledgeEdgeV2>,
    candidate_edges: &BTreeMap<KnowledgeEdgeIdentityV2, &KnowledgeEdgeV2>,
    changed_node_ids: BTreeSet<StableId>,
    changed_edge_identities: BTreeSet<KnowledgeEdgeIdentityV2>,
) -> KnowledgeMutationFrontierV2 {
    let mut changed_supports = BTreeSet::new();

    for node_id in &changed_node_ids {
        if let Some(node) = predecessor_nodes.get(node_id) {
            extend_support_identities(&mut changed_supports, &node.supports);
        }
        if let Some(node) = candidate_nodes.get(node_id) {
            extend_support_identities(&mut changed_supports, &node.supports);
        }
    }
    for identity in &changed_edge_identities {
        if let Some(edge) = predecessor_edges.get(identity) {
            extend_support_identities(&mut changed_supports, &edge.supports);
        }
        if let Some(edge) = candidate_edges.get(identity) {
            extend_support_identities(&mut changed_supports, &edge.supports);
        }
    }

    KnowledgeMutationFrontierV2 {
        changed_supports: changed_supports.into_iter().collect(),
        changed_node_ids: changed_node_ids.into_iter().collect(),
        changed_edge_identities: changed_edge_identities.into_iter().collect(),
    }
}

fn extend_support_identities(
    identities: &mut BTreeSet<KnowledgeSupportIdentityV2>,
    supports: &[KnowledgeSupportV2],
) {
    identities.extend(supports.iter().map(support_identity));
}

fn support_identity(support: &KnowledgeSupportV2) -> KnowledgeSupportIdentityV2 {
    KnowledgeSupportIdentityV2 {
        source_id: support.source_id.clone(),
        source_revision: support.source_revision,
    }
}

#[cfg(test)]
#[path = "incremental_tests.rs"]
mod tests;
