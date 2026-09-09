use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw)
        .unwrap_or_else(|error| panic!("valid probability: {error}"))
}

fn support(label: &str, tombstoned: bool) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("source:{label}")),
        source_revision: revision(1),
        source_fact_digest: digest(&format!("fact:{label}")),
        validity_digest: digest(&format!("validity:{label}")),
        tombstoned,
    }
}

fn node(label: &str, payload: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(&format!("node:{label}")),
        node_kind_id: id("kind:entity"),
        payload_digest: digest(payload),
        supports: vec![support(label, false)],
    }
}

fn edge(
    source: &str,
    target: &str,
    relation: KnowledgeRelationKindV2,
    support_label: &str,
) -> KnowledgeEdgeV2 {
    KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: id(&format!("node:{source}")),
            relation,
            target_node_id: id(&format!("node:{target}")),
        },
        confidence: probability(1_u64 << 31),
        validity_digest: digest("edge-validity"),
        supports: vec![support(support_label, false)],
    }
}

fn input(nodes: Vec<KnowledgeNodeV2>, edges: Vec<KnowledgeEdgeV2>) -> KnowledgeProjectionInputV2 {
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest("snapshot:1"),
        generation_vector_digest: digest("vector:1"),
        graph_profile_digest: digest("profile:1"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

#[test]
fn incremental_and_full_rebuilds_are_semantically_equal() {
    let first = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a-v1"), node("b", "b-v1")],
            vec![edge(
                "a",
                "b",
                KnowledgeRelationKindV2::Supports,
                "edge-ab-v1",
            )],
        ),
    )
    .unwrap_or_else(|error| panic!("valid first generation: {error}"));

    let mut updated_edge = edge(
        "a",
        "b",
        KnowledgeRelationKindV2::Supports,
        "edge-ab-v2",
    );
    updated_edge.confidence = probability(3_u64 << 30);
    let delta = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: first.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: digest("profile:1"),
        remove_node_ids: Vec::new(),
        upsert_nodes: vec![node("b", "b-v2")],
        remove_edge_identities: Vec::new(),
        upsert_edges: vec![updated_edge.clone()],
    };
    let incremental = apply_incremental_delta(&first, generation(2), delta)
        .unwrap_or_else(|error| panic!("valid incremental generation: {error}"));

    let full = build_complete_generation(
        generation(2),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("snapshot:2"),
            generation_vector_digest: digest("vector:2"),
            graph_profile_digest: digest("profile:1"),
            complete_source_cut: true,
            nodes: vec![node("a", "a-v1"), node("b", "b-v2")],
            edges: vec![updated_edge],
        },
    )
    .unwrap_or_else(|error| panic!("valid full generation: {error}"));

    assert_eq!(incremental, full);
}

#[test]
fn tombstoning_last_edge_support_removes_relation() {
    let mut removed = edge(
        "a",
        "b",
        KnowledgeRelationKindV2::Contradicts,
        "edge-ab",
    );
    removed.supports[0].tombstoned = true;
    let generation = build_complete_generation(
        generation(1),
        input(vec![node("a", "a"), node("b", "b")], vec![removed]),
    )
    .unwrap_or_else(|error| panic!("valid deletion projection: {error}"));
    assert!(generation.edges.is_empty());
}

#[test]
fn incomplete_generation_and_wrong_predecessor_cannot_publish() {
    let mut incomplete = input(vec![node("a", "a")], Vec::new());
    incomplete.complete_source_cut = false;
    assert_eq!(
        build_complete_generation(generation(1), incomplete),
        Err(KnowledgeGenerationErrorV2::IncompleteSourceCut)
    );

    let candidate = build_complete_generation(
        generation(2),
        input(vec![node("a", "a")], Vec::new()),
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    assert_eq!(
        publish_generation(None, &candidate),
        Err(KnowledgeGenerationErrorV2::InvalidPredecessor)
    );
}

#[test]
fn publication_is_predecessor_bound_and_query_is_generation_bound() {
    let first = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b")],
            vec![edge(
                "a",
                "b",
                KnowledgeRelationKindV2::Causes,
                "edge-ab",
            )],
        ),
    )
    .unwrap_or_else(|error| panic!("valid first: {error}"));
    let second = build_complete_generation(
        generation(2),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("snapshot:2"),
            generation_vector_digest: digest("vector:2"),
            graph_profile_digest: digest("profile:1"),
            complete_source_cut: true,
            nodes: first.nodes.clone(),
            edges: first.edges.clone(),
        },
    )
    .unwrap_or_else(|error| panic!("valid second: {error}"));
    let receipt = publish_generation(Some(&first), &second)
        .unwrap_or_else(|error| panic!("valid publication: {error}"));
    receipt
        .validate()
        .unwrap_or_else(|error| panic!("valid receipt: {error}"));

    let result = query_relations(
        &second,
        KnowledgeRelationQueryV2 {
            query_id: id("query:1"),
            generation_digest: second.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: vec![KnowledgeRelationKindV2::Causes],
            maximum_edges: 8,
        },
    )
    .unwrap_or_else(|error| panic!("valid query: {error}"));
    assert_eq!(result.edges.len(), 1);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);

    assert_eq!(
        query_relations(
            &second,
            KnowledgeRelationQueryV2 {
                query_id: id("query:stale"),
                generation_digest: digest("stale"),
                seed_node_ids: vec![id("node:a")],
                relation_kinds: Vec::new(),
                maximum_edges: 8,
            }
        ),
        Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation"
        ))
    );
}

#[test]
fn supports_and_contradicts_remain_distinct_edges() {
    let generation = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b")],
            vec![
                edge(
                    "a",
                    "b",
                    KnowledgeRelationKindV2::Supports,
                    "support-edge",
                ),
                edge(
                    "a",
                    "b",
                    KnowledgeRelationKindV2::Contradicts,
                    "contradict-edge",
                ),
            ],
        ),
    )
    .unwrap_or_else(|error| panic!("valid contradictory graph: {error}"));
    assert_eq!(generation.edges.len(), 2);
    assert_ne!(generation.edges[0].identity, generation.edges[1].identity);
}
