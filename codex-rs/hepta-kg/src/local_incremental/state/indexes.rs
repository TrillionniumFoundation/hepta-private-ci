use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeNodeV2;

use super::KnowledgeLocalIncrementalStateV3;
use crate::local_incremental::canonical::support_identity;
use crate::local_incremental::commitment;
use crate::local_incremental::commitment::LocalEntryIdentityV3;
use crate::local_incremental::digest::compute_state_root;
use crate::local_incremental::digest::edge_entry_key;
use crate::local_incremental::digest::edge_value_hash;
use crate::local_incremental::digest::node_entry_key;
use crate::local_incremental::digest::node_value_hash;
use crate::local_incremental::digest::usize_to_u64;
use crate::local_incremental::model::KnowledgeLocalIncrementalErrorV3;
use crate::local_incremental::model::KnowledgeLocalMutationWorkV3;

impl KnowledgeLocalIncrementalStateV3 {
    pub(super) fn insert_node(
        &mut self,
        node: KnowledgeNodeV2,
        work: &mut KnowledgeLocalMutationWorkV3,
    ) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
        let identity = LocalEntryIdentityV3::Node(node.node_id.clone());
        let key = node_entry_key(&node.node_id);
        if self
            .identities
            .get(&key)
            .is_some_and(|existing| existing != &identity)
        {
            return Err(KnowledgeLocalIncrementalErrorV3::CommitmentKeyCollision);
        }
        self.tree_root = Some(commitment::insert(
            self.tree_root.clone(),
            key,
            node_value_hash(&node),
            work,
        )?);
        self.identities.insert(key, identity);
        self.insert_node_indexes(node);
        Ok(())
    }

    pub(super) fn insert_edge(
        &mut self,
        edge: KnowledgeEdgeV2,
        work: &mut KnowledgeLocalMutationWorkV3,
    ) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
        let identity = LocalEntryIdentityV3::Edge(edge.identity.clone());
        let key = edge_entry_key(&edge.identity);
        if self
            .identities
            .get(&key)
            .is_some_and(|existing| existing != &identity)
        {
            return Err(KnowledgeLocalIncrementalErrorV3::CommitmentKeyCollision);
        }
        self.tree_root = Some(commitment::insert(
            self.tree_root.clone(),
            key,
            edge_value_hash(&edge),
            work,
        )?);
        self.identities.insert(key, identity);
        self.insert_edge_indexes(edge);
        Ok(())
    }

    pub(super) fn insert_node_indexes(&mut self, node: KnowledgeNodeV2) {
        for support in &node.supports {
            self.support_to_nodes
                .entry(support_identity(support))
                .or_default()
                .insert(node.node_id.clone());
        }
        self.nodes.insert(node.node_id.clone(), node);
    }

    pub(super) fn insert_edge_indexes(&mut self, edge: KnowledgeEdgeV2) {
        self.node_to_edges
            .entry(edge.identity.source_node_id.clone())
            .or_default()
            .insert(edge.identity.clone());
        self.node_to_edges
            .entry(edge.identity.target_node_id.clone())
            .or_default()
            .insert(edge.identity.clone());
        for support in &edge.supports {
            self.support_to_edges
                .entry(support_identity(support))
                .or_default()
                .insert(edge.identity.clone());
        }
        self.edges.insert(edge.identity.clone(), edge);
    }

    pub(super) fn remove_node_indexes(&mut self, node_id: &StableId) {
        let Some(node) = self.nodes.remove(node_id) else {
            return;
        };
        for support in &node.supports {
            remove_set_value(
                &mut self.support_to_nodes,
                &support_identity(support),
                node_id,
            );
        }
        self.node_to_edges.remove(node_id);
    }

    pub(super) fn remove_edge_indexes(&mut self, identity: &KnowledgeEdgeIdentityV2) {
        let Some(edge) = self.edges.remove(identity) else {
            return;
        };
        remove_set_value(
            &mut self.node_to_edges,
            &edge.identity.source_node_id,
            identity,
        );
        remove_set_value(
            &mut self.node_to_edges,
            &edge.identity.target_node_id,
            identity,
        );
        for support in &edge.supports {
            remove_set_value(
                &mut self.support_to_edges,
                &support_identity(support),
                identity,
            );
        }
    }

    pub(super) fn compute_current_state_root(&self) -> Digest32 {
        compute_state_root(
            self.generation,
            self.source_snapshot_digest,
            self.generation_vector_digest,
            self.graph_profile_digest,
            commitment::root_hash(&self.tree_root),
            usize_to_u64(self.nodes.len()),
            usize_to_u64(self.edges.len()),
        )
    }
}

fn remove_set_value<K, V>(map: &mut BTreeMap<K, BTreeSet<V>>, key: &K, value: &V)
where
    K: Ord,
    V: Ord,
{
    let remove_key = if let Some(values) = map.get_mut(key) {
        values.remove(value);
        values.is_empty()
    } else {
        false
    };
    if remove_key {
        map.remove(key);
    }
}
