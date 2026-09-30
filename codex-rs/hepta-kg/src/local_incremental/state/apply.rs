use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;

use super::KnowledgeLocalIncrementalStateV3;
use crate::local_incremental::commitment;
use crate::local_incremental::commitment::LocalEntryIdentityV3;
use crate::local_incremental::commitment::LocalTreapNodeV3;
use crate::local_incremental::digest::compute_receipt_digest;
use crate::local_incremental::digest::compute_state_root;
use crate::local_incremental::digest::edge_entry_key;
use crate::local_incremental::digest::edge_value_hash;
use crate::local_incremental::digest::node_entry_key;
use crate::local_incremental::digest::node_value_hash;
use crate::local_incremental::model::KnowledgeLocalIncrementalErrorV3;
use crate::local_incremental::model::KnowledgeLocalMutationReceiptV3;
use crate::local_incremental::model::KnowledgeLocalMutationWorkV3;
use crate::local_incremental::model::KnowledgeLocalStorageDeltaV3;
use crate::local_incremental::state::prepare::planned_node_exists;
use crate::local_incremental::state::prepare::resulting_edge_count;
use crate::local_incremental::state::prepare::resulting_node_count;

impl KnowledgeLocalIncrementalStateV3 {
    /// Revalidate and apply a prepared local mutation.
    ///
    /// Root, counts and endpoint closure are recomputed before any owner state
    /// changes, so a stale or altered plan cannot partially mutate the state.
    pub fn apply_prepared(
        &mut self,
        prepared: KnowledgeLocalStorageDeltaV3,
    ) -> Result<KnowledgeLocalMutationReceiptV3, KnowledgeLocalIncrementalErrorV3> {
        prepared.validate()?;
        if prepared.expected_predecessor_generation != self.generation
            || prepared.expected_predecessor_state_root != self.state_root
        {
            return Err(KnowledgeLocalIncrementalErrorV3::StalePreparedMutation);
        }
        if prepared.graph_profile_digest != self.graph_profile_digest {
            return Err(KnowledgeLocalIncrementalErrorV3::ProfileChanged);
        }
        self.validate_prepared_endpoints(&prepared)?;

        let (tree_root, identity_updates, _) = self.simulate_tree_delta(&prepared)?;
        let observed_node_count =
            resulting_node_count(self, &prepared.remove_node_ids, &prepared.upsert_nodes);
        let observed_edge_count =
            resulting_edge_count(self, &prepared.remove_edge_identities, &prepared.upsert_edges);
        if observed_node_count != prepared.resulting_node_count
            || observed_edge_count != prepared.resulting_edge_count
        {
            return Err(KnowledgeLocalIncrementalErrorV3::ResultingCountMismatch);
        }
        let observed_root = compute_state_root(
            prepared.generation,
            prepared.source_snapshot_digest,
            prepared.generation_vector_digest,
            prepared.graph_profile_digest,
            commitment::root_hash(&tree_root),
            observed_node_count,
            observed_edge_count,
        );
        if observed_root != prepared.resulting_state_root {
            return Err(
                KnowledgeLocalIncrementalErrorV3::ResultingStateRootMismatch {
                    expected: prepared.resulting_state_root,
                    observed: observed_root,
                },
            );
        }

        for identity in &prepared.remove_edge_identities {
            self.remove_edge_indexes(identity);
        }
        for node_id in &prepared.remove_node_ids {
            self.remove_node_indexes(node_id);
        }
        for node in prepared.upsert_nodes.iter().cloned() {
            self.remove_node_indexes(&node.node_id);
            self.insert_node_indexes(node);
        }
        for edge in prepared.upsert_edges.iter().cloned() {
            self.remove_edge_indexes(&edge.identity);
            self.insert_edge_indexes(edge);
        }
        for (key, identity) in identity_updates {
            match identity {
                Some(identity) => {
                    self.identities.insert(key, identity);
                }
                None => {
                    self.identities.remove(&key);
                }
            }
        }
        self.tree_root = tree_root;
        let predecessor_generation = self.generation;
        let predecessor_state_root = self.state_root;
        self.generation = prepared.generation;
        self.source_snapshot_digest = prepared.source_snapshot_digest;
        self.generation_vector_digest = prepared.generation_vector_digest;
        self.graph_profile_digest = prepared.graph_profile_digest;
        self.state_root = observed_root;

        let mut receipt = KnowledgeLocalMutationReceiptV3 {
            predecessor_generation,
            predecessor_state_root,
            generation: self.generation,
            source_snapshot_digest: self.source_snapshot_digest,
            generation_vector_digest: self.generation_vector_digest,
            graph_profile_digest: self.graph_profile_digest,
            state_root: self.state_root,
            node_count: observed_node_count,
            edge_count: observed_edge_count,
            full_rebuild_audit_due: prepared.full_rebuild_audit_due,
            preparation_digest: prepared.preparation_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = compute_receipt_digest(&receipt);
        receipt.validate()?;
        Ok(receipt)
    }

    /// Materialize and validate the complete normative V2 generation.
    pub fn materialize_v2_audit(
        &self,
    ) -> Result<KnowledgeGenerationV2, KnowledgeLocalIncrementalErrorV3> {
        let generation = build_complete_generation(
            self.generation,
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: self.source_snapshot_digest,
                generation_vector_digest: self.generation_vector_digest,
                graph_profile_digest: self.graph_profile_digest,
                complete_source_cut: true,
                nodes: self.nodes.values().cloned().collect(),
                edges: self.edges.values().cloned().collect(),
            },
        )?;
        let rebuilt = Self::from_generation(generation.clone())?;
        if rebuilt.state_root != self.state_root {
            return Err(KnowledgeLocalIncrementalErrorV3::AuditRootMismatch {
                expected: self.state_root,
                observed: rebuilt.state_root,
            });
        }
        Ok(generation)
    }

    pub(super) fn simulate_tree_delta(
        &self,
        prepared: &KnowledgeLocalStorageDeltaV3,
    ) -> Result<
        (
            Option<Arc<LocalTreapNodeV3>>,
            BTreeMap<[u8; 32], Option<LocalEntryIdentityV3>>,
            KnowledgeLocalMutationWorkV3,
        ),
        KnowledgeLocalIncrementalErrorV3,
    > {
        let mut root = self.tree_root.clone();
        let mut identity_updates =
            BTreeMap::<[u8; 32], Option<LocalEntryIdentityV3>>::new();
        let mut work = KnowledgeLocalMutationWorkV3::default();

        for identity in &prepared.remove_edge_identities {
            let entry_identity = LocalEntryIdentityV3::Edge(identity.clone());
            let key = edge_entry_key(identity);
            verify_identity(&self.identities, &identity_updates, key, &entry_identity)?;
            if current_identity(&self.identities, &identity_updates, key).is_some() {
                root = commitment::remove(root, key, &mut work)?;
                work.treap_leaf_updates = work.treap_leaf_updates.saturating_add(1);
            }
            identity_updates.insert(key, None);
        }
        for node_id in &prepared.remove_node_ids {
            let entry_identity = LocalEntryIdentityV3::Node(node_id.clone());
            let key = node_entry_key(node_id);
            verify_identity(&self.identities, &identity_updates, key, &entry_identity)?;
            if current_identity(&self.identities, &identity_updates, key).is_some() {
                root = commitment::remove(root, key, &mut work)?;
                work.treap_leaf_updates = work.treap_leaf_updates.saturating_add(1);
            }
            identity_updates.insert(key, None);
        }
        for node in &prepared.upsert_nodes {
            let entry_identity = LocalEntryIdentityV3::Node(node.node_id.clone());
            let key = node_entry_key(&node.node_id);
            verify_identity(&self.identities, &identity_updates, key, &entry_identity)?;
            root = Some(commitment::insert(
                root,
                key,
                node_value_hash(node),
                &mut work,
            )?);
            work.treap_leaf_updates = work.treap_leaf_updates.saturating_add(1);
            identity_updates.insert(key, Some(entry_identity));
        }
        for edge in &prepared.upsert_edges {
            let entry_identity = LocalEntryIdentityV3::Edge(edge.identity.clone());
            let key = edge_entry_key(&edge.identity);
            verify_identity(&self.identities, &identity_updates, key, &entry_identity)?;
            root = Some(commitment::insert(
                root,
                key,
                edge_value_hash(edge),
                &mut work,
            )?);
            work.treap_leaf_updates = work.treap_leaf_updates.saturating_add(1);
            identity_updates.insert(key, Some(entry_identity));
        }
        Ok((root, identity_updates, work))
    }

    fn validate_prepared_endpoints(
        &self,
        prepared: &KnowledgeLocalStorageDeltaV3,
    ) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
        let remove_node_ids = prepared
            .remove_node_ids
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>();
        let upsert_nodes = prepared
            .upsert_nodes
            .iter()
            .cloned()
            .map(|node| (node.node_id.clone(), node))
            .collect::<BTreeMap<_, _>>();
        for edge in &prepared.upsert_edges {
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
        }
        Ok(())
    }
}

fn verify_identity(
    base: &BTreeMap<[u8; 32], LocalEntryIdentityV3>,
    overlay: &BTreeMap<[u8; 32], Option<LocalEntryIdentityV3>>,
    key: [u8; 32],
    expected: &LocalEntryIdentityV3,
) -> Result<(), KnowledgeLocalIncrementalErrorV3> {
    if current_identity(base, overlay, key)
        .as_ref()
        .is_some_and(|current| current != expected)
    {
        return Err(KnowledgeLocalIncrementalErrorV3::CommitmentKeyCollision);
    }
    Ok(())
}

fn current_identity(
    base: &BTreeMap<[u8; 32], LocalEntryIdentityV3>,
    overlay: &BTreeMap<[u8; 32], Option<LocalEntryIdentityV3>>,
    key: [u8; 32],
) -> Option<LocalEntryIdentityV3> {
    match overlay.get(&key) {
        Some(identity) => identity.clone(),
        None => base.get(&key).cloned(),
    }
}
