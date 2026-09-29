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
            edges: vec![edge("node:a", "node:b", "support:edge:a-b")],
        },
    );
    let Ok(value) = result else {
        panic!("predecessor must build");
    };
    value
}

fn chain_predecessor() -> KnowledgeGenerationV2 {
    let result = build_complete_generation(
        generation(1),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(b"snapshot:chain:1"),
            generation_vector_digest: Digest32::of_bytes(b"vector:chain:1"),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: vec![
                node("node:a", "support:a"),
                node("node:b", "support:b"),
                node("node:c", "support:c"),
            ],
            edges: vec![
                edge("node:a", "node:b", "support:edge:a-b"),
                edge("node:b", "node:c", "support:edge:b-c"),
            ],
        },
    );
    let Ok(value) = result else {
        panic!("chain predecessor must build");
    };
    value
}

fn single_node_predecessor() -> KnowledgeGenerationV2 {
    let result = build_complete_generation(
        generation(1),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(b"snapshot:single:1"),
            generation_vector_digest: Digest32::of_bytes(b"vector:single:1"),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: vec![node("node:a", "support:a")],
            edges: Vec::new(),
        },
    );
    let Ok(value) = result else {
        panic!("single-node predecessor must build");
    };
    value
}

fn delta_for(
    predecessor: &KnowledgeGenerationV2,
    remove_node_ids: Vec<StableId>,
    upsert_nodes: Vec<KnowledgeNodeV2>,
    remove_edge_identities: Vec<KnowledgeEdgeIdentityV2>,
    upsert_edges: Vec<KnowledgeEdgeV2>,
) -> KnowledgeProjectionDeltaV2 {
    KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: predecessor.generation_digest,
        source_snapshot_digest: Digest32::of_bytes(b"snapshot:2"),
        generation_vector_digest: Digest32::of_bytes(b"vector:2"),
        graph_profile_digest: predecessor.graph_profile_digest,
        remove_node_ids,
        upsert_nodes,
        remove_edge_identities,
        upsert_edges,
    }
}

#[test]
fn reverse_index_expands_changed_node_only_to_direct_incident_edges() {
    let predecessor = chain_predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
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
    assert!(!impact.node_ids.contains(&id("node:c")));
    assert!(
        impact
            .edge_identities
            .contains(&edge("node:a", "node:b", "support:unused").identity)
    );
    assert!(
        !impact
            .edge_identities
            .contains(&edge("node:b", "node:c", "support:unused").identity)
    );
}

#[test]
fn incremental_plan_emits_referentially_safe_delta_and_candidate() {
    let predecessor = predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
        panic!("dependency index must build");
    };
    let replacement = node("node:a", "support:a:2");
    let delta = delta_for(
        &predecessor,
        Vec::new(),
        vec![replacement],
        Vec::new(),
        Vec::new(),
    );
    let result = plan_incremental_publication_v2(&predecessor, &index, generation(2), delta);
    let Ok(plan) = result else {
        panic!("incremental plan must build");
    };
    assert_eq!(plan.candidate.generation.get(), 2);
    assert_eq!(
        plan.storage_delta.generation_digest,
        plan.candidate.generation_digest
    );
    assert!(plan.storage_delta.impact.node_ids.contains(&id("node:a")));
    assert_eq!(plan.storage_delta.impact.edge_identities.len(), 1);
    let Ok(rebuilt) = apply_storage_delta_v2(&predecessor, &plan.storage_delta) else {
        panic!("storage delta must reconstruct the candidate");
    };
    assert_eq!(rebuilt, plan.candidate);
}

#[test]
fn node_removal_storage_delta_includes_implicit_incident_edge_removals() {
    let predecessor = chain_predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
        panic!("dependency index must build");
    };
    let removed_node = id("node:b");
    let delta = delta_for(
        &predecessor,
        vec![removed_node.clone()],
        Vec::new(),
        Vec::new(),
        Vec::new(),
    );
    let result = plan_incremental_publication_v2(&predecessor, &index, generation(2), delta);
    let Ok(plan) = result else {
        panic!("node-removal plan must build");
    };

    assert_eq!(plan.storage_delta.remove_node_ids, vec![removed_node.clone()]);
    assert_eq!(plan.storage_delta.remove_edge_identities.len(), 2);
    assert!(plan.storage_delta.upsert_nodes.is_empty());
    assert!(plan.storage_delta.upsert_edges.is_empty());
    assert!(
        plan.candidate
            .nodes
            .iter()
            .all(|node| node.node_id != removed_node)
    );
    assert!(plan.candidate.edges.is_empty());

    let Ok(rebuilt) = apply_storage_delta_v2(&predecessor, &plan.storage_delta) else {
        panic!("storage delta must include every implicit edge removal");
    };
    assert_eq!(rebuilt, plan.candidate);
}

#[test]
fn canonicalized_tombstone_becomes_removal_not_storage_upsert() {
    let predecessor = single_node_predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
        panic!("dependency index must build");
    };
    let mut tombstone = support("support:a:2");
    tombstone.tombstoned = true;
    let tombstoned_node = KnowledgeNodeV2 {
        node_id: id("node:a"),
        node_kind_id: id("kind:test"),
        payload_digest: Digest32::of_bytes(b"payload:node:a"),
        supports: vec![tombstone],
    };
    let delta = delta_for(
        &predecessor,
        Vec::new(),
        vec![tombstoned_node],
        Vec::new(),
        Vec::new(),
    );
    let result = plan_incremental_publication_v2(&predecessor, &index, generation(2), delta);
    let Ok(plan) = result else {
        panic!("tombstone plan must build");
    };

    assert_eq!(plan.storage_delta.remove_node_ids, vec![id("node:a")]);
    assert!(plan.storage_delta.upsert_nodes.is_empty());
    assert!(plan.candidate.nodes.is_empty());
    let Ok(rebuilt) = apply_storage_delta_v2(&predecessor, &plan.storage_delta) else {
        panic!("canonical storage delta must reconstruct tombstone removal");
    };
    assert_eq!(rebuilt, plan.candidate);
}

#[test]
fn storage_delta_digest_tampering_fails_closed() {
    let predecessor = predecessor();
    let Ok(index) = KnowledgeDependencyIndexV2::build(&predecessor) else {
        panic!("dependency index must build");
    };
    let delta = delta_for(
        &predecessor,
        Vec::new(),
        vec![node("node:a", "support:a:2")],
        Vec::new(),
        Vec::new(),
    );
    let Ok(plan) =
        plan_incremental_publication_v2(&predecessor, &index, generation(2), delta)
    else {
        panic!("incremental plan must build");
    };
    let mut tampered = plan.storage_delta;
    tampered.generation_digest = Digest32::of_bytes(b"tampered");

    let result = apply_storage_delta_v2(&predecessor, &tampered);
    let Err(KnowledgeIncrementalErrorV2::StorageDeltaDigestMismatch { .. }) = result else {
        panic!("tampered storage delta digest must fail closed");
    };
}

#[test]
fn periodic_full_rebuild_audit_is_deterministic() {
    assert_eq!(should_run_full_rebuild_audit_v2(generation(20), 10), Ok(true));
    assert_eq!(should_run_full_rebuild_audit_v2(generation(21), 10), Ok(false));
}
