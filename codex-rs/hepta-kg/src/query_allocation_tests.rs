use super::*;

#[test]
fn empty_relation_results_do_not_reserve_slots_for_unrelated_generation_edges() {
    let nodes = (0..128)
        .map(|index| node(&format!("n{index:03}"), "payload"))
        .collect();
    let edges = (0..127)
        .map(|index| {
            let mut edge = edge(
                &format!("n{index:03}"),
                &format!("n{:03}", index + 1),
                KnowledgeRelationKindV2::Supports,
                &format!("e{index:03}"),
            );
            edge.supports[0].valid_to_unix_seconds = Some(100);
            edge
        })
        .collect();
    let graph = build_complete_generation(generation(1), input(nodes, edges)).expect("chain");
    let verified = VerifiedKnowledgeGenerationV2::new(graph.clone()).expect("view");
    for (seed_node_ids, relation_kinds, valid_at_unix_seconds) in [
        (Vec::new(), Vec::new(), None),
        (vec![id("node:unknown")], Vec::new(), None),
        (
            vec![id("node:n064")],
            vec![KnowledgeRelationKindV2::Causes],
            None,
        ),
        (vec![id("node:n064")], Vec::new(), Some(100)),
    ] {
        let query = KnowledgeRelationQueryV2 {
            query_id: id("query:empty-result-allocation"),
            generation_digest: graph.generation_digest,
            seed_node_ids,
            relation_kinds,
            valid_at_unix_seconds,
            maximum_edges: MAX_KNOWLEDGE_EDGES_V2 as u32,
        };
        let reference = query_relations(&graph, query.clone()).expect("reference");
        let indexed = verified.query_relations(query).expect("indexed");

        assert_eq!(reference, indexed);
        // Retained capacity is an observable resource property of the returned
        // Vec. No-match requests must not allocate graph-sized result storage.
        assert_eq!((reference.edges.len(), reference.edges.capacity()), (0, 0));
    }
}
