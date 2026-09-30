use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeNodeV2;
use crate::apply_incremental_delta;

use super::fixtures::chain_generation;
use super::fixtures::edge;
use super::fixtures::generation;
use super::fixtures::id;
use super::fixtures::local_delta;
use super::fixtures::node;
use super::fixtures::tombstone;
use super::fixtures::v2_delta;
use super::super::KnowledgeLocalIncrementalErrorV3;
use super::super::KnowledgeLocalIncrementalStateV3;

#[test]
fn local_frontier_plan_matches_complete_v2_oracle() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor.clone());
    let Ok(mut state) = state_result else {
        panic!("local state must build");
    };
    let replacement = node("node:a", "support:a:replacement");
    let added_edge = edge("node:a", "node:c", "support:a-c");
    let prepare_result = state.prepare(
        local_delta(
            &state,
            Vec::new(),
            vec![replacement.clone()],
            Vec::new(),
            vec![added_edge.clone()],
        ),
        2,
    );
    let Ok(prepared) = prepare_result else {
        panic!("local mutation must prepare");
    };
    assert_eq!(prepared.resulting_node_count, 3);
    assert_eq!(prepared.resulting_edge_count, 3);
    assert_eq!(prepared.work.full_entries_scanned, 0);
    assert_eq!(prepared.work.treap_leaf_updates, 2);
    assert!(prepared.work.treap_nodes_rehashed >= 2);
    assert!(prepared.full_rebuild_audit_due);

    let expected_result = apply_incremental_delta(
        &predecessor,
        generation(2),
        v2_delta(
            &predecessor,
            Vec::new(),
            vec![replacement],
            Vec::new(),
            vec![added_edge],
        ),
    );
    let Ok(expected) = expected_result else {
        panic!("complete V2 oracle must apply");
    };
    let receipt_result = state.apply_prepared(prepared);
    let Ok(receipt) = receipt_result else {
        panic!("local mutation must apply");
    };
    assert_eq!(receipt.generation, generation(2));
    assert_eq!(receipt.node_count, 3);
    assert_eq!(receipt.edge_count, 3);
    assert!(receipt.full_rebuild_audit_due);
    assert_eq!(receipt.validate(), Ok(()));

    let audit_result = state.materialize_v2_audit();
    let Ok(audit) = audit_result else {
        panic!("complete V2 audit must succeed");
    };
    assert_eq!(audit, expected);
}

#[test]
fn node_removal_closes_only_direct_incident_frontier() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor.clone());
    let Ok(mut state) = state_result else {
        panic!("local state must build");
    };
    let prepare_result = state.prepare(
        local_delta(
            &state,
            vec![id("node:b")],
            Vec::new(),
            Vec::new(),
            Vec::new(),
        ),
        8,
    );
    let Ok(prepared) = prepare_result else {
        panic!("node removal must prepare");
    };
    assert_eq!(prepared.remove_node_ids, vec![id("node:b")]);
    assert_eq!(prepared.remove_edge_identities.len(), 2);
    assert_eq!(prepared.resulting_node_count, 2);
    assert_eq!(prepared.resulting_edge_count, 0);
    assert_eq!(prepared.work.predecessor_nodes_read, 1);
    assert_eq!(prepared.work.predecessor_edges_read, 2);
    assert_eq!(prepared.work.full_entries_scanned, 0);

    let expected_result = apply_incremental_delta(
        &predecessor,
        generation(2),
        v2_delta(
            &predecessor,
            vec![id("node:b")],
            Vec::new(),
            Vec::new(),
            Vec::new(),
        ),
    );
    let Ok(expected) = expected_result else {
        panic!("complete V2 removal must apply");
    };
    let apply_result = state.apply_prepared(prepared);
    if apply_result.is_err() {
        panic!("local removal must apply");
    }
    let audit_result = state.materialize_v2_audit();
    let Ok(audit) = audit_result else {
        panic!("local removal must audit");
    };
    assert_eq!(audit, expected);
}

#[test]
fn tombstoned_upsert_becomes_node_and_incident_edge_removal() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor);
    let Ok(state) = state_result else {
        panic!("local state must build");
    };
    let tombstoned = KnowledgeNodeV2 {
        node_id: id("node:b"),
        node_kind_id: id("kind:test"),
        payload_digest: codex_hepta_types::Digest32::of_bytes(b"payload:node:b"),
        supports: vec![tombstone("support:b:withdrawn")],
    };
    let prepare_result = state.prepare(
        local_delta(
            &state,
            Vec::new(),
            vec![tombstoned],
            Vec::new(),
            Vec::new(),
        ),
        32,
    );
    let Ok(prepared) = prepare_result else {
        panic!("tombstone must prepare");
    };
    assert_eq!(prepared.remove_node_ids, vec![id("node:b")]);
    assert!(prepared.upsert_nodes.is_empty());
    assert_eq!(prepared.remove_edge_identities.len(), 2);
}

#[test]
fn edge_upsert_cannot_target_a_removed_endpoint() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor);
    let Ok(state) = state_result else {
        panic!("local state must build");
    };
    let prepare_result = state.prepare(
        local_delta(
            &state,
            vec![id("node:b")],
            Vec::new(),
            Vec::new(),
            vec![edge("node:a", "node:b", "support:new-a-b")],
        ),
        32,
    );
    assert_eq!(
        prepare_result,
        Err(KnowledgeLocalIncrementalErrorV3::Generation(
            KnowledgeGenerationErrorV2::UnknownEdgeNode
        ))
    );
}
