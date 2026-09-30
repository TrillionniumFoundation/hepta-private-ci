use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(label: &str, from: i64, to: i64) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(label),
        source_revision: Revision::new(1).unwrap_or_else(|error| panic!("valid revision: {error}")),
        source_fact_digest: digest(label),
        validity_digest: digest(&format!("{label}:{from}:{to}")),
        valid_from_unix_seconds: Some(from),
        valid_to_unix_seconds: Some(to),
        tombstoned: false,
    }
}

fn fixture(scope: &str) -> KnowledgeGenerationV2 {
    let nodes = ["a", "b", "c", "d", "e"]
        .into_iter()
        .map(|label| KnowledgeNodeV2 {
            node_id: id(&format!("node:{label}")),
            node_kind_id: id("kind:entity"),
            payload_digest: digest(label),
            supports: vec![support(&format!("source:node:{label}"), 0, 30)],
        })
        .collect();
    let edges = [("a", "a"), ("a", "b"), ("a", "c"), ("d", "e")]
        .into_iter()
        .map(|(from, to)| KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id(&format!("node:{from}")),
                relation: KnowledgeRelationKindV2::Supports,
                target_node_id: id(&format!("node:{to}")),
            },
            confidence: ProbabilityQ32::from_raw(1_u64 << 31)
                .unwrap_or_else(|error| panic!("valid probability: {error}")),
            validity_digest: digest("edge-validity"),
            supports: vec![
                support(&format!("source:edge:{from}:{to}:early"), 0, 10),
                support(&format!("source:edge:{from}:{to}:late"), 10, 20),
            ],
        })
        .collect();
    build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("valid generation: {error}")),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest(scope),
            generation_vector_digest: digest(&format!("vector:{scope}")),
            graph_profile_digest: digest("profile:budget-regression"),
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .unwrap_or_else(|error| panic!("valid fixture: {error}"))
}

fn request(generation: &KnowledgeGenerationV2, at: Option<i64>) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:budget-regression"),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: at,
        maximum_edges: 1,
    }
}

#[test]
fn bounded_index_matches_scan_oracle_across_time_and_truncation() {
    let generation = fixture("scope:one");
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("valid view: {error}"));
    for at in [
        None,
        Some(-1),
        Some(0),
        Some(9),
        Some(10),
        Some(19),
        Some(20),
        Some(30),
    ] {
        for maximum in [1, 2, 4] {
            for seeds in [vec![id("node:a")], vec![id("node:c"), id("node:a")]] {
                let mut query = request(&generation, at);
                query.maximum_edges = maximum;
                query.seed_node_ids = seeds;
                let expected = query_relations(&generation, query.clone())
                    .unwrap_or_else(|error| panic!("reference query: {error}"));
                let (actual, work) = verified
                    .query_relations_with_work(query.clone())
                    .unwrap_or_else(|error| panic!("indexed query: {error}"));
                assert_eq!(actual, expected);
                assert_eq!(work.validated_nodes, 0);
                assert_eq!(work.validated_edges, 0);
                assert_eq!(work.validated_supports, 0);
                assert_eq!(work.relation_edges_scanned, 3);
                assert_eq!(work.selected_edges_cloned, actual.edges.len() as u64);
                let charged = work.visibility_supports_inspected
                    + work.relation_supports_inspected
                    + work.selected_supports_cloned;
                if charged > 0 {
                    let (boundary, _) = verified
                        .query_relations_with_work_budget(query.clone(), charged)
                        .unwrap_or_else(|error| panic!("exact budget: {error}"));
                    assert_eq!(boundary, expected);
                    assert_eq!(
                        verified.query_relations_with_work_budget(query, charged - 1),
                        Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
                    );
                }
            }
        }
    }
}

#[test]
fn structural_copy_is_charged_before_allocation_and_omissions_do_not_clone() {
    let generation = fixture("scope:one");
    let query = request(&generation, None);
    let verified = VerifiedKnowledgeGenerationV2::new(generation)
        .unwrap_or_else(|error| panic!("valid view: {error}"));
    assert_eq!(
        verified.query_relations_with_work_budget(query.clone(), 1),
        Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
    );
    let (result, work) = verified
        .query_relations_with_work_budget(query, 2)
        .unwrap_or_else(|error| panic!("exact copy budget: {error}"));
    assert_eq!(result.edges.len(), 1);
    assert_eq!(result.omitted_count, 2);
    assert_eq!(work.selected_edges_cloned, 1);
    assert_eq!(work.selected_supports_cloned, 2);
    assert_eq!(work.relation_supports_inspected, 0);
}

#[test]
fn invalid_budget_cannot_raise_ceiling_or_poison_next_request() {
    let generation = fixture("scope:one");
    let query = request(&generation, Some(9));
    let expected = query_relations(&generation, query.clone())
        .unwrap_or_else(|error| panic!("reference query: {error}"));
    let verified = VerifiedKnowledgeGenerationV2::new(generation)
        .unwrap_or_else(|error| panic!("valid view: {error}"));
    for maximum in [0, 1, MAX_QUERY_SUPPORT_WORK_V2 + 1, u64::MAX] {
        assert_eq!(
            verified.query_relations_with_work_budget(query.clone(), maximum),
            Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
        );
    }
    assert_eq!(
        verified
            .query_relations(query)
            .unwrap_or_else(|error| panic!("unpoisoned query: {error}")),
        expected
    );
}

#[test]
fn verified_view_rechecks_time_and_rejects_other_source_cut() {
    let generation = fixture("scope:one");
    let other = fixture("scope:two");
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("valid view: {error}"));
    assert_eq!(
        verified.query_relations(request(&other, Some(9))),
        Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation"
        ))
    );
    let early = verified
        .query_relations(request(&generation, Some(9)))
        .unwrap_or_else(|error| panic!("early query: {error}"));
    let late = verified
        .query_relations(request(&generation, Some(10)))
        .unwrap_or_else(|error| panic!("late query: {error}"));
    assert_ne!(early.edges[0].supports, late.edges[0].supports);
    assert_ne!(early.request_digest, late.request_digest);
    assert_ne!(early.result_digest, late.result_digest);
    let expired = verified
        .query_relations(request(&generation, Some(20)))
        .unwrap_or_else(|error| panic!("expired query: {error}"));
    assert!(expired.edges.is_empty());
    assert_eq!(expired.omitted_count, 0);
}

#[test]
fn duplicate_source_identity_is_rejected_by_builder_and_validator() {
    let mut generation = fixture("scope:one");
    let mut duplicate = generation.edges[0].supports[0].clone();
    duplicate.source_fact_digest = digest("different fact same identity");
    generation.edges[0].supports.push(duplicate);
    generation.edges[0].supports.sort();
    generation.generation_digest = compute_generation_digest(&generation);
    assert_eq!(
        generation.validate(),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    );
    assert!(matches!(
        VerifiedKnowledgeGenerationV2::new(generation.clone()),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    ));
    assert_eq!(
        build_complete_generation(
            generation.generation,
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: generation.source_snapshot_digest,
                generation_vector_digest: generation.generation_vector_digest,
                graph_profile_digest: generation.graph_profile_digest,
                complete_source_cut: true,
                nodes: generation.nodes,
                edges: generation.edges,
            }
        ),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    );
}

#[test]
fn tampered_generation_and_revoked_edge_cannot_be_reused_as_current() {
    let generation = fixture("scope:one");
    let mut tampered = generation.clone();
    tampered.edges[0].validity_digest = digest("tampered");
    assert!(matches!(
        VerifiedKnowledgeGenerationV2::new(tampered),
        Err(KnowledgeGenerationErrorV2::DigestMismatch("generation"))
    ));
    let mut next_edges = generation.edges.clone();
    for edge in &mut next_edges {
        for support in &mut edge.supports {
            support.tombstoned = true;
        }
    }
    let next = build_complete_generation(
        generation
            .generation
            .next()
            .unwrap_or_else(|error| panic!("next generation: {error}")),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("scope:one:revoked"),
            generation_vector_digest: digest("vector:revoked"),
            graph_profile_digest: generation.graph_profile_digest,
            complete_source_cut: true,
            nodes: generation.nodes.clone(),
            edges: next_edges,
        },
    )
    .unwrap_or_else(|error| panic!("revoked generation: {error}"));
    let view = VerifiedKnowledgeGenerationV2::new(next.clone())
        .unwrap_or_else(|error| panic!("revoked view: {error}"));
    assert!(
        view.query_relations(request(&next, Some(5)))
            .unwrap_or_else(|error| panic!("revoked query: {error}"))
            .edges
            .is_empty()
    );
    assert_eq!(
        view.query_relations(request(&generation, Some(5))),
        Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation"
        ))
    );
}
