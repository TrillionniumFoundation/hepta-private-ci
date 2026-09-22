use super::*;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use crate::CandidateDisposition;
use crate::OptimizationRequest;
use crate::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn register_admitted_factor(registry: &mut PromptRegistry, factor_id: &str) {
    let factor_id = id(factor_id);
    registry
        .register_factor(PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id("proposer:graph-tests"),
            semantic_version: id("semantic:v1"),
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
    let mut registry = PromptRegistry::new(32).expect("registry");
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

#[test]
fn graph_conflicts_are_hard_constraints_and_receipt_binds_relation_view() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:graph"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 3,
        maximum_selected: 3,
        candidates: vec![
            candidate("candidate:a", "factor:a", 30, registry_digest),
            candidate("candidate:b", "factor:b", 20, registry_digest),
            candidate("candidate:c", "factor:c", 10, registry_digest),
        ],
    };
    let receipt = optimize_with_factor_graph(request, &factor_graph).expect("graph optimize");
    assert_eq!(
        receipt.portfolio.selected,
        vec![id("candidate:a"), id("candidate:c")]
    );
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
