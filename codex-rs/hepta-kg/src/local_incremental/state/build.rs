use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;

use super::KnowledgeLocalIncrementalStateV3;
use crate::local_incremental::digest::usize_to_u64;
use crate::local_incremental::model::KnowledgeLocalIncrementalErrorV3;
use crate::local_incremental::model::KnowledgeLocalMutationWorkV3;

impl KnowledgeLocalIncrementalStateV3 {
    /// Build the local commitment and reverse indexes from a complete V2 cut.
    pub fn from_generation(
        generation: KnowledgeGenerationV2,
    ) -> Result<Self, KnowledgeLocalIncrementalErrorV3> {
        generation.validate()?;
        let mut state = Self {
            generation: generation.generation,
            source_snapshot_digest: generation.source_snapshot_digest,
            generation_vector_digest: generation.generation_vector_digest,
            graph_profile_digest: generation.graph_profile_digest,
            nodes: BTreeMap::new(),
            edges: BTreeMap::new(),
            support_to_nodes: BTreeMap::new(),
            support_to_edges: BTreeMap::new(),
            node_to_edges: BTreeMap::new(),
            identities: BTreeMap::new(),
            tree_root: None,
            state_root: Digest32::ZERO,
        };
        let mut work = KnowledgeLocalMutationWorkV3::default();
        for node in generation.nodes {
            state.insert_node(node, &mut work)?;
        }
        for edge in generation.edges {
            state.insert_edge(edge, &mut work)?;
        }
        state.state_root = state.compute_current_state_root();
        Ok(state)
    }

    /// Rebuild from persisted canonical rows and verify their stored V3 root.
    pub fn recover_from_storage(
        generation: Generation,
        source_snapshot_digest: Digest32,
        generation_vector_digest: Digest32,
        graph_profile_digest: Digest32,
        nodes: Vec<KnowledgeNodeV2>,
        edges: Vec<KnowledgeEdgeV2>,
        expected_state_root: Digest32,
    ) -> Result<Self, KnowledgeLocalIncrementalErrorV3> {
        let complete = build_complete_generation(
            generation,
            KnowledgeProjectionInputV2 {
                source_snapshot_digest,
                generation_vector_digest,
                graph_profile_digest,
                complete_source_cut: true,
                nodes,
                edges,
            },
        )?;
        let state = Self::from_generation(complete)?;
        if state.state_root != expected_state_root {
            return Err(KnowledgeLocalIncrementalErrorV3::AuditRootMismatch {
                expected: expected_state_root,
                observed: state.state_root,
            });
        }
        Ok(state)
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn state_root(&self) -> Digest32 {
        self.state_root
    }

    #[must_use]
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    #[must_use]
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    #[must_use]
    pub fn entry_count(&self) -> u64 {
        usize_to_u64(self.nodes.len()).saturating_add(usize_to_u64(self.edges.len()))
    }
}
