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
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error}"))
}

fn support(label: &str, tombstoned: bool) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("source:{label}")),
        source_revision: revision(1),
        source_fact_digest: digest(&format!("fact:{label}")),
        validity_digest: digest(&format!("validity:{label}")),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
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

    let mut updated_edge = edge("a", "b", KnowledgeRelationKindV2::Supports, "edge-ab-v2");
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
    let mut removed = edge("a", "b", KnowledgeRelationKindV2::Contradicts, "edge-ab");
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

    let candidate =
        build_complete_generation(generation(2), input(vec![node("a", "a")], Vec::new()))
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
            vec![edge("a", "b", KnowledgeRelationKindV2::Causes, "edge-ab")],
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
            valid_at_unix_seconds: None,
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
                valid_at_unix_seconds: None,
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
                edge("a", "b", KnowledgeRelationKindV2::Supports, "support-edge"),
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

#[test]
fn custom_relation_identities_are_lossless_and_queryable() {
    let studies = KnowledgeRelationKindV2::Custom(id("relation-kind:studies"));
    let teaches = KnowledgeRelationKindV2::Custom(id("relation-kind:teaches"));
    let generation = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b")],
            vec![
                edge("a", "b", studies.clone(), "studies-edge"),
                edge("a", "b", teaches, "teaches-edge"),
            ],
        ),
    )
    .unwrap_or_else(|error| panic!("valid custom-relation graph: {error}"));
    assert_eq!(generation.edges.len(), 2);
    assert_ne!(generation.edges[0].identity, generation.edges[1].identity);

    let result = query_relations(
        &generation,
        KnowledgeRelationQueryV2 {
            query_id: id("query:custom"),
            generation_digest: generation.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: vec![studies],
            valid_at_unix_seconds: None,
            maximum_edges: 8,
        },
    )
    .unwrap_or_else(|error| panic!("valid custom query: {error}"));
    assert_eq!(result.edges.len(), 1);
    assert_eq!(
        result.edges[0].identity.relation,
        KnowledgeRelationKindV2::Custom(id("relation-kind:studies"))
    );
}

#[test]
fn composed_owner_can_retain_more_than_sixty_four_supports() {
    let mut canonical = node("shared", "shared");
    canonical.supports = (1..=65)
        .map(|index| support(&format!("shared-{index}"), false))
        .collect();
    let generation = build_complete_generation(generation(1), input(vec![canonical], Vec::new()))
        .unwrap_or_else(|error| panic!("65 explicit supports remain within owner bounds: {error}"));
    assert_eq!(generation.nodes[0].supports.len(), 65);
}

#[test]
fn temporal_visibility_matches_inclusive_start_and_exclusive_end() {
    let mut timed = edge("a", "b", KnowledgeRelationKindV2::Supports, "timed-edge");
    timed.supports[0].valid_from_unix_seconds = Some(100);
    timed.supports[0].valid_to_unix_seconds = Some(200);
    let generation = build_complete_generation(
        generation(1),
        input(vec![node("a", "a"), node("b", "b")], vec![timed]),
    )
    .unwrap_or_else(|error| panic!("valid timed graph: {error}"));

    let query_at = |at| {
        query_relations(
            &generation,
            KnowledgeRelationQueryV2 {
                query_id: id(&format!("query:at:{at}")),
                generation_digest: generation.generation_digest,
                seed_node_ids: vec![id("node:a")],
                relation_kinds: Vec::new(),
                valid_at_unix_seconds: Some(at),
                maximum_edges: 8,
            },
        )
        .unwrap_or_else(|error| panic!("valid timed query: {error}"))
    };
    assert!(query_at(99).edges.is_empty());
    assert_eq!(query_at(100).edges.len(), 1);
    assert_eq!(query_at(199).edges.len(), 1);
    assert!(query_at(200).edges.is_empty());

    let structural = query_relations(
        &generation,
        KnowledgeRelationQueryV2 {
            query_id: id("query:structural"),
            generation_digest: generation.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: None,
            maximum_edges: 8,
        },
    )
    .unwrap_or_else(|error| panic!("valid structural query: {error}"));
    assert_eq!(structural.edges.len(), 1);
}

#[test]
fn invalid_temporal_support_window_is_rejected() {
    let mut invalid = node("a", "a");
    invalid.supports[0].valid_from_unix_seconds = Some(200);
    invalid.supports[0].valid_to_unix_seconds = Some(200);
    assert_eq!(
        build_complete_generation(generation(1), input(vec![invalid], Vec::new())),
        Err(KnowledgeGenerationErrorV2::InvalidValidityWindow)
    );
}

#[test]
fn duplicate_incremental_upserts_are_rejected_before_last_write_wins() {
    let first = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a-v1"), node("b", "b-v1")],
            vec![edge("a", "b", KnowledgeRelationKindV2::Supports, "edge-ab")],
        ),
    )
    .unwrap_or_else(|error| panic!("valid predecessor: {error}"));

    let duplicate_node = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: first.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: digest("profile:1"),
        remove_node_ids: Vec::new(),
        upsert_nodes: vec![node("a", "a-v2"), node("a", "a-v3")],
        remove_edge_identities: Vec::new(),
        upsert_edges: Vec::new(),
    };
    assert_eq!(
        apply_incremental_delta(&first, generation(2), duplicate_node),
        Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity)
    );

    let duplicate_edge_value = edge("a", "b", KnowledgeRelationKindV2::Supports, "edge-ab-v2");
    let duplicate_edge = KnowledgeProjectionDeltaV2 {
        expected_predecessor_digest: first.generation_digest,
        source_snapshot_digest: digest("snapshot:2"),
        generation_vector_digest: digest("vector:2"),
        graph_profile_digest: digest("profile:1"),
        remove_node_ids: Vec::new(),
        upsert_nodes: Vec::new(),
        remove_edge_identities: Vec::new(),
        upsert_edges: vec![duplicate_edge_value.clone(), duplicate_edge_value],
    };
    assert_eq!(
        apply_incremental_delta(&first, generation(2), duplicate_edge),
        Err(KnowledgeGenerationErrorV2::DuplicateDeltaIdentity)
    );
}

#[test]
fn adversarial_mixed_delta_matches_full_rebuild_canonically() {
    let first = build_complete_generation(
        generation(1),
        input(
            vec![node("c", "c-v1"), node("a", "a-v1"), node("b", "b-v1")],
            vec![
                edge("b", "c", KnowledgeRelationKindV2::Causes, "edge-bc-v1"),
                edge("a", "b", KnowledgeRelationKindV2::Supports, "edge-ab-v1"),
            ],
        ),
    )
    .unwrap_or_else(|error| panic!("valid predecessor: {error}"));

    let removed_ab = KnowledgeEdgeIdentityV2 {
        source_node_id: id("node:a"),
        relation: KnowledgeRelationKindV2::Supports,
        target_node_id: id("node:b"),
    };
    let mut tombstoned = edge(
        "a",
        "c",
        KnowledgeRelationKindV2::Contradicts,
        "edge-ac-deleted",
    );
    tombstoned.supports[0].tombstoned = true;
    let replacement = edge(
        "c",
        "a",
        KnowledgeRelationKindV2::Custom(id("relation-kind:references")),
        "edge-ca-v2",
    );

    let incremental = apply_incremental_delta(
        &first,
        generation(2),
        KnowledgeProjectionDeltaV2 {
            expected_predecessor_digest: first.generation_digest,
            source_snapshot_digest: digest("snapshot:adversarial:2"),
            generation_vector_digest: digest("vector:adversarial:2"),
            graph_profile_digest: digest("profile:1"),
            remove_node_ids: vec![id("node:b")],
            upsert_nodes: vec![node("c", "c-v2"), node("a", "a-v1")],
            remove_edge_identities: vec![removed_ab],
            upsert_edges: vec![tombstoned, replacement.clone()],
        },
    )
    .unwrap_or_else(|error| panic!("valid mixed delta: {error}"));

    let full = build_complete_generation(
        generation(2),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("snapshot:adversarial:2"),
            generation_vector_digest: digest("vector:adversarial:2"),
            graph_profile_digest: digest("profile:1"),
            complete_source_cut: true,
            nodes: vec![node("a", "a-v1"), node("c", "c-v2")],
            edges: vec![replacement],
        },
    )
    .unwrap_or_else(|error| panic!("valid full rebuild: {error}"));

    assert_eq!(incremental, full);
    assert_eq!(incremental.generation_digest, full.generation_digest);
}

#[test]
fn query_result_digest_binds_complete_request_even_when_edges_match() {
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b")],
            vec![edge("a", "b", KnowledgeRelationKindV2::Causes, "edge-ab")],
        ),
    )
    .unwrap_or_else(|error| panic!("valid graph: {error}"));

    let run = |seeds: Vec<StableId>, kinds: Vec<KnowledgeRelationKindV2>, maximum_edges| {
        query_relations(
            &graph,
            KnowledgeRelationQueryV2 {
                query_id: id("query:request-binding"),
                generation_digest: graph.generation_digest,
                seed_node_ids: seeds,
                relation_kinds: kinds,
                valid_at_unix_seconds: None,
                maximum_edges,
            },
        )
        .unwrap_or_else(|error| panic!("valid query: {error}"))
    };

    let baseline = run(vec![id("node:a")], vec![KnowledgeRelationKindV2::Causes], 8);
    let broader_seed = run(
        vec![id("node:a"), id("node:b")],
        vec![KnowledgeRelationKindV2::Causes],
        8,
    );
    let broader_filter = run(vec![id("node:a")], Vec::new(), 8);
    let broader_limit = run(vec![id("node:a")], vec![KnowledgeRelationKindV2::Causes], 9);

    for changed in [&broader_seed, &broader_filter, &broader_limit] {
        assert_eq!(baseline.edges, changed.edges);
        assert_eq!(baseline.omitted_count, changed.omitted_count);
        assert_ne!(baseline.request_digest, changed.request_digest);
        assert_ne!(baseline.result_digest, changed.result_digest);
    }
}

#[test]
fn bounded_query_does_not_retain_capacity_for_omitted_history() {
    for count in [1, 64, 1024] {
        let mut nodes = vec![node("root", "root")];
        let mut edges = Vec::new();
        for index in 0..count {
            let label = format!("target-{index:04}");
            nodes.push(node(&label, &label));
            edges.push(edge(
                "root",
                &label,
                KnowledgeRelationKindV2::Supports,
                &label,
            ));
        }
        let graph =
            build_complete_generation(generation(1), input(nodes, edges)).expect("complete graph");
        for maximum_edges in [1, 3, 64] {
            let result = query_relations(
                &graph,
                KnowledgeRelationQueryV2 {
                    query_id: id("query:bounded-history"),
                    generation_digest: graph.generation_digest,
                    seed_node_ids: vec![id("node:root")],
                    relation_kinds: Vec::new(),
                    valid_at_unix_seconds: None,
                    maximum_edges,
                },
            )
            .expect("bounded query");
            let retained = count.min(maximum_edges as usize);
            assert_eq!(result.edges, graph.edges[..retained]);
            assert_eq!(result.omitted_count as usize, count - retained);
            assert!(
                result.edges.capacity() <= retained.max(4).next_power_of_two(),
                "omitted history must not reserve output storage: count={count}, limit={maximum_edges}, capacity={}",
                result.edges.capacity()
            );
            assert_eq!(result.result_digest, compute_query_result_digest(&result));
        }
    }
}

#[test]
fn bounded_query_counts_only_visible_matching_edges_and_filters_selected_supports() {
    let mut hidden_node = node("hidden", "hidden");
    hidden_node.supports[0].valid_to_unix_seconds = Some(100);
    let mut mixed = edge("a", "b", KnowledgeRelationKindV2::Supports, "expired");
    mixed.supports[0].valid_to_unix_seconds = Some(100);
    mixed.supports.push(support("live", false));
    let mut expired = edge("a", "c", KnowledgeRelationKindV2::Supports, "expired-only");
    expired.supports[0].valid_to_unix_seconds = Some(100);
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![
                node("a", "a"),
                node("b", "b"),
                node("c", "c"),
                node("d", "d"),
                hidden_node,
            ],
            vec![
                mixed,
                expired,
                edge("a", "d", KnowledgeRelationKindV2::Supports, "second-live"),
                edge(
                    "a",
                    "hidden",
                    KnowledgeRelationKindV2::Supports,
                    "hidden-endpoint",
                ),
                edge("a", "c", KnowledgeRelationKindV2::Contradicts, "wrong-kind"),
            ],
        ),
    )
    .expect("complete timed graph");
    let result = query_relations(
        &graph,
        KnowledgeRelationQueryV2 {
            query_id: id("query:bounded-visible"),
            generation_digest: graph.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: vec![KnowledgeRelationKindV2::Supports],
            valid_at_unix_seconds: Some(100),
            maximum_edges: 1,
        },
    )
    .expect("bounded visible query");
    assert_eq!(result.edges.len(), 1);
    assert_eq!(result.edges[0].identity.target_node_id, id("node:b"));
    assert_eq!(result.edges[0].supports, vec![support("live", false)]);
    assert_eq!(result.omitted_count, 1);
    assert_eq!(result.result_digest, compute_query_result_digest(&result));
}

#[test]
fn bounded_query_still_rejects_tampering_beyond_returned_prefix() {
    let mut graph = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b"), node("c", "c")],
            vec![
                edge("a", "b", KnowledgeRelationKindV2::Supports, "first"),
                edge("a", "c", KnowledgeRelationKindV2::Supports, "second"),
            ],
        ),
    )
    .expect("complete graph");
    graph.edges[1].supports[0].source_fact_digest = digest("tampered-omitted-support");
    assert_eq!(
        query_relations(
            &graph,
            KnowledgeRelationQueryV2 {
                query_id: id("query:tampered-tail"),
                generation_digest: graph.generation_digest,
                seed_node_ids: vec![id("node:a")],
                relation_kinds: Vec::new(),
                valid_at_unix_seconds: None,
                maximum_edges: 1,
            }
        ),
        Err(KnowledgeGenerationErrorV2::DigestMismatch("generation"))
    );
}

#[test]
fn bounded_query_clones_only_selected_edges_and_counts_every_omission() {
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![
                node("a", "a"),
                node("b", "b"),
                node("c", "c"),
                node("d", "d"),
            ],
            vec![
                edge("a", "b", KnowledgeRelationKindV2::Causes, "edge-ab"),
                edge("a", "c", KnowledgeRelationKindV2::Causes, "edge-ac"),
                edge("a", "d", KnowledgeRelationKindV2::Causes, "edge-ad"),
            ],
        ),
    )
    .unwrap_or_else(|error| panic!("valid graph: {error}"));
    let query = KnowledgeRelationQueryV2 {
        query_id: id("query:bounded-copy"),
        generation_digest: graph.generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: vec![KnowledgeRelationKindV2::Causes],
        valid_at_unix_seconds: None,
        maximum_edges: 1,
    };

    let (measured, work) = query_relations_with_work(&graph, query.clone())
        .unwrap_or_else(|error| panic!("valid measured query: {error}"));
    let ordinary = query_relations(&graph, query)
        .unwrap_or_else(|error| panic!("valid ordinary query: {error}"));

    assert_eq!(measured, ordinary);
    assert_eq!(measured.edges, graph.edges[..1]);
    assert_eq!(measured.omitted_count, 2);
    assert_eq!(work.validated_nodes, 4);
    assert_eq!(work.validated_edges, 3);
    assert_eq!(work.validated_supports, 7);
    assert_eq!(work.relation_edges_scanned, 3);
    assert_eq!(work.matching_edges, 3);
    assert_eq!(work.selected_edges_cloned, 1);
    assert_eq!(work.selected_supports_cloned, 1);
    assert_eq!(work.omitted_edges, 2);
}

#[test]
fn measured_query_filters_large_support_history_before_cloning() {
    let mut relation = edge("a", "b", KnowledgeRelationKindV2::Causes, "unused");
    relation.supports = (0..4096)
        .map(|index| {
            let mut value = support(&format!("history-{index:04}"), false);
            if index != 4095 {
                value.valid_to_unix_seconds = Some(100);
            }
            value
        })
        .collect();
    let graph = build_complete_generation(
        generation(1),
        input(vec![node("a", "a"), node("b", "b")], vec![relation]),
    )
    .expect("support-rich graph");
    let query = KnowledgeRelationQueryV2 {
        query_id: id("query:support-history"),
        generation_digest: graph.generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: Some(100),
        maximum_edges: 1,
    };
    let (measured, work) =
        query_relations_with_work(&graph, query.clone()).expect("measured query");
    assert_eq!(
        measured,
        query_relations(&graph, query).expect("ordinary query")
    );
    assert_eq!(
        measured.edges[0].supports,
        vec![support("history-4095", false)]
    );
    assert_eq!(measured.omitted_count, 0);
    assert_eq!(work.relation_supports_inspected, 4096);
    assert_eq!(work.selected_supports_cloned, 1);
    assert!(measured.edges[0].supports.capacity() < 16);
}

#[test]
fn measured_query_matches_collect_then_truncate_reference_for_every_bound() {
    let mut edges = Vec::new();
    for index in 0..64 {
        let mut value = edge(
            "a",
            "b",
            KnowledgeRelationKindV2::Custom(id(&format!("r:{index:02}"))),
            &format!("s:{index:02}"),
        );
        value.supports[0].valid_to_unix_seconds = Some(index + 100);
        edges.push(value);
    }
    let graph = build_complete_generation(
        generation(1),
        input(vec![node("a", "a"), node("b", "b")], edges),
    )
    .expect("graph");
    for at in [None, Some(100), Some(132), Some(164)] {
        for limit in [1, 2, 31, 64, 100] {
            let mut expected = graph
                .edges
                .iter()
                .filter_map(|edge| {
                    let mut edge = edge.clone();
                    if let Some(at) = at {
                        edge.supports.retain(|support| support.visible_at(at));
                    }
                    (!edge.supports.is_empty()).then_some(edge)
                })
                .collect::<Vec<_>>();
            let matches = expected.len();
            expected.truncate(limit as usize);
            let query = KnowledgeRelationQueryV2 {
                query_id: id("query:reference"),
                generation_digest: graph.generation_digest,
                seed_node_ids: vec![id("node:a")],
                relation_kinds: Vec::new(),
                valid_at_unix_seconds: at,
                maximum_edges: limit,
            };
            let (result, work) = query_relations_with_work(&graph, query.clone()).expect("query");
            let reference = KnowledgeRelationResultV2 {
                edges: expected,
                omitted_count: matches.saturating_sub(limit as usize) as u32,
                ..result.clone()
            };
            assert_eq!(result, reference);
            assert_eq!(
                result.result_digest,
                compute_query_result_digest(&reference)
            );
            assert_eq!(
                result,
                query_relations(&graph, query).expect("ordinary query")
            );
            assert_eq!(work.selected_edges_cloned as usize, result.edges.len());
            assert_eq!(work.selected_supports_cloned as usize, result.edges.len());
            assert_eq!(work.omitted_edges as u32, result.omitted_count);
        }
    }
}

#[test]
fn bulk_node_retirement_and_replacement_match_full_rebuild() {
    for count in [16_usize, 128, 1024] {
        let mut nodes = vec![node("hub", "hub")];
        let mut edges = Vec::new();
        for index in 0..count {
            let label = format!("leaf-{index:05}");
            nodes.push(node(&label, &label));
            edges.push(edge(
                "hub",
                &label,
                KnowledgeRelationKindV2::Supports,
                &label,
            ));
        }
        let first = build_complete_generation(generation(1), input(nodes, edges))
            .unwrap_or_else(|error| panic!("first: {error}"));
        let before = first.clone();
        let removed = (0..count / 2)
            .map(|index| id(&format!("node:leaf-{index:05}")))
            .collect::<Vec<_>>();
        // Reinsert a retired node and one of its edges. Other incident edges
        // remain retired. Replacement of a surviving edge has the same order.
        let replacement_node = node("leaf-00000", "new-payload");
        let replacement_edge = edge(
            "hub",
            "leaf-00000",
            KnowledgeRelationKindV2::Contradicts,
            "new-support",
        );
        let last = format!("leaf-{:05}", count - 1);
        let updated_edge = edge("hub", &last, KnowledgeRelationKindV2::Supports, "updated");
        let removed_edge = first.edges[count - 2].identity.clone();
        let mut expected_nodes = vec![node("hub", "hub"), replacement_node.clone()];
        let mut expected_edges = vec![replacement_edge.clone(), updated_edge.clone()];
        for index in count / 2..count {
            let label = format!("leaf-{index:05}");
            expected_nodes.push(node(&label, &label));
            if index < count - 2 {
                expected_edges.push(edge(
                    "hub",
                    &label,
                    KnowledgeRelationKindV2::Supports,
                    &label,
                ));
            }
        }
        let full = build_complete_generation(
            generation(2),
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: digest("snapshot:2"),
                generation_vector_digest: digest("vector:2"),
                graph_profile_digest: first.graph_profile_digest,
                complete_source_cut: true,
                nodes: expected_nodes,
                edges: expected_edges,
            },
        )
        .unwrap_or_else(|error| panic!("full: {error}"));
        for reverse in [false, true] {
            let mut remove_node_ids = removed.clone();
            if reverse {
                remove_node_ids.reverse();
            }
            let actual = apply_incremental_delta(
                &first,
                generation(2),
                KnowledgeProjectionDeltaV2 {
                    expected_predecessor_digest: first.generation_digest,
                    source_snapshot_digest: digest("snapshot:2"),
                    generation_vector_digest: digest("vector:2"),
                    graph_profile_digest: first.graph_profile_digest,
                    remove_node_ids,
                    upsert_nodes: vec![replacement_node.clone()],
                    remove_edge_identities: vec![
                        removed_edge.clone(),
                        updated_edge.identity.clone(),
                    ],
                    upsert_edges: vec![replacement_edge.clone(), updated_edge.clone()],
                },
            )
            .unwrap_or_else(|error| panic!("delta: {error}"));
            assert_eq!(actual, full);
            assert_eq!(first, before);
        }
    }
}

#[test]
#[ignore = "observational history-growth measurement; not a target-host qualification"]
fn bulk_retirement_emits_history_growth_curve() {
    for count in [1024_usize, 4096, 16384] {
        let mut nodes = vec![node("hub", "hub")];
        let mut edges = Vec::new();
        for index in 0..count {
            let label = format!("leaf-{index:05}");
            nodes.push(node(&label, &label));
            edges.push(edge(
                "hub",
                &label,
                KnowledgeRelationKindV2::Supports,
                &label,
            ));
        }
        let first = build_complete_generation(generation(1), input(nodes, edges))
            .unwrap_or_else(|error| panic!("first: {error}"));
        let delta = KnowledgeProjectionDeltaV2 {
            expected_predecessor_digest: first.generation_digest,
            source_snapshot_digest: digest("snapshot:2"),
            generation_vector_digest: digest("vector:2"),
            graph_profile_digest: first.graph_profile_digest,
            remove_node_ids: (0..count / 2)
                .map(|index| id(&format!("node:leaf-{index:05}")))
                .collect(),
            upsert_nodes: Vec::new(),
            remove_edge_identities: Vec::new(),
            upsert_edges: Vec::new(),
        };
        let started = std::time::Instant::now();
        let result = apply_incremental_delta(&first, generation(2), delta)
            .unwrap_or_else(|error| panic!("delta: {error}"));
        let elapsed_ns = started.elapsed().as_nanos();
        assert_eq!(result.edges.len(), count / 2);
        assert_eq!(result.nodes.len(), count / 2 + 1);
        println!(
            "KG_BULK_RETIREMENT nodes={} edges={} removed={} retained_edges={} elapsed_ns={elapsed_ns}",
            count + 1,
            count,
            count / 2,
            result.edges.len()
        );
    }
}
