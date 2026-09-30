use codex_hepta_types::Digest32;

use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;

use super::fixtures::generation;
use super::fixtures::local_delta;
use super::fixtures::node;
use super::super::KnowledgeLocalIncrementalStateV3;

#[test]
fn one_entry_update_does_not_scan_a_large_generation() {
    let mut nodes = Vec::new();
    for index in 0..2_048_u64 {
        let node_id = format!("node:{index:04}");
        let support_id = format!("support:{index:04}");
        nodes.push(node(&node_id, &support_id));
    }
    let generation_result = build_complete_generation(
        generation(1),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(b"snapshot:large"),
            generation_vector_digest: Digest32::of_bytes(b"vector:large"),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes,
            edges: Vec::new(),
        },
    );
    let Ok(predecessor) = generation_result else {
        panic!("large generation must build");
    };
    let state_result = KnowledgeLocalIncrementalStateV3::from_generation(predecessor);
    let Ok(state) = state_result else {
        panic!("large local state must build");
    };
    let prepare_result = state.prepare(
        local_delta(
            &state,
            Vec::new(),
            vec![node("node:1024", "support:1024:replacement")],
            Vec::new(),
            Vec::new(),
        ),
        1_024,
    );
    let Ok(prepared) = prepare_result else {
        panic!("large local mutation must prepare");
    };
    assert_eq!(prepared.work.full_entries_scanned, 0);
    assert_eq!(prepared.work.predecessor_nodes_read, 0);
    assert_eq!(prepared.work.predecessor_edges_read, 0);
    assert_eq!(prepared.work.treap_leaf_updates, 1);
    assert!(prepared.work.treap_nodes_rehashed < state.entry_count());
    assert_eq!(prepared.resulting_node_count, 2_048);
}
