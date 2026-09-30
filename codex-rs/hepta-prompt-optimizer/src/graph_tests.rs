use super::*;
use codex_hepta_kg::KnowledgePhysicalQueryErrorV2;
use codex_hepta_kg::KnowledgeQueryAdmissionErrorV2;
use codex_hepta_kg::KnowledgeResourceErrorCodeV2;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::fixture::PromptRegistryFixture;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use crate::CandidateDisposition;
use crate::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn register_admitted_factor(registry: &mut PromptRegistryFixture, factor_id: &str) {
    let factor_id = id(factor_id);
    registry
        .register_factor(PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id("proposer:graph-tests"),
            semantic_version: id("semantic:v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest(&format!("factor-content:{factor_id}")),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        })
        .expect("register factor");
    registry
        .admit_factor(
            &factor_id,
            &id("reviewer:graph-tests"),
            digest(&format!("factor-admission:{factor_id}")),
        )
        .expect("admit factor");
}

fn graph() -> PromptFactorProjectionV1 {
    let mut registry = PromptRegistryFixture::new(32).expect("registry");
    for factor_id in ["factor:a", "factor:b", "factor:c"] {
        register_admitted_factor(&mut registry, factor_id);
    }
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a-b-conflict"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("evidence:a-b-conflict"),
        })
        .expect("register conflict");
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a-c-complement"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:c"),
            kind: PromptFactorRelationKind::Complements,
            evidence_digest: digest("evidence:a-c-complement"),
        })
        .expect("register complement");
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:b-c-substitute"),
            left_factor_id: id("factor:b"),
            right_factor_id: id("factor:c"),
            kind: PromptFactorRelationKind::Substitutes,
            evidence_digest: digest("evidence:b-c-substitute"),
        })
        .expect("register substitute");
    let source = registry.factor_graph_source_v1();
    build_prompt_factor_projection_v1(
        Generation::new(1).expect("generation"),
        digest("prompt-generation-vector"),
        &source,
    )
    .expect("factor graph")
}

fn candidate(name: &str, factor_id: &str, gain: i64, registry_digest: Digest32) -> PromptCandidate {
    PromptCandidate {
        candidate_id: id(name),
        factor_id: id(factor_id),
        realization_id: id(&format!("realization:{name}")),
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost: 1,
        registry_digest,
        support_digest: digest(&format!("candidate-support:{name}")),
    }
}

fn full_request(factor_graph: &PromptFactorProjectionV1, decision_id: &str) -> OptimizationRequest {
    let registry_digest = factor_graph.registry_snapshot_digest();
    OptimizationRequest {
        decision_id: id(decision_id),
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 3,
        maximum_selected: 3,
        candidates: vec![
            candidate("candidate:a", "factor:a", 30, registry_digest),
            candidate("candidate:b", "factor:b", 20, registry_digest),
            candidate("candidate:c", "factor:c", 10, registry_digest),
        ],
    }
}

#[test]
fn graph_conflicts_are_hard_constraints_and_receipt_binds_physical_relation_view() {
    let factor_graph = graph();
    let request = full_request(&factor_graph, "decision:graph");
    let receipt = optimize_with_factor_graph(request, &factor_graph).expect("graph optimize");
    assert_eq!(
        receipt.portfolio.selected,
        vec![id("candidate:a"), id("candidate:c")]
    );
    assert_eq!(receipt.relation_support_work, 3);
    assert_eq!(
        receipt.relation_support_work_budget,
        DEFAULT_QUERY_SUPPORT_WORK_V2
    );
    assert!(receipt.factor_graph_generation_bytes > 0);
    assert!(receipt.relation_output_bytes > 0);
    assert_eq!(receipt.observed_relation_count, 3);
    assert_eq!(receipt.observed_complement_count, 1);
    assert_eq!(receipt.observed_substitute_count, 1);
    assert_eq!(receipt.observed_conflict_count, 1);
    assert!(!receipt.relation_request_digest.is_zero());
    assert_eq!(
        receipt.factor_graph_generation_digest,
        factor_graph.generation().generation_digest
    );
    assert_eq!(
        receipt.portfolio.total_expected_gain,
        FixedQ32::from_raw(40)
    );
    assert!(receipt.portfolio.decisions.iter().any(|decision| {
        decision.candidate_id == id("candidate:b")
            && decision.disposition == CandidateDisposition::GraphConflict
    }));
    receipt.validate().expect("bound receipt");
    assert!(!receipt.authority.grants_any());
}

#[test]
fn graph_receipt_rejects_tampered_physical_observations() {
    let factor_graph = graph();
    let mut receipt = optimize_with_factor_graph(
        full_request(&factor_graph, "decision:physical-tamper"),
        &factor_graph,
    )
    .expect("graph optimize");

    receipt.factor_graph_generation_bytes = 0;
    receipt.receipt_digest = receipt.compute_receipt_digest();
    assert!(receipt.validate().is_err());

    receipt.factor_graph_generation_bytes = factor_graph.generation_usage().canonical_bytes;
    receipt.relation_output_bytes = 0;
    receipt.receipt_digest = receipt.compute_receipt_digest();
    assert!(receipt.validate().is_err());
}

#[test]
fn factor_projection_bounded_query_distinguishes_exhaustion_from_empty() {
    let factor_graph = graph();
    let exhausted = factor_graph
        .query_relations_external(
            KnowledgeRelationQueryV2 {
                query_id: id("query:factor-budget-exhaustion"),
                generation_digest: factor_graph.generation().generation_digest,
                seed_node_ids: vec![id("factor:a"), id("factor:b"), id("factor:c")],
                relation_kinds: vec![
                    KnowledgeRelationKindV2::PromptComplements,
                    KnowledgeRelationKindV2::PromptSubstitutes,
                    KnowledgeRelationKindV2::PromptConflicts,
                ],
                valid_at_unix_seconds: None,
                maximum_edges: 3,
            },
            Some(1),
        )
        .expect_err("one support-work unit cannot copy all factor relations");
    assert!(matches!(
        exhausted,
        KnowledgePhysicalQueryErrorV2::Admission(KnowledgeQueryAdmissionErrorV2::BudgetExceeded {
            maximum_support_work: 1,
            ..
        })
    ));

    let (empty, observation) = factor_graph
        .query_relations_external(
            KnowledgeRelationQueryV2 {
                query_id: id("query:factor-empty"),
                generation_digest: factor_graph.generation().generation_digest,
                seed_node_ids: vec![id("factor:a")],
                relation_kinds: vec![KnowledgeRelationKindV2::PromptDominates],
                valid_at_unix_seconds: None,
                maximum_edges: 3,
            },
            None,
        )
        .expect("true empty result remains a successful bounded query");
    assert!(empty.edges.is_empty());
    assert_eq!(empty.omitted_count, 0);
    assert_eq!(observation.work.selected_supports_cloned, 0);
    assert!(observation.output_bytes > 0);
}

#[test]
fn optimizer_propagates_cancellation_as_a_stable_resource_error() {
    let factor_graph = graph();
    let cancellation = KnowledgeCancellationV2::default();
    let guard = KnowledgeOperationGuardV2::unbounded(cancellation.clone());
    cancellation.cancel();

    let error = optimize_with_factor_graph_guarded(
        full_request(&factor_graph, "decision:cancelled"),
        &factor_graph,
        &guard,
    )
    .expect_err("cancelled optimizer query must fail closed");
    assert!(
        matches!(&error, Error::FactorGraph(message)
            if message.contains(KnowledgeResourceErrorCodeV2::Cancelled.as_str())),
        "unexpected error: {error:?}"
    );
}

#[test]
fn candidate_factor_missing_from_complete_graph_fails_closed() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:missing"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate("candidate:x", "factor:x", 10, registry_digest)],
    };
    let error = optimize_with_factor_graph(request, &factor_graph).expect_err("missing factor");
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("factor:x")),
        "unexpected error: {error:?}"
    );
}

#[test]
fn registry_snapshot_drift_fails_closed_before_selection() {
    let factor_graph = graph();
    let request = OptimizationRequest {
        decision_id: id("decision:stale-registry"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("different-registry"),
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate(
            "candidate:a",
            "factor:a",
            10,
            factor_graph.registry_snapshot_digest(),
        )],
    };
    let error = optimize_with_factor_graph(request, &factor_graph).expect_err("stale registry");
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("registry snapshot")),
        "unexpected error: {error:?}"
    );
}

#[test]
fn graph_substitutes_are_hard_redundancy_constraints() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:substitute"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 2,
        maximum_selected: 2,
        candidates: vec![
            candidate("candidate:b", "factor:b", 20, registry_digest),
            candidate("candidate:c", "factor:c", 10, registry_digest),
        ],
    };
    let receipt = optimize_with_factor_graph(request, &factor_graph).expect("graph optimize");
    assert_eq!(receipt.portfolio.selected, vec![id("candidate:b")]);
    assert_eq!(receipt.observed_substitute_count, 1);
    assert!(receipt.portfolio.decisions.iter().any(|decision| {
        decision.candidate_id == id("candidate:c")
            && decision.disposition == CandidateDisposition::GraphSubstitute
    }));
}
