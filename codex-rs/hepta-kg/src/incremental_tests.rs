use super::*;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeSupportV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be stable");
    };
    value
}

fn revision() -> Revision {
    let Ok(value) = Revision::new(1) else {
        panic!("test revision must be valid");
    };
    value
}

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation must be valid");
    };
    value
}

fn support(value: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(value),
        source_revision: revision(),
        source_fact_digest: Digest32::of_bytes(value.as_bytes()),
        validity_digest: Digest32::of_bytes(format!("valid:{value}").as_bytes()),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

fn node(value: &str, support_id: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(value),
        node_kind_id: id("kind:test"),
        payload_digest: Digest32::of_bytes(format!("payload:{value}").as_bytes()),
        supports: vec![support(support_id)],
    }
}

fn edge(source: &str, target: &str, support_id: &str) -> KnowledgeEdgeV2 {
    KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: id(source),
            relation: KnowledgeRelationKindV2::Supports,
            target_node_id: id(target),
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest: Digest32::of_bytes(b"edge-validity"),
        supports: vec![support(support_id)],
    }
}

fn predecessor() -> KnowledgeGenerationV2 {
    let result = build_complete_generation(
        generation(1),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(b"snapshot:1"),
            generation_vector_digest: Digest32::of_bytes(b"vector:1"),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: vec![node("node:a", "support:a"), node("node:b", "support:b")],
            edges: vec![edge("node:a", "node:b", "support:edge")],
        },
    );
    let Ok(value) = result else {
        panic!("predecessor must build");
    };
    value
}

#[test]
fn reverse_index_expands_changed_node_to_incident_edges() {
    let generation = predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&generation) else {
        panic!("dependency index must build");
    };
    let impact = compute_impact_closure_v2(
        &index,
        &KnowledgeMutationFrontierV2 {
            changed_node_ids: vec![id("node:a")],
            ..KnowledgeMutationFrontierV2::default()
        },
    );
    assert!(impact.node_ids.contains(&id("node:a")));
    assert!(impact.node_ids.contains(&id("node:b")));
    assert_eq!(impact.edge_identities.len(), 1);
}

#[test]
fn incremental_plan_emits_referentially_safe_delta_and_candidate() {
    let predecessor = predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
        panic!("dependency index must build");
    };
    let replacement = node("node:a", "support:a:2");
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: Digest32::of_bytes(b"snapshot:2"),
        generation_vector_digest: Digest32::of_bytes(b"vector:2"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids: Vec::new(),
        upsert_nodes: vec![replacement],
        remove_edge_identities: Vec::new(),
        upsert_edges: Vec::new(),
    };
    let result = plan_incremental_publication_v2(&predecessor, &index, generation(2), delta);
    let Ok(plan) = result else {
        panic!("incremental plan must build");
    };
    assert_eq!(plan.candidate.generation.get(), 2);
    assert!(plan.storage_delta.impact.node_ids.contains(&id("node:a")));
    assert_eq!(plan.storage_delta.impact.edge_identities.len(), 1);
}

#[test]
fn periodic_full_rebuild_audit_is_deterministic() {
    assert_eq!(should_run_full_rebuild_audit_v2(generation(20), 10), Ok(true));
    assert_eq!(should_run_full_rebuild_audit_v2(generation(21), 10), Ok(false));
}
