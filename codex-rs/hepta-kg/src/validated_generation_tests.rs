use std::ops::Range;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use super::*;
use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeSupportV2;
use crate::MAX_KNOWLEDGE_NODES_V2;
use crate::build_complete_generation;
use crate::query_relations;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(label: &str, validity: Range<i64>) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(label),
        source_revision: Revision::new(1).expect("valid revision"),
        source_fact_digest: digest(label),
        validity_digest: digest("validity"),
        valid_from_unix_seconds: Some(validity.start),
        valid_to_unix_seconds: Some(validity.end),
        tombstoned: false,
    }
}

fn graph() -> KnowledgeGenerationV2 {
    let nodes = ["node:a", "node:b", "node:c"]
        .into_iter()
        .map(|label| KnowledgeNodeV2 {
            node_id: id(label),
            node_kind_id: id("kind:entity"),
            payload_digest: digest(label),
            supports: vec![support(label, 0..30)],
        })
        .collect();
    let edges = vec![
        KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id("node:a"),
                relation: KnowledgeRelationKindV2::Supports,
                target_node_id: id("node:b"),
            },
            confidence: ProbabilityQ32::ONE,
            validity_digest: digest("validity:ab"),
            supports: vec![
                support("support:ab:early", 10..20),
                support("support:ab:late", 20..40),
            ],
        },
        KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id("node:a"),
                relation: KnowledgeRelationKindV2::Causes,
                target_node_id: id("node:c"),
            },
            confidence: ProbabilityQ32::ONE,
            validity_digest: digest("validity:ac"),
            supports: vec![support("support:ac", 0..50)],
        },
    ];
    build_complete_generation(
        Generation::new(1).expect("valid generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("source:1"),
            generation_vector_digest: digest("vector:1"),
            graph_profile_digest: digest("profile:1"),
            complete_source_cut: true,
            nodes,
            edges,
        },
    )
    .expect("valid graph")
}

fn query(generation: &KnowledgeGenerationV2) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:validated"),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: None,
        maximum_edges: 1,
    }
}

#[test]
fn admitted_queries_match_complete_free_function_results() {
    let generation = graph();
    let validated =
        ValidatedKnowledgeGenerationV2::new(generation.clone()).expect("validated generation");
    assert_eq!(validated.as_generation(), &generation);
    for valid_at in [
        None,
        Some(9),
        Some(10),
        Some(19),
        Some(20),
        Some(29),
        Some(30),
    ] {
        for maximum_edges in [1, 2] {
            for relation_kinds in [Vec::new(), vec![KnowledgeRelationKindV2::Supports]] {
                let mut request = query(&generation);
                request.valid_at_unix_seconds = valid_at;
                request.maximum_edges = maximum_edges;
                request.relation_kinds = relation_kinds;
                assert_eq!(
                    validated.query_relations(request.clone()),
                    query_relations(&generation, request)
                );
            }
        }
    }
}

#[test]
fn admitted_queries_preserve_complete_request_digest_binding() {
    let validated = ValidatedKnowledgeGenerationV2::new(graph()).expect("validated graph");
    let baseline_request = query(validated.as_generation());
    let baseline = validated
        .query_relations(baseline_request.clone())
        .expect("baseline query");
    let mut changed_seed = baseline_request.clone();
    changed_seed.seed_node_ids.push(id("node:b"));
    let mut changed_limit = baseline_request;
    changed_limit.maximum_edges = 2;
    for changed in [changed_seed, changed_limit] {
        let result = validated
            .query_relations(changed.clone())
            .expect("changed query");
        assert_eq!(
            result,
            query_relations(validated.as_generation(), changed).expect("validating query")
        );
        assert_ne!(result.request_digest, baseline.request_digest);
        assert_ne!(result.result_digest, baseline.result_digest);
    }
}

#[test]
fn malformed_generations_cannot_enter_an_admitted_reader() {
    let mut tampered = graph();
    tampered.nodes[0].payload_digest = digest("rewritten-payload");
    assert_eq!(
        ValidatedKnowledgeGenerationV2::new(tampered),
        Err(KnowledgeGenerationErrorV2::DigestMismatch("generation"))
    );
    let mut reordered = graph();
    reordered.edges.reverse();
    reordered.generation_digest = super::super::compute_generation_digest(&reordered);
    assert_eq!(
        ValidatedKnowledgeGenerationV2::new(reordered),
        Err(KnowledgeGenerationErrorV2::NonCanonicalEdgeOrder)
    );
}

#[test]
fn admitted_queries_reject_stale_duplicate_and_oversized_requests() {
    let validated = ValidatedKnowledgeGenerationV2::new(graph()).expect("validated graph");
    let baseline = query(validated.as_generation());
    let mut stale = baseline.clone();
    stale.generation_digest = digest("generation:stale");
    let mut duplicate_seeds = baseline.clone();
    duplicate_seeds.seed_node_ids.push(id("node:a"));
    let mut duplicate_kinds = baseline.clone();
    duplicate_kinds.relation_kinds = vec![KnowledgeRelationKindV2::Supports; 2];
    let mut zero_limit = baseline.clone();
    zero_limit.maximum_edges = 0;
    let mut oversized_seeds = baseline;
    oversized_seeds.seed_node_ids = vec![id("node:a"); MAX_KNOWLEDGE_NODES_V2 + 1];
    for (request, expected) in [
        (
            stale,
            KnowledgeGenerationErrorV2::DigestMismatch("query_generation"),
        ),
        (
            duplicate_seeds,
            KnowledgeGenerationErrorV2::DuplicateDeltaIdentity,
        ),
        (
            duplicate_kinds,
            KnowledgeGenerationErrorV2::DuplicateRelationKind,
        ),
        (zero_limit, KnowledgeGenerationErrorV2::InvalidQueryLimit),
        (
            oversized_seeds,
            KnowledgeGenerationErrorV2::QueryInputLimitExceeded,
        ),
    ] {
        assert_eq!(validated.query_relations(request.clone()), Err(expected));
        assert_eq!(
            validated.query_relations(request.clone()),
            query_relations(validated.as_generation(), request)
        );
    }
}
