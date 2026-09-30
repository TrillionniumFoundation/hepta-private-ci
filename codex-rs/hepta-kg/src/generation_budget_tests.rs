use super::*;
use crate::generation::tests::digest;
use crate::generation::tests::edge;
use crate::generation::tests::generation;
use crate::generation::tests::input;
use crate::generation::tests::node;
use crate::generation::tests::support;

#[test]
fn budget_counts_the_actual_length_framed_encoding() {
    let mut a = node("a", "payload");
    a.supports[0].valid_from_unix_seconds = Some(i64::MIN);
    a.supports[0].valid_to_unix_seconds = Some(i64::MAX);
    let graph = build_complete_generation(
        generation(1),
        input(
            vec![a, node("b", "payload")],
            vec![edge(
                "a",
                "b",
                KnowledgeRelationKindV2::Custom(StableId::new("custom:kind").expect("id")),
                "ab",
            )],
        ),
    )
    .expect("fixture");
    let mut bytes = Vec::new();
    bytes.extend_from_slice(GENERATION_DOMAIN);
    push_u64(&mut bytes, graph.generation.get());
    push_digest(&mut bytes, graph.source_snapshot_digest);
    push_digest(&mut bytes, graph.generation_vector_digest);
    push_digest(&mut bytes, graph.graph_profile_digest);
    push_len(&mut bytes, graph.nodes.len());
    for node in &graph.nodes {
        push_id(&mut bytes, &node.node_id);
        push_id(&mut bytes, &node.node_kind_id);
        push_digest(&mut bytes, node.payload_digest);
        push_supports(&mut bytes, &node.supports);
    }
    push_len(&mut bytes, graph.edges.len());
    for edge in &graph.edges {
        push_edge_identity(&mut bytes, &edge.identity);
        push_u64(&mut bytes, edge.confidence.raw());
        push_digest(&mut bytes, edge.validity_digest);
        push_supports(&mut bytes, &edge.supports);
    }
    assert_eq!(
        validate_generation_budget(graph.nodes.iter(), graph.edges.iter()),
        Ok(bytes.len())
    );
    assert_eq!(Digest32::of_bytes(&bytes), graph.generation_digest);
}

#[test]
fn aggregate_support_and_byte_limits_reject_the_next_record_without_large_allocations() {
    let supports = [support("last", /*tombstoned*/ false)];
    let mut support_budget = GenerationBudget::new();
    support_budget.supports = MAX_TOTAL_KNOWLEDGE_SUPPORTS_V2 - 1;
    assert_eq!(support_budget.admit_supports(&supports), Ok(()));
    assert_eq!(
        support_budget.admit_supports(&supports),
        Err(KnowledgeGenerationErrorV2::TotalSupportLimitExceeded)
    );

    let mut bytes = Vec::new();
    push_supports(&mut bytes, &supports);
    let mut byte_budget = GenerationBudget::new();
    byte_budget.canonical_bytes = MAX_KNOWLEDGE_CANONICAL_BYTES_V2 - bytes.len();
    assert_eq!(byte_budget.admit_supports(&supports), Ok(()));
    assert_eq!(
        byte_budget.admit_supports(&supports),
        Err(KnowledgeGenerationErrorV2::CanonicalByteLimitExceeded)
    );

    // A corrupted arithmetic state must fail closed instead of wrapping.
    let mut overflow = GenerationBudget::new();
    overflow.canonical_bytes = usize::MAX;
    assert_eq!(
        overflow.admit_bytes(1),
        Err(KnowledgeGenerationErrorV2::CanonicalByteLimitExceeded)
    );
}

#[test]
fn rejected_raw_support_sets_are_checked_before_sorting_or_revocation() {
    let mut revoked = node("a", "payload");
    revoked.supports =
        vec![support("revoked", /*tombstoned*/ true); MAX_SUPPORTS_PER_RELATION_V2 + 1];
    assert_eq!(
        build_complete_generation(generation(1), input(vec![revoked], Vec::new())),
        Err(KnowledgeGenerationErrorV2::SupportLimitExceeded)
    );
    let mut loaded =
        build_complete_generation(generation(1), input(vec![node("a", "payload")], Vec::new()))
            .expect("fixture");
    loaded.nodes[0].supports =
        vec![support("live", /*tombstoned*/ false); MAX_SUPPORTS_PER_RELATION_V2 + 1];
    loaded.generation_digest = digest("untrusted-recomputed-digest");
    assert_eq!(
        VerifiedKnowledgeGenerationV2::new(loaded).map(|_| ()),
        Err(KnowledgeGenerationErrorV2::SupportLimitExceeded)
    );
}
