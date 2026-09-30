use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionDeltaV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeSupportV2;
use crate::build_complete_generation;

use super::super::KnowledgeLocalIncrementalStateV3;
use super::super::KnowledgeProjectionDeltaV3;

pub(super) fn id(value: impl Into<String>) -> StableId {
    let value = value.into();
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be stable");
    };
    value
}

pub(super) fn revision(value: u64) -> Revision {
    let Ok(value) = Revision::new(value) else {
        panic!("test revision must be valid");
    };
    value
}

pub(super) fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be valid");
    };
    value
}

pub(super) fn support(value: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(value),
        source_revision: revision(1),
        source_fact_digest: Digest32::of_bytes(format!("fact:{value}").as_bytes()),
        validity_digest: Digest32::of_bytes(format!("valid:{value}").as_bytes()),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

pub(super) fn tombstone(value: &str) -> KnowledgeSupportV2 {
    let mut support = support(value);
    support.tombstoned = true;
    support
}

pub(super) fn node(value: &str, support_id: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(value),
        node_kind_id: id("kind:test"),
        payload_digest: Digest32::of_bytes(format!("payload:{value}").as_bytes()),
        supports: vec![support(support_id)],
    }
}

pub(super) fn edge(source: &str, target: &str, support_id: &str) -> KnowledgeEdgeV2 {
    KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: id(source),
            relation: KnowledgeRelationKindV2::Supports,
            target_node_id: id(target),
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest: Digest32::of_bytes(format!("edge:{source}:{target}").as_bytes()),
        supports: vec![support(support_id)],
    }
}

pub(super) fn chain_generation(number: u64, reverse_input: bool) -> KnowledgeGenerationV2 {
    let mut nodes = vec![
        node("node:a", "support:a"),
        node("node:b", "support:b"),
        node("node:c", "support:c"),
    ];
    let mut edges = vec![
        edge("node:a", "node:b", "support:a-b"),
        edge("node:b", "node:c", "support:b-c"),
    ];
    if reverse_input {
        nodes.reverse();
        edges.reverse();
    }
    let result = build_complete_generation(
        generation(number),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(
                format!("snapshot:{number}").as_bytes(),
            ),
            generation_vector_digest: Digest32::of_bytes(
                format!("vector:{number}").as_bytes(),
            ),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes,
            edges,
        },
    );
    let Ok(value) = result else {
        panic!("chain generation must build");
    };
    value
}

pub(super) fn local_delta(
    state: &KnowledgeLocalIncrementalStateV3,
    remove_node_ids: Vec<StableId>,
    upsert_nodes: Vec<KnowledgeNodeV2>,
    remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    upsert_edges: Vec<KnowledgeEdgeV2>,
) -> KnowledgeProjectionDeltaV3 {
    KnowledgeProjectionDeltaV3 {
        expected_predecessor_generation: state.generation(),
        expected_predecessor_state_root: state.state_root(),
        generation: generation(state.generation().get().saturating_add(1)),
        source_snapshot_digest: Digest32::of_bytes(b"snapshot:next"),
        generation_vector_digest: Digest32::of_bytes(b"vector:next"),
        graph_profile_digest: Digest32::of_bytes(b"profile"),
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}

pub(super) fn v2_delta(
    predecessor: &KnowledgeGenerationV2,
    remove_node_ids: Vec<StableId>,
    upsert_nodes: Vec<KnowledgeNodeV2>,
    remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    upsert_edges: Vec<KnowledgeEdgeV2>,
) -> KnowledgeProjectionDeltaV2 {
    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: Digest32::of_bytes(b"snapshot:next"),
        generation_vector_digest: Digest32::of_bytes(b"vector:next"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}
