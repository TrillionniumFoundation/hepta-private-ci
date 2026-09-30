//! Public-API regression matrix; no owner, writer, or activation authority.
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationErrorV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::VerifiedKnowledgeGenerationV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::query_relations;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture identity: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(value: &str, from: i64, to: i64) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(value),
        source_revision: Revision::new(1)
            .unwrap_or_else(|error| panic!("fixture revision: {error}")),
        source_fact_digest: digest(value),
        validity_digest: digest(&format!("validity:{value}:{from}:{to}")),
        valid_from_unix_seconds: Some(from),
        valid_to_unix_seconds: Some(to),
        tombstoned: false,
    }
}

fn fixture() -> KnowledgeProjectionInputV2 {
    let nodes = (0..12)
        .map(|index| KnowledgeNodeV2 {
            node_id: id(&format!("node:{index:02}")),
            node_kind_id: id("kind:entity"),
            payload_digest: digest(&format!("payload:{index}")),
            supports: vec![
                support(&format!("source:node:{index}:a"), 0, 10),
                support(&format!("source:node:{index}:b"), 10, 30),
            ],
        })
        .collect();
    let mut edges = Vec::new();
    for index in 0..12 {
        for target in [index, (index + 1) % 12] {
            edges.push(KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: id(&format!("node:{index:02}")),
                    relation: if target == index {
                        KnowledgeRelationKindV2::Contradicts
                    } else {
                        KnowledgeRelationKindV2::Supports
                    },
                    target_node_id: id(&format!("node:{target:02}")),
                },
                confidence: ProbabilityQ32::from_raw(1_u64 << 31)
                    .unwrap_or_else(|error| panic!("fixture confidence: {error}")),
                validity_digest: digest(&format!("edge:{index}:{target}")),
                supports: vec![
                    support(&format!("source:edge:{index}:{target}:a"), 1, 7),
                    support(&format!("source:edge:{index}:{target}:b"), 12, 25),
                ],
            });
        }
    }
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest("owner:fixture:source-cut"),
        generation_vector_digest: digest("vector:fixture"),
        graph_profile_digest: digest("profile:fixture"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

fn build(input: KnowledgeProjectionInputV2) -> KnowledgeGenerationV2 {
    build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("fixture generation: {error}")),
        input,
    )
    .unwrap_or_else(|error| panic!("valid fixture: {error}"))
}

fn request(generation: &KnowledgeGenerationV2) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:acceptance"),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id("node:00")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: Some(2),
        maximum_edges: 1,
    }
}

#[test]
fn indexed_receipts_equal_reference_across_time_filters_seeds_and_bounds() {
    let generation = build(fixture());
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified view: {error}"));
    let mut permuted = fixture();
    permuted.nodes.reverse();
    permuted.edges.reverse();
    for node in &mut permuted.nodes {
        node.supports.reverse();
    }
    for edge in &mut permuted.edges {
        edge.supports.reverse();
    }
    assert_eq!(build(permuted), generation);
    for mask in 0..8 {
        for at in [
            None,
            Some(0),
            Some(1),
            Some(7),
            Some(10),
            Some(12),
            Some(25),
            Some(30),
        ] {
            for kinds in [
                Vec::new(),
                vec![KnowledgeRelationKindV2::Supports],
                vec![KnowledgeRelationKindV2::Contradicts],
                vec![KnowledgeRelationKindV2::Causes],
            ] {
                for maximum in [1, 2, 24] {
                    let mut query = request(&generation);
                    query.seed_node_ids = (0..3)
                        .filter(|index| mask & (1 << index) != 0)
                        .map(|index| id(&format!("node:{index:02}")))
                        .collect();
                    query.valid_at_unix_seconds = at;
                    query.relation_kinds = kinds.clone();
                    query.maximum_edges = maximum;
                    let reference = query_relations(&generation, query.clone())
                        .unwrap_or_else(|error| panic!("reference: {error}"));
                    let (indexed, work) = verified
                        .query_relations_with_work(query)
                        .unwrap_or_else(|error| panic!("indexed result: {error}"));
                    assert_eq!(
                        indexed, reference,
                        "mask={mask}, at={at:?}, maximum={maximum}"
                    );
                    assert_eq!(work.validated_nodes, 0);
                    assert_eq!(work.validated_edges, 0);
                    assert_eq!(work.selected_edges_cloned, indexed.edges.len() as u64);
                    assert_eq!(work.omitted_edges, u64::from(indexed.omitted_count));
                }
            }
        }
    }
}

#[test]
fn work_budget_boundary_is_exact_and_no_partial_success_is_returned() {
    let generation = build(fixture());
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified view: {error}"));
    for at in [None, Some(2), Some(12)] {
        let mut query = request(&generation);
        query.valid_at_unix_seconds = at;
        let (expected, work) = verified
            .query_relations_with_work(query.clone())
            .unwrap_or_else(|error| panic!("query: {error}"));
        let required = work.visibility_supports_inspected
            + work.relation_supports_inspected
            + work.selected_supports_cloned;
        assert!(required > 0);
        assert_eq!(
            verified
                .query_relations_with_work_budget(query.clone(), required)
                .unwrap_or_else(|error| panic!("exact budget: {error}"))
                .0,
            expected
        );
        assert!(matches!(
            verified.query_relations_with_work_budget(query, required - 1),
            Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
        ));
    }
    let (_, work) = verified
        .query_relations_with_work(request(&generation))
        .unwrap_or_else(|error| panic!("query: {error}"));
    assert!(work.relation_edges_scanned < generation.edges.len() as u64);
    assert_eq!(work.selected_edges_cloned, 1);
    assert!(work.omitted_edges > 0);
}

#[test]
fn public_validation_rejects_duplicate_identity_before_digest_check() {
    let mut generation = build(fixture());
    let mut duplicate = generation.nodes[0].supports[0].clone();
    duplicate.source_fact_digest = digest("different fact under reused source identity");
    generation.nodes[0].supports.push(duplicate);
    generation.nodes[0].supports.sort();
    assert!(matches!(
        generation.validate(),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    ));
    assert!(matches!(
        VerifiedKnowledgeGenerationV2::new(generation),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    ));
    let mut input = fixture();
    let mut duplicate = input.nodes[0].supports[0].clone();
    duplicate.source_fact_digest = digest("different fact under reused source identity");
    input.nodes[0].supports.push(duplicate);
    assert!(matches!(
        build_complete_generation(
            Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
            input
        ),
        Err(KnowledgeGenerationErrorV2::DuplicateSupport)
    ));
}

#[test]
fn withdrawn_nodes_and_edges_drop_together_but_live_dangling_edges_fail() {
    let mut input = fixture();
    for node in &mut input.nodes {
        for support in &mut node.supports {
            support.tombstoned = true;
        }
    }
    assert!(matches!(
        build_complete_generation(
            Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
            input.clone()
        ),
        Err(KnowledgeGenerationErrorV2::UnknownEdgeNode)
    ));
    for edge in &mut input.edges {
        for support in &mut edge.supports {
            support.tombstoned = true;
        }
    }
    let withdrawn = build(input);
    assert!(withdrawn.nodes.is_empty());
    assert!(withdrawn.edges.is_empty());
}

#[test]
fn view_cannot_satisfy_another_source_cut_or_a_changed_generation_digest() {
    let generation = build(fixture());
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified view: {error}"));
    let mut other = fixture();
    other.source_snapshot_digest = digest("owner:another-owner:source-cut");
    let different = build(other);
    assert!(matches!(
        verified.query_relations(request(&different)),
        Err(KnowledgeGenerationErrorV2::DigestMismatch(
            "query_generation"
        ))
    ));
    let mut mutated = generation;
    mutated.nodes[0].payload_digest = digest("mutated payload");
    assert!(VerifiedKnowledgeGenerationV2::new(mutated).is_err());
}
