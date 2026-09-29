use super::*;
use crate::KnowledgeEdgeIdentityV2;
use crate::KnowledgeEdgeV2;
use crate::KnowledgeNodeV2;
use crate::KnowledgeProjectionInputV2;
use crate::KnowledgeRelationKindV2;
use crate::KnowledgeResourceErrorCodeV2;
use crate::KnowledgeSupportV2;
use crate::build_complete_generation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use std::time::Instant;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn support(value: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(value),
        source_revision: Revision::new(1).expect("test revision"),
        source_fact_digest: Digest32::of_bytes(value.as_bytes()),
        validity_digest: Digest32::of_bytes(format!("valid:{value}").as_bytes()),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

fn generation() -> KnowledgeGenerationV2 {
    let result = build_complete_generation(
        Generation::new(1).expect("test generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(b"snapshot"),
            generation_vector_digest: Digest32::of_bytes(b"vector"),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: vec![
                KnowledgeNodeV2 {
                    node_id: id("node:a"),
                    node_kind_id: id("kind:test"),
                    payload_digest: Digest32::of_bytes(b"payload:a"),
                    supports: vec![support("support:a")],
                },
                KnowledgeNodeV2 {
                    node_id: id("node:b"),
                    node_kind_id: id("kind:test"),
                    payload_digest: Digest32::of_bytes(b"payload:b"),
                    supports: vec![support("support:b")],
                },
            ],
            edges: vec![KnowledgeEdgeV2 {
                identity: KnowledgeEdgeIdentityV2 {
                    source_node_id: id("node:a"),
                    relation: KnowledgeRelationKindV2::Supports,
                    target_node_id: id("node:b"),
                },
                confidence: ProbabilityQ32::ONE,
                validity_digest: Digest32::of_bytes(b"edge-validity"),
                supports: vec![support("support:edge")],
            }],
        },
    );
    result.expect("test generation must build")
}

fn query(view: &KnowledgePhysicalQueryViewV2) -> KnowledgeRelationQueryV2 {
    KnowledgeRelationQueryV2 {
        query_id: id("query:physical"),
        generation_digest: view.generation().generation_digest,
        seed_node_ids: vec![id("node:a")],
        relation_kinds: vec![KnowledgeRelationKindV2::Supports],
        valid_at_unix_seconds: None,
        maximum_edges: 8,
    }
}

#[test]
fn construction_rejects_generation_byte_overflow() {
    let limits = KnowledgePhysicalLimitsV2 {
        maximum_generation_bytes: 0,
        ..KnowledgePhysicalLimitsV2::default()
    };
    let result = KnowledgePhysicalQueryViewV2::new(generation(), limits);
    let Err(KnowledgePhysicalQueryErrorV2::Resource(error)) = result else {
        panic!("generation byte overflow must fail");
    };
    assert_eq!(
        error.code,
        KnowledgeResourceErrorCodeV2::GenerationBytesExceeded
    );
}

#[test]
fn cancelled_query_fails_before_execution() {
    let view =
        KnowledgePhysicalQueryViewV2::new(generation(), KnowledgePhysicalLimitsV2::default())
            .expect("physical query view");
    let cancellation = crate::KnowledgeCancellationV2::default();
    let guard = KnowledgeOperationGuardV2::unbounded(cancellation.clone());
    cancellation.cancel();

    let result = view.query_relations_external(query(&view), None, &guard);
    let Err(KnowledgePhysicalQueryErrorV2::Resource(error)) = result else {
        panic!("cancelled query must fail");
    };
    assert_eq!(error.code, KnowledgeResourceErrorCodeV2::Cancelled);
}

#[test]
fn expired_deadline_fails_before_execution() {
    let view =
        KnowledgePhysicalQueryViewV2::new(generation(), KnowledgePhysicalLimitsV2::default())
            .expect("physical query view");
    let guard = KnowledgeOperationGuardV2::with_deadline(
        Instant::now(),
        crate::KnowledgeCancellationV2::default(),
    );

    let result = view.query_relations_external(query(&view), None, &guard);
    let Err(KnowledgePhysicalQueryErrorV2::Resource(error)) = result else {
        panic!("expired query must fail");
    };
    assert_eq!(error.code, KnowledgeResourceErrorCodeV2::DeadlineExceeded);
}

#[test]
fn query_output_byte_overflow_is_distinct() {
    let limits = KnowledgePhysicalLimitsV2 {
        maximum_query_output_bytes: 0,
        ..KnowledgePhysicalLimitsV2::default()
    };
    let view = KnowledgePhysicalQueryViewV2::new(generation(), limits)
        .expect("generation itself remains within limits");
    let guard =
        KnowledgeOperationGuardV2::unbounded(crate::KnowledgeCancellationV2::default());

    let result = view.query_relations_external(query(&view), None, &guard);
    let Err(KnowledgePhysicalQueryErrorV2::Resource(error)) = result else {
        panic!("query output byte overflow must fail");
    };
    assert_eq!(
        error.code,
        KnowledgeResourceErrorCodeV2::QueryOutputBytesExceeded
    );
}

#[test]
fn accepted_query_reports_generation_and_output_usage() {
    let view =
        KnowledgePhysicalQueryViewV2::new(generation(), KnowledgePhysicalLimitsV2::default())
            .expect("physical query view");
    let guard =
        KnowledgeOperationGuardV2::unbounded(crate::KnowledgeCancellationV2::default());

    let result = view.query_relations_external(query(&view), None, &guard);
    let Ok((relations, observation)) = result else {
        panic!("bounded physical query must succeed");
    };
    assert_eq!(relations.edges.len(), 1);
    assert!(observation.output_bytes > 0);
    assert!(observation.generation_usage.canonical_bytes > 0);
    assert!(observation.work.relation_edges_scanned > 0);
}
