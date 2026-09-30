//! External-query resource admission and failure-classification contract.
use codex_hepta_kg::DEFAULT_QUERY_SUPPORT_WORK_V2;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeGenerationErrorV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeQueryAdmissionErrorV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::MAX_QUERY_SUPPORT_WORK_V2;
use codex_hepta_kg::VerifiedKnowledgeGenerationV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::query_relations_reference_unbounded;
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

fn support(value: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(value),
        source_revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
        source_fact_digest: digest(value),
        validity_digest: digest(&format!("validity:{value}")),
        valid_from_unix_seconds: Some(0),
        valid_to_unix_seconds: Some(100),
        tombstoned: false,
    }
}

fn fixture() -> codex_hepta_kg::KnowledgeGenerationV2 {
    build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("source-cut"),
            generation_vector_digest: digest("generation-vector"),
            graph_profile_digest: digest("graph-profile"),
            complete_source_cut: true,
            nodes: vec![
                KnowledgeNodeV2 {
                    node_id: id("node:a"),
                    node_kind_id: id("kind:entity"),
                    payload_digest: digest("payload:a"),
                    supports: vec![support("source:node:a")],
                },
                KnowledgeNodeV2 {
                    node_id: id("node:b"),
                    node_kind_id: id("kind:entity"),
                    payload_digest: digest("payload:b"),
                    supports: vec![support("source:node:b")],
                },
            ],
            edges: vec![KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: id("node:a"),
                    relation: KnowledgeRelationKindV2::Supports,
                    target_node_id: id("node:b"),
                },
                confidence: ProbabilityQ32::from_raw(1_u64 << 31)
                    .unwrap_or_else(|error| panic!("confidence: {error}")),
                validity_digest: digest("edge:a:b"),
                supports: vec![support("source:edge:a:b")],
            }],
        },
    )
    .unwrap_or_else(|error| panic!("valid fixture: {error}"))
}

fn query(
    generation: &codex_hepta_kg::KnowledgeGenerationV2,
    seed: &str,
) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:resource-contract"),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id(seed)],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: Some(10),
        maximum_edges: 8,
    }
}

#[test]
fn external_budget_distinguishes_empty_exhausted_invalid_and_unbounded() {
    assert!(DEFAULT_QUERY_SUPPORT_WORK_V2 > 0);
    assert!(DEFAULT_QUERY_SUPPORT_WORK_V2 <= MAX_QUERY_SUPPORT_WORK_V2);

    let generation = fixture();
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified view: {error}"));

    let (empty, empty_work) = verified
        .query_relations_external(query(&generation, "node:missing"), Some(1))
        .unwrap_or_else(|error| panic!("a true empty result is successful: {error}"));
    assert!(empty.edges.is_empty());
    assert_eq!(empty.omitted_count, 0);
    assert_eq!(empty_work.relation_edges_scanned, 0);

    assert!(matches!(
        verified.query_relations_external(query(&generation, "node:a"), Some(1)),
        Err(KnowledgeQueryAdmissionErrorV2::BudgetExceeded {
            maximum_support_work: 1,
            attempted_support_work: 2,
        })
    ));
    assert!(matches!(
        verified.query_relations_external(
            query(&generation, "node:a"),
            Some(MAX_QUERY_SUPPORT_WORK_V2 + 1),
        ),
        Err(KnowledgeQueryAdmissionErrorV2::InvalidBudget {
            requested_support_work,
            maximum_support_work,
        }) if requested_support_work == MAX_QUERY_SUPPORT_WORK_V2 + 1
            && maximum_support_work == MAX_QUERY_SUPPORT_WORK_V2
    ));

    let bounded = verified
        .query_relations_external(query(&generation, "node:a"), None)
        .unwrap_or_else(|error| panic!("default bounded query: {error}"))
        .0;
    let reference = query_relations_reference_unbounded(&generation, query(&generation, "node:a"))
        .unwrap_or_else(|error| panic!("explicit unbounded oracle: {error}"));
    assert_eq!(bounded, reference);

    assert!(matches!(
        verified.query_relations_with_work_budget(query(&generation, "node:a"), 1),
        Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
    ));
}
