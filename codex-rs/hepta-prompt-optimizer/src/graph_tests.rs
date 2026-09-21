use super::*;
use codex_hepta_kg::KnowledgeEdgeIdentityV2;
use codex_hepta_kg::KnowledgeEdgeV2;
use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

use crate::CandidateDisposition;
use crate::OptimizationRequest;
use crate::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(label: &str) -> KnowledgeSupportV2 {
    KnowledgeSupportV2 {
        source_id: id(&format!("support:{label}")),
        source_revision: Revision::new(1).expect("revision"),
        source_fact_digest: digest(&format!("fact:{label}")),
        validity_digest: digest(&format!("validity:{label}")),
        valid_from_unix_seconds: None,
        valid_to_unix_seconds: None,
        tombstoned: false,
    }
}

fn node(factor_id: &str) -> KnowledgeNodeV2 {
    KnowledgeNodeV2 {
        node_id: id(factor_id),
        node_kind_id: id("kind:prompt-factor"),
        payload_digest: digest(&format!("payload:{factor_id}")),
        supports: vec![support(factor_id)],
    }
}

fn edge(
    left: &str,
    right: &str,
    relation: KnowledgeRelationKindV2,
    label: &str,
) -> KnowledgeEdgeV2 {
    KnowledgeEdgeV2 {
        identity: KnowledgeEdgeIdentityV2 {
            source_node_id: id(left),
            relation,
            target_node_id: id(right),
        },
        confidence: ProbabilityQ32::ONE,
        validity_digest: digest(&format!("edge-validity:{label}")),
        supports: vec![support(label)],
    }
}

fn graph() -> PromptFactorProjectionV1 {
    let generation = build_complete_generation(
        Generation::new(1).expect("generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: digest("prompt-registry-source"),
            generation_vector_digest: digest("prompt-generation-vector"),
            graph_profile_digest: digest("prompt-graph-profile"),
            complete_source_cut: true,
            nodes: vec![node("factor:a"), node("factor:b"), node("factor:c")],
            edges: vec![
                edge(
                    "factor:a",
                    "factor:b",
                    KnowledgeRelationKindV2::PromptConflicts,
                    "a-b-conflict",
                ),
                edge(
                    "factor:a",
                    "factor:c",
                    KnowledgeRelationKindV2::PromptComplements,
                    "a-c-complement",
                ),
            ],
        },
    )
    .expect("factor graph");
    PromptFactorProjectionV1 {
        registry_revision: 1,
        registry_snapshot_digest: digest("registry"),
        source_digest: generation.source_snapshot_digest,
        generation,
        authority: AuthorityPosture::DENY_ALL,
    }
}
fn candidate(name: &str, factor_id: &str, gain: i64) -> PromptCandidate {
    PromptCandidate {
        candidate_id: id(name),
        factor_id: id(factor_id),
        realization_id: id(&format!("realization:{name}")),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost: 1,
        registry_digest: digest("registry"),
        support_digest: digest(&format!("candidate-support:{name}")),
    }
}

#[test]
fn graph_conflicts_are_hard_constraints_and_receipt_binds_relation_view() {
    let request = OptimizationRequest {
        decision_id: id("decision:graph"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("registry"),
        budget: 3,
        maximum_selected: 3,
        candidates: vec![
            candidate("candidate:a", "factor:a", 30),
            candidate("candidate:b", "factor:b", 20),
            candidate("candidate:c", "factor:c", 10),
        ],
    };
    let factor_graph = graph();
    let receipt = optimize_with_factor_graph(request, &factor_graph).expect("graph optimize");
    assert_eq!(
        receipt.portfolio.selected,
        vec![id("candidate:a"), id("candidate:c")]
    );
    assert_eq!(receipt.observed_relation_count, 2);
    assert_eq!(
        receipt.factor_graph_generation_digest,
        factor_graph.generation.generation_digest
    );
    assert!(receipt
        .portfolio
        .decisions
        .iter()
        .any(|decision| {
            decision.candidate_id == id("candidate:b")
                && decision.disposition == CandidateDisposition::GraphConflict
        }));
    receipt.validate().expect("bound receipt");
    assert!(!receipt.authority.grants_any());
}

#[test]
fn candidate_factor_missing_from_complete_graph_fails_closed() {
    let request = OptimizationRequest {
        decision_id: id("decision:missing"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("registry"),
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate("candidate:x", "factor:x", 10)],
    };
    let error = optimize_with_factor_graph(request, &graph()).expect_err("missing factor");
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("factor:x")),
        "unexpected error: {error:?}"
    );
}


#[test]
fn registry_snapshot_drift_fails_closed_before_selection() {
    let request = OptimizationRequest {
        decision_id: id("decision:stale-registry"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("different-registry"),
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate("candidate:a", "factor:a", 10)],
    };
    let error = optimize_with_factor_graph(request, &graph()).expect_err("stale registry");
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("registry snapshot")),
        "unexpected error: {error:?}"
    );
}
