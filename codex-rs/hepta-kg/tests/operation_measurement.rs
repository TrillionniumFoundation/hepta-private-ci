//! Operation-boundary measurements for the public knowledge.graph API.
//!
//! These are regression observations, not host-independent latency claims.
use std::time::Instant;

use codex_hepta_kg::DEFAULT_QUERY_SUPPORT_WORK_V2;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionDeltaV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::MAX_QUERY_SUPPORT_WORK_V2;
use codex_hepta_kg::VerifiedKnowledgeGenerationV2;
use codex_hepta_kg::apply_incremental_delta;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_kg::publish_generation;
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
        source_revision: Revision::new(1)
            .unwrap_or_else(|error| panic!("revision: {error}")),
        source_fact_digest: digest(value),
        validity_digest: digest(&format!("validity:{value}")),
        valid_from_unix_seconds: Some(0),
        valid_to_unix_seconds: Some(10_000),
        tombstoned: false,
    }
}

fn input() -> KnowledgeProjectionInputV2 {
    let nodes = (0..128)
        .map(|index| KnowledgeNodeV2 {
            node_id: id(&format!("node:{index:03}")),
            node_kind_id: id("kind:entity"),
            payload_digest: digest(&format!("payload:{index}")),
            supports: vec![support(&format!("source:node:{index}"))],
        })
        .collect::<Vec<_>>();
    let edges = (0..127)
        .map(|index| KnowledgeEdgeV2 {
            identity: KnowledgeEdgeIdentityV2 {
                source_node_id: id(&format!("node:{index:03}")),
                relation: KnowledgeRelationKindV2::Supports,
                target_node_id: id(&format!("node:{:03}", index + 1)),
            },
            confidence: ProbabilityQ32::from_raw(1_u64 << 31)
                .unwrap_or_else(|error| panic!("confidence: {error}")),
            validity_digest: digest(&format!("edge:{index}")),
            supports: vec![support(&format!("source:edge:{index}"))],
        })
        .collect();
    KnowledgeProjectionInputV2 {
        source_snapshot_digest: digest("source-cut:1"),
        generation_vector_digest: digest("generation-vector:1"),
        graph_profile_digest: digest("graph-profile"),
        complete_source_cut: true,
        nodes,
        edges,
    }
}

#[test]
fn public_operation_boundaries_emit_nonzero_regression_metrics() {
    let original = input();

    let started = Instant::now();
    let cloned = original.clone();
    let input_clone_ns = started.elapsed().as_nanos();

    let started = Instant::now();
    let predecessor = build_complete_generation(
        Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
        cloned,
    )
    .unwrap_or_else(|error| panic!("build, validate and seal: {error}"));
    let build_validate_seal_ns = started.elapsed().as_nanos();

    let started = Instant::now();
    let generation = apply_incremental_delta(
        &predecessor,
        Generation::new(2).unwrap_or_else(|error| panic!("next generation: {error}")),
        KnowledgeProjectionDeltaV2 {
            expected_predecessor_digest: predecessor.generation_digest,
            source_snapshot_digest: digest("source-cut:2"),
            generation_vector_digest: digest("generation-vector:2"),
            graph_profile_digest: predecessor.graph_profile_digest,
            remove_node_ids: Vec::new(),
            upsert_nodes: Vec::new(),
            remove_edge_identities: Vec::new(),
            upsert_edges: Vec::new(),
        },
    )
    .unwrap_or_else(|error| panic!("bounded generation update: {error}"));
    let generation_update_ns = started.elapsed().as_nanos();

    let started = Instant::now();
    let verified = VerifiedKnowledgeGenerationV2::new(generation.clone())
        .unwrap_or_else(|error| panic!("verified query view: {error}"));
    let verified_view_build_ns = started.elapsed().as_nanos();

    let query = KnowledgeRelationQueryV2 {
        query_id: id("query:operation-metrics"),
        generation_digest: generation.generation_digest,
        seed_node_ids: vec![id("node:000")],
        relation_kinds: Vec::new(),
        valid_at_unix_seconds: Some(100),
        maximum_edges: 8,
    };

    let started = Instant::now();
    let cold = verified
        .query_relations_external(query.clone(), None)
        .unwrap_or_else(|error| panic!("cold bounded query: {error}"))
        .0;
    let cold_bounded_query_ns = started.elapsed().as_nanos();
    assert_eq!(cold.edges.len(), 1);

    let iterations = 128_u64;
    let started = Instant::now();
    for _ in 0..iterations {
        let result = verified
            .query_relations_external(query.clone(), None)
            .unwrap_or_else(|error| panic!("hot bounded query: {error}"))
            .0;
        assert_eq!(result, cold);
    }
    let hot_bounded_query_total_ns = started.elapsed().as_nanos();

    let started = Instant::now();
    let reference = query_relations_reference_unbounded(&generation, query)
        .unwrap_or_else(|error| panic!("explicit unbounded reference query: {error}"));
    let unbounded_reference_query_ns = started.elapsed().as_nanos();
    assert_eq!(reference, cold);

    let started = Instant::now();
    let receipt = publish_generation(Some(&predecessor), &generation)
        .unwrap_or_else(|error| panic!("publication receipt: {error}"));
    receipt
        .validate()
        .unwrap_or_else(|error| panic!("valid publication receipt: {error}"));
    let publication_receipt_ns = started.elapsed().as_nanos();

    for value in [
        input_clone_ns,
        build_validate_seal_ns,
        generation_update_ns,
        verified_view_build_ns,
        cold_bounded_query_ns,
        hot_bounded_query_total_ns,
        unbounded_reference_query_ns,
        publication_receipt_ns,
    ] {
        assert!(value > 0);
    }

    println!(
        "HEPTA_KG_OPERATION_METRICS={{\"schema\":\"hepta.knowledge-graph-operation-metrics.v2\",\"inputCloneNs\":{input_clone_ns},\"buildValidateSealNs\":{build_validate_seal_ns},\"generationUpdateNs\":{generation_update_ns},\"verifiedViewBuildNs\":{verified_view_build_ns},\"coldBoundedQueryNs\":{cold_bounded_query_ns},\"hotBoundedQueryTotalNs\":{hot_bounded_query_total_ns},\"unboundedReferenceQueryNs\":{unbounded_reference_query_ns},\"publicationReceiptNs\":{publication_receipt_ns},\"iterations\":{iterations},\"defaultSupportWork\":{DEFAULT_QUERY_SUPPORT_WORK_V2},\"maximumSupportWork\":{MAX_QUERY_SUPPORT_WORK_V2}}}"
    );
}
