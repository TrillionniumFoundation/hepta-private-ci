use codex_hepta_types::Digest32;

use super::fixtures::chain_generation;
use super::fixtures::generation;
use super::fixtures::local_delta;
use super::fixtures::node;
use super::super::KnowledgeLocalIncrementalErrorV3;
use super::super::KnowledgeLocalIncrementalStateV3;

#[test]
fn stale_prepared_mutation_fails_without_state_drift() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor);
    let Ok(mut state) = state_result else {
        panic!("local state must build");
    };
    let first_result = state.prepare(
        local_delta(
            &state,
            Vec::new(),
            vec![node("node:a", "support:a:first")],
            Vec::new(),
            Vec::new(),
        ),
        16,
    );
    let Ok(first) = first_result else {
        panic!("first local mutation must prepare");
    };
    let second_result = state.prepare(
        local_delta(
            &state,
            Vec::new(),
            vec![node("node:a", "support:a:second")],
            Vec::new(),
            Vec::new(),
        ),
        16,
    );
    let Ok(second) = second_result else {
        panic!("second local mutation must prepare");
    };
    let first_apply_result = state.apply_prepared(first);
    if first_apply_result.is_err() {
        panic!("first local mutation must apply");
    }
    let committed_root = state.state_root();
    let stale_result = state.apply_prepared(second);
    assert_eq!(
        stale_result,
        Err(KnowledgeLocalIncrementalErrorV3::StalePreparedMutation)
    );
    assert_eq!(state.state_root(), committed_root);
    assert_eq!(state.generation(), generation(2));
}

#[test]
fn recovery_rejects_wrong_persisted_root() {
    let predecessor = chain_generation(1, false);
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor.clone());
    let Ok(state) = state_result else {
        panic!("local state must build");
    };
    let recovered_result = KnowledgeLocalIncrementalStateV3::recover_from_storage(
        predecessor.generation,
        predecessor.source_snapshot_digest,
        predecessor.generation_vector_digest,
        predecessor.graph_profile_digest,
        predecessor.nodes.clone(),
        predecessor.edges.clone(),
        state.state_root(),
    );
    let Ok(recovered) = recovered_result else {
        panic!("matching persisted root must recover");
    };
    assert_eq!(recovered.state_root(), state.state_root());

    let tampered_result = KnowledgeLocalIncrementalStateV3::recover_from_storage(
        predecessor.generation,
        predecessor.source_snapshot_digest,
        predecessor.generation_vector_digest,
        predecessor.graph_profile_digest,
        predecessor.nodes,
        predecessor.edges,
        Digest32::of_bytes(b"wrong-root"),
    );
    let Err(KnowledgeLocalIncrementalErrorV3::AuditRootMismatch { .. }) = tampered_result else {
        panic!("wrong persisted root must fail closed");
    };
}

#[test]
fn local_root_is_independent_of_complete_input_order() {
    let ordered = chain_generation(1, false);
    let reversed = chain_generation(1, true);
    assert_eq!(ordered, reversed);
    let ordered_state_result = KnowledgeLocalIncrementalStateV3::from_generation(ordered);
    let Ok(ordered_state) = ordered_state_result else {
        panic!("ordered state must build");
    };
    let reversed_state_result = KnowledgeLocalIncrementalStateV3::from_generation(reversed);
    let Ok(reversed_state) = reversed_state_result else {
        panic!("reversed state must build");
    };
    assert_eq!(ordered_state.state_root(), reversed_state.state_root());
}
