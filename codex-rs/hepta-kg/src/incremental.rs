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
    support_to_edges:
        BTreeMap<KnowledgeSupportIdentityV2, BTreeSet<KnowledgeEdgeIdentityV2>>,
    node_to_edges: BTreeMap<StableId, BTreeSet<KnowledgeEdgeIdentityV2>>,
}

impl KnowledgeDependencyIndexV2 {
    pub fn build(
        generation: &KnowledgeGenerationV2,
    ) -> Result<Self, KnowledgeGenerationErrorV2> {
        generation.validate()?;
        let mut support_to_nodes = BTreeMap::<
            KnowledgeSupportIdentityV2,
            BTreeSet<StableId>,
        >::new();
        let mut support_to_edges = BTreeMap::<
            KnowledgeSupportIdentityV2,
            BTreeSet<KnowledgeEdgeIdentityV2>,
        >::new();
        let mut node_to_edges =
            BTreeMap::<StableId, BTreeSet<KnowledgeEdgeIdentityV2>>::new();
        for node in &generation.nodes {
            for support in &node.supports {
                support_to_nodes
                    .entry(KnowledgeSupportIdentityV2 {
                        source_id: support.source_id.clone(),
                        source_revision: support.source_revision,
                    })
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
                    .entry(KnowledgeSupportIdentityV2 {
                        source_id: support.source_id.clone(),
                        source_revision: support.source_revision,
                    })
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
    loop {
        let previous_node_count = closure.node_ids.len();
        let previous_edge_count = closure.edge_identities.len();
        for node_id in closure.node_ids.clone() {
            if let Some(edges) = index.node_to_edges.get(&node_id) {
                closure.edge_identities.extend(edges.iter().cloned());
            }
        }
        for edge in closure.edge_identities.clone() {
            closure.node_ids.insert(edge.source_node_id);
            closure.node_ids.insert(edge.target_node_id);
        }
        if previous_node_count == closure.node_ids.len()
            && previous_edge_count == closure.edge_identities.len()
        {
            break;
        }
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
            | Self::FullRebuildDiverged { .. }
            | Self::InvalidAuditInterval => None,
        }
    }
}

pub fn plan_incremental_publication_v2(
    predecessor: &KnowledgeGenerationV2,
    index: &KnowledgeDependencyIndexV2,
    generation: Generation,
    delta: KnowledgeProjectionDeltaV2,
) -> Result<KnowledgeIncrementalPlanV2, KnowledgeIncrementalErrorV2> {
    if index.generation_digest != predecessor.generation_digest {
        return Err(KnowledgeIncrementalErrorV2::IndexGenerationMismatch);
    }
    let frontier = frontier_from_delta(&delta);
    let impact = compute_impact_closure_v2(index, &frontier);
    let storage_delta = KnowledgeStorageDeltaV2 {
        expected_predecessor_digest: delta.expected_predecessor_digest,
        generation,
        source_snapshot_digest: delta.source_snapshot_digest,
        generation_vector_digest: delta.generation_vector_digest,
        graph_profile_digest: delta.graph_profile_digest,
        remove_edge_identities: canonical_values(delta.remove_edge_identities.clone()),
        remove_node_ids: canonical_values(delta.remove_node_ids.clone()),
        upsert_nodes: canonical_nodes(delta.upsert_nodes.clone()),
        upsert_edges: canonical_edges(delta.upsert_edges.clone()),
        impact,
    };
    let candidate = apply_incremental_delta(predecessor, generation, delta)?;
    Ok(KnowledgeIncrementalPlanV2 {
        storage_delta,
        candidate,
    })
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
    Ok(generation.get() % every_generations == 0)
}

fn frontier_from_delta(delta: &KnowledgeProjectionDeltaV2) -> KnowledgeMutationFrontierV2 {
    let mut changed_supports = Vec::new();
    for node in &delta.upsert_nodes {
        for support in &node.supports {
            changed_supports.push(KnowledgeSupportIdentityV2 {
                source_id: support.source_id.clone(),
                source_revision: support.source_revision,
            });
        }
    }
    for edge in &delta.upsert_edges {
        for support in &edge.supports {
            changed_supports.push(KnowledgeSupportIdentityV2 {
                source_id: support.source_id.clone(),
                source_revision: support.source_revision,
            });
        }
    }
    KnowledgeMutationFrontierV2 {
        changed_supports: canonical_values(changed_supports),
        changed_node_ids: canonical_values(
            delta
                .remove_node_ids
                .iter()
                .cloned()
                .chain(delta.upsert_nodes.iter().map(|node| node.node_id.clone()))
                .collect(),
        ),
        changed_edge_identities: canonical_values(
            delta
                .remove_edge_identities
                .iter()
                .cloned()
                .chain(delta.upsert_edges.iter().map(|edge| edge.identity.clone()))
                .collect(),
        ),
    }
}

fn canonical_values<T: Ord>(values: Vec<T>) -> Vec<T> {
    values.into_iter().collect::<BTreeSet<_>>().into_iter().collect()
}

fn canonical_nodes(nodes: Vec<KnowledgeNodeV2>) -> Vec<KnowledgeNodeV2> {
    nodes
        .into_iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>()
        .into_values()
        .collect()
}

fn canonical_edges(edges: Vec<KnowledgeEdgeV2>) -> Vec<KnowledgeEdgeV2> {
    edges
        .into_iter()
        .map(|edge| (edge.identity.clone(), edge))
        .collect::<BTreeMap<_, _>>()
        .into_values()
        .collect()
}

#[cfg(test)]
#[path = "incremental_tests.rs"]
mod tests;
