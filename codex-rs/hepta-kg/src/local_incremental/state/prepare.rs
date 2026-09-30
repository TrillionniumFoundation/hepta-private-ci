use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeNodeV2;
use crate::MAX_KNOWLEDGE_EDGES_V2;
use crate::MAX_KNOWLEDGE_NODES_V2;

use super::KnowledgeLocalIncrementalStateV3;
use crate::local_incremental::canonical::canonicalize_edge;
use crate::local_incremental::canonical::canonicalize_node;
use crate::local_incremental::canonical::collect_unique;
use crate::local_incremental::commitment;
use crate::local_incremental::digest::compute_preparation_digest;
use crate::local_incremental::digest::compute_state_root;
use crate::local_incremental::digest::usize_to_u64;
use crate::local_incremental::model::KnowledgeLocalIncrementalErrorV3;
use crate::local_incremental::model::KnowledgeLocalMutationWorkV3;
use crate::local_incremental::model::KnowledgeLocalStorageDeltaV3;
use crate::local_incremental::model::KnowledgeProjectionDeltaV3;
use crate::local_incremental::model::ensure_nonzero;

impl KnowledgeLocalIncrementalStateV3 {
    /// Prepare an exact local delta without mutating the owner state.
    ///
    /// The returned plan is bound to the exact predecessor generation and V3
    /// root, so the storage owner can revalidate it inside a short write lock.
    pub fn prepare(
        &self,
        delta: KnowledgeProjectionDeltaV3,
        full_rebuild_audit_interval: u64,
    ) -> Result<KnowledgeLocalStorageDeltaV3, KnowledgeLocalIncrementalErrorV3> {
        if full_rebuild_audit_interval == 0 {
            return Err(KnowledgeLocalIncrementalErrorV3::InvalidAuditInterval);
        }
        if delta.expected_predecessor_generation != self.generation
            || delta.expected_predecessor_state_root != self.state_root
        {
            return Err(KnowledgeLocalIncrementalErrorV3::StalePreparedMutation);
        }
        if self.generation.next().ok() != Some(delta.generation) {
            return Err(KnowledgeLocalIncrementalErrorV3::InvalidPredecessor);
        }
        if delta.graph_profile_digest != self.graph_profile_digest {
            return Err(KnowledgeLocalIncrementalErrorV3::ProfileChanged);
        }
        ensure_nonzero("local_source_snapshot", delta.source_snapshot_digest)?;
        ensure_nonzero("local_generation_vector", delta.generation_vector_digest)?;
        ensure_nonzero("local_graph_profile", delta.graph_profile_digest)?;

        let mut work = KnowledgeLocalMutationWorkV3::default();
        let mut remove_node_ids = collect_unique(delta.remove_node_ids)?;
        let mut upsert_nodes = BTreeMap::<StableId, KnowledgeNodeV2>::new();
        let mut seen_upsert_nodes = BTreeSet::new();
        for node in delta.upsert_nodes {
            let node_id = node.node_id.clone();
            if !seen_upsert_nodes.insert(node_id.clone()) {
                return Err(KnowledgeLocalIncrementalErrorV3::DuplicateDeltaIdentity);
            }
            work.supports_inspected = work
                .supports_inspected
                .saturating_add(usize_to_u64(node.supports.len()));
            match canonicalize_node(node)? {
                Some(node) => {
                    upsert_nodes.insert(node.node_id.clone(), node);
                }
                None => {
                    remove_node_ids.insert(node_id);
                }
            }
        }

        let mut remove_edge_identities = collect_unique(delta.remove_edge_identities)?;
        for node_id in &remove_node_ids {
            if self.nodes.contains_key(node_id) {
                work.predecessor_nodes_read = work.predecessor_nodes_read.saturating_add(1);
            }
            if let Some(incident) = self.node_to_edges.get(node_id) {
                work.predecessor_edges_read = work
                    .predecessor_edges_read
                    .saturating_add(usize_to_u64(incident.len()));
                remove_edge_identities.extend(incident.iter().cloned());
            }
        }

        let mut upsert_edges = BTreeMap::<KnowledgeEdgeIdentityV2, KnowledgeEdgeV2>::new();
        let mut seen_upsert_edges = BTreeSet::new();
        for edge in delta.upsert_edges {
            let identity = edge.identity.clone();
            if !seen_upsert_edges.insert(identity.clone()) {
                return Err(KnowledgeLocalIncrementalErrorV3::DuplicateDeltaIdentity);
            }
            work.supports_inspected = work
                .supports_inspected
                .saturating_add(usize_to_u64(edge.supports.len()));
            match canonicalize_edge(edge)? {
                Some(edge) => {
                    if !planned_node_exists(
                        self,
                        &remove_node_ids,
                        &upsert_nodes,
                        &edge.identity.source_node_id,
                    ) || !planned_node_exists(
                        self,
                        &remove_node_ids,
                        &upsert_nodes,
                        &edge.identity.target_node_id,
                    ) {
                        return Err(KnowledgeGenerationErrorV2::UnknownEdgeNode.into());
                    }
                    upsert_edges.insert(edge.identity.clone(), edge);
                }
                None => {
                    remove_edge_identities.insert(identity);
                }
            }
        }

        let remove_node_ids = remove_node_ids.into_iter().collect::<Vec<_>>();
        let remove_edge_identities = remove_edge_identities.into_iter().collect::<Vec<_>>();
        let upsert_nodes = upsert_nodes.into_values().collect::<Vec<_>>();
        let upsert_edges = upsert_edges.into_values().collect::<Vec<_>>();
        let resulting_node_count =
            resulting_node_count(self, &remove_node_ids, &upsert_nodes);
        let resulting_edge_count =
            resulting_edge_count(self, &remove_edge_identities, &upsert_edges);
        if resulting_node_count > usize_to_u64(MAX_KNOWLEDGE_NODES_V2) {
            return Err(KnowledgeGenerationErrorV2::NodeLimitExceeded.into());
        }
        if resulting_edge_count > usize_to_u64(MAX_KNOWLEDGE_EDGES_V2) {
            return Err(KnowledgeGenerationErrorV2::EdgeLimitExceeded.into());
        }

        let mut prepared = KnowledgeLocalStorageDeltaV3 {
            expected_predecessor_generation: self.generation,
            expected_predecessor_state_root: self.state_root,
            generation: delta.generation,
            source_snapshot_digest: delta.source_snapshot_digest,
            generation_vector_digest: delta.generation_vector_digest,
            graph_profile_digest: delta.graph_profile_digest,
            remove_edge_identities,
            remove_node_ids,
            upsert_nodes,
            upsert_edges,
            resulting_state_root: Digest32::ZERO,
            resulting_node_count,
            resulting_edge_count,
            full_rebuild_audit_due: delta
                .generation
                .get()
                .is_multiple_of(full_rebuild_audit_interval),
            work,
            preparation_digest: Digest32::ZERO,
        };
        let (tree_root, _, tree_work) = self.simulate_tree_delta(&prepared)?;
        prepared.work.treap_leaf_updates = tree_work.treap_leaf_updates;
        prepared.work.treap_nodes_rehashed = tree_work.treap_nodes_rehashed;
        prepared.resulting_state_root = compute_state_root(
            prepared.generation,
            prepared.source_snapshot_digest,
            prepared.generation_vector_digest,
            prepared.graph_profile_digest,
            commitment::root_hash(&tree_root),
            prepared.resulting_node_count,
            prepared.resulting_edge_count,
        );
        prepared.preparation_digest = compute_preparation_digest(&prepared);
        prepared.validate()?;
        Ok(prepared)
    }
}

pub(super) fn planned_node_exists(
    state: &KnowledgeLocalIncrementalStateV3,
    remove_node_ids: &BTreeSet<StableId>,
    upsert_nodes: &BTreeMap<StableId, KnowledgeNodeV2>,
    node_id: &StableId,
) -> bool {
    if upsert_nodes.contains_key(node_id) {
        true
    } else if remove_node_ids.contains(node_id) {
        false
    } else {
        state.nodes.contains_key(node_id)
    }
}

pub(super) fn resulting_node_count(
    state: &KnowledgeLocalIncrementalStateV3,
    remove_node_ids: &[StableId],
    upsert_nodes: &[KnowledgeNodeV2],
) -> u64 {
    let mut touched = remove_node_ids.iter().cloned().collect::<BTreeSet<_>>();
    touched.extend(upsert_nodes.iter().map(|node| node.node_id.clone()));
    let upserts = upsert_nodes
        .iter()
        .map(|node| node.node_id.clone())
        .collect::<BTreeSet<_>>();
    let mut count = usize_to_u64(state.nodes.len());
    for node_id in touched {
        let before = state.nodes.contains_key(&node_id);
        let after = upserts.contains(&node_id);
        match (before, after) {
            (true, false) => count = count.saturating_sub(1),
            (false, true) => count = count.saturating_add(1),
            (true, true) | (false, false) => {}
        }
    }
    count
}

pub(super) fn resulting_edge_count(
    state: &KnowledgeLocalIncrementalStateV3,
    remove_edge_identities: &[KnowledgeEdgeIdentityV2],
    upsert_edges: &[KnowledgeEdeV2],
) -> u64 {
    let mut touched = remove_edge_identities
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    touched.extend(upsert_edges.iter().map(|edge| edge.identity.clone()));
    let upserts = upsert_edges
        .iter()
        .map(|edge| edge.identity.clone())
        .collect::<BTreeSet<_>>();
    let mut count = usize_to_u64(state.edges.len());
    for identity in touched {
        let before = state.edges.contains_key(&identity);
        let after = upserts.contains(&identity);
        match (before, after) {
            (true, false) => count = count.saturating_sub(1),
            (false, true) => count = count.saturating_add(1),
            (true, true) | (false, false) => {}
        }
    }
    count
}
