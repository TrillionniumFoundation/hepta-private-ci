use super::*;

#[test]
fn duplicate_support_identity_is_rejected_even_with_recomputed_digest() {
    for on_edge in [false, true] {
        let mut candidate = build_complete_generation(
            generation(1),
            input(
                vec![node("a", "a"), node("b", "b")],
                vec![edge("a", "b", KnowledgeRelationKindV2::Supports, "ab")],
            ),
        )
        .expect("valid fixture");
        let supports = if on_edge {
            &mut candidate.edges[0].supports
        } else {
            &mut candidate.nodes[0].supports
        };
        let mut duplicate = supports[0].clone();
        duplicate.source_fact_digest = digest("different-content-same-source-revision");
        supports.push(duplicate);
        supports.sort();
        candidate.generation_digest = compute_generation_digest(&candidate);
        assert_eq!(
            candidate.validate(),
            Err(KnowledgeGenerationErrorV2::DuplicateSupport)
        );
        assert_eq!(
            build_complete_generation(generation(1), input(candidate.nodes, candidate.edges)),
            Err(KnowledgeGenerationErrorV2::DuplicateSupport)
        );
    }
}

#[test]
fn generation_validation_rejects_noncanonical_nodes_and_edges() {
    let canonical = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), node("b", "b")],
            vec![
                edge("a", "b", KnowledgeRelationKindV2::Supports, "ab"),
                edge("b", "a", KnowledgeRelationKindV2::Contradicts, "ba"),
            ],
        ),
    )
    .expect("valid fixture");
    let mut nodes = canonical.clone();
    nodes.nodes.reverse();
    nodes.generation_digest = compute_generation_digest(&nodes);
    assert_eq!(
        nodes.validate(),
        Err(KnowledgeGenerationErrorV2::NonCanonicalNodeOrder)
    );
    let mut edges = canonical;
    edges.edges.reverse();
    edges.generation_digest = compute_generation_digest(&edges);
    assert_eq!(
        edges.validate(),
        Err(KnowledgeGenerationErrorV2::NonCanonicalEdgeOrder)
    );
}

#[test]
fn simultaneous_endpoint_and_last_edge_support_revocation_is_valid() {
    let mut removed_node = node("b", "b");
    removed_node.supports[0].tombstoned = true;
    let mut removed_edge = edge("a", "b", KnowledgeRelationKindV2::Supports, "ab");
    removed_edge.supports[0].tombstoned = true;
    let observed = build_complete_generation(
        generation(1),
        input(vec![node("a", "a"), removed_node], vec![removed_edge]),
    )
    .expect("atomic source cut revokes endpoint and relation");
    let expected =
        build_complete_generation(generation(1), input(vec![node("a", "a")], Vec::new()))
            .expect("expected cut");
    assert_eq!(observed, expected);
}

#[test]
fn indexed_and_reference_queries_have_identical_complete_receipts() {
    let mut b = node("b", "b");
    b.supports[0].valid_from_unix_seconds = Some(10);
    b.supports[0].valid_to_unix_seconds = Some(20);
    let mut ab = edge("a", "b", KnowledgeRelationKindV2::Supports, "ab");
    ab.supports[0].valid_from_unix_seconds = Some(5);
    ab.supports[0].valid_to_unix_seconds = Some(15);
    let mut additional = support("ab-later", false);
    additional.valid_from_unix_seconds = Some(15);
    additional.valid_to_unix_seconds = Some(25);
    ab.supports.push(additional);
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![node("a", "a"), b, node("c", "c")],
            vec![
                ab,
                edge("a", "a", KnowledgeRelationKindV2::Contradicts, "aa"),
                edge("c", "b", KnowledgeRelationKindV2::Causes, "cb"),
            ],
        ),
    )
    .expect("temporal fixture");
    let verified = VerifiedKnowledgeGenerationV2::new(graph.clone()).expect("validated view");
    for at in [
        None,
        Some(0),
        Some(10),
        Some(14),
        Some(15),
        Some(19),
        Some(20),
        Some(25),
    ] {
        for seeds in [
            vec![],
            vec![id("node:a")],
            vec![id("node:a"), id("node:b")],
            vec![id("node:unknown")],
        ] {
            for kinds in [
                vec![],
                vec![KnowledgeRelationKindV2::Supports],
                vec![KnowledgeRelationKindV2::Causes],
            ] {
                for maximum_edges in [1, 2, 8] {
                    let query = KnowledgeRelationQueryV2 {
                        query_id: id("query:equivalence"),
                        generation_digest: graph.generation_digest,
                        seed_node_ids: seeds.clone(),
                        relation_kinds: kinds.clone(),
                        valid_at_unix_seconds: at,
                        maximum_edges,
                    };
                    let expected = query_relations(&graph, query.clone()).expect("reference");
                    let (observed, work) =
                        verified.query_relations_with_work(query).expect("indexed");
                    assert_eq!(observed, expected);
                    assert_eq!(
                        (
                            work.validated_nodes,
                            work.validated_edges,
                            work.validated_supports
                        ),
                        (0, 0, 0)
                    );
                }
            }
        }
    }
    let query = KnowledgeRelationQueryV2 {
        query_id: id("query:stale"),
        generation_digest: digest("another-scope-or-generation"),
        seed_node_ids: vec![id("node:a")],
        relation_kinds: vec![],
        valid_at_unix_seconds: None,
        maximum_edges: 1,
    };
    assert_eq!(
        verified.query_relations(query),
        Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation"
        ))
    );
}

#[test]
fn repeated_sparse_queries_do_not_revalidate_or_scan_unrelated_edges() {
    let nodes = (0..128)
        .map(|index| node(&format!("n{index:03}"), "payload"))
        .collect();
    let edges = (0..127)
        .map(|index| {
            edge(
                &format!("n{index:03}"),
                &format!("n{:03}", index + 1),
                KnowledgeRelationKindV2::Supports,
                &format!("e{index:03}"),
            )
        })
        .collect();
    let graph = build_complete_generation(generation(1), input(nodes, edges)).expect("chain");
    let verified = VerifiedKnowledgeGenerationV2::new(graph.clone()).expect("view");
    for _ in 0..8 {
        let query = KnowledgeRelationQueryV2 {
            query_id: id("query:sparse"),
            generation_digest: graph.generation_digest,
            seed_node_ids: vec![id("node:n064")],
            relation_kinds: vec![],
            valid_at_unix_seconds: Some(10),
            maximum_edges: 1,
        };
        let reference = query_relations(&graph, query.clone()).expect("reference");
        let (observed, work) = verified.query_relations_with_work(query).expect("indexed");
        assert_eq!(observed, reference);
        assert_eq!(
            (
                work.relation_edges_scanned,
                work.selected_edges_cloned,
                work.omitted_edges
            ),
            (2, 1, 1)
        );
        assert_eq!(work.validated_supports, 0);
        assert!(work.visibility_nodes_scanned <= 3);
    }
}

#[test]
fn verified_view_rejects_payload_drift_and_invalid_requests() {
    let graph = build_complete_generation(generation(1), input(vec![node("a", "a")], vec![]))
        .expect("fixture");
    let mut tampered = graph.clone();
    tampered.nodes[0].payload_digest = digest("tampered");
    assert!(matches!(
        VerifiedKnowledgeGenerationV2::new(tampered),
        Err(KnowledgeGenerationErrorV2::DigestMismatch("generation"))
    ));
    let verified = VerifiedKnowledgeGenerationV2::new(graph.clone()).expect("view");
    for query in [
        KnowledgeRelationQueryV2 {
            query_id: id("query:duplicate-seed"),
            generation_digest: graph.generation_digest,
            seed_node_ids: vec![id("node:a"), id("node:a")],
            relation_kinds: vec![],
            valid_at_unix_seconds: None,
            maximum_edges: 1,
        },
        KnowledgeRelationQueryV2 {
            query_id: id("query:zero-limit"),
            generation_digest: graph.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: vec![],
            valid_at_unix_seconds: None,
            maximum_edges: 0,
        },
        KnowledgeRelationQueryV2 {
            query_id: id("query:duplicate-kind"),
            generation_digest: graph.generation_digest,
            seed_node_ids: vec![id("node:a")],
            relation_kinds: vec![KnowledgeRelationKindV2::Supports; 2],
            valid_at_unix_seconds: None,
            maximum_edges: 1,
        },
    ] {
        let expected = query_relations(&graph, query.clone());
        assert!(expected.is_err());
        assert_eq!(verified.query_relations(query), expected);
    }
}
