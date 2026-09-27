use super::GraphBoundPromptPortfolioReceipt;
use super::optimize_with_factor_graph;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_kg::PromptFactorProjectionV1;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::compat::CandidateDisposition;
use crate::compat::Error;
use crate::compat::OptimizationRequest;
use crate::compat::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn graph() -> PromptFactorProjectionV1 {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("temporary: {error}"));
    let mut durable = DurablePromptRegistry::open_state_dir(&temporary.path().join("registry"), 64)
        .unwrap_or_else(|error| panic!("registry: {error}"));
    let key = SigningKey::from_bytes(&[41; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temporary.path().join("authority"), "authority:graph-fixture".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations { authority_epoch: 1, revision: 1, revoked_grant_ids: BTreeSet::new() },
    ).unwrap_or_else(|error| panic!("authority: {error}"));
    let now = SystemTime::now().duration_since(UNIX_EPOCH)
        .unwrap_or_else(|error| panic!("clock: {error}")).as_millis() as u64;
    let scope = digest("scope:graph-fixture");
    for (index, name) in ["factor:a", "factor:b", "factor:c"].into_iter().enumerate() {
        let factor = PromptFactor {
            factor_id: id(name), proposer_id: id("proposer:graph-fixture"),
            semantic_version: id("v1"), semantic_purpose: "inspect evidence".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest(name), source: FactorSource::GovernedInternal, lifecycle: Lifecycle::Draft,
        };
        durable.register_factor(factor.clone()).unwrap_or_else(|error| panic!("factor: {error}"));
        let evidence = digest(&format!("admission:{name}"));
        let grant = FinalUseGrant {
            schema_version: 1, signer_id: "authority:graph-fixture".to_owned(), authority_epoch: 1,
            grant_id: format!("grant:graph-fixture:{index}"), nonce: [index as u8 + 41; 32],
            binding: final_use_admission_binding(&factor, &id("reviewer:graph-fixture"), scope, evidence)
                .unwrap_or_else(|error| panic!("binding: {error}")),
            not_before_unix_ms: now.saturating_sub(1_000), expires_at_unix_ms: now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: key.sign(&grant.signing_bytes().unwrap_or_else(|error| panic!("bytes: {error}"))).to_bytes().to_vec(), grant,
        };
        durable.admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
            .unwrap_or_else(|error| panic!("admit: {error}"));
    }
    // Arithmetic fixture uses a pure copy of genuinely admitted registry facts.
    let mut registry = durable.registry().unwrap_or_else(|error| panic!("registry: {error}")).clone();
    for (name, left, right, kind) in [
        ("conflict", "factor:a", "factor:b", PromptFactorRelationKind::Conflicts),
        ("complement", "factor:a", "factor:c", PromptFactorRelationKind::Complements),
        ("substitute", "factor:b", "factor:c", PromptFactorRelationKind::Substitutes),
    ] {
        registry.register_factor_relation(PromptFactorRelation {
            relation_id: id(&format!("relation:{name}")), left_factor_id: id(left), right_factor_id: id(right),
            kind, evidence_digest: digest(&format!("relation-evidence:{name}")),
        }).unwrap_or_else(|error| panic!("relation: {error}"));
    }
    build_prompt_factor_projection_v1(
        Generation::new(1).unwrap_or_else(|error| panic!("generation: {error}")),
        digest("prompt-generation-vector"), &registry.factor_graph_source_v1(),
    ).unwrap_or_else(|error| panic!("projection: {error}"))
}
fn candidate(name: &str, factor: &str, gain: i64, registry_digest: Digest32) -> PromptCandidate {
    PromptCandidate {
        candidate_id: id(name), factor_id: id(factor), realization_id: id(&format!("realization:{name}")),
        admitted: true, legal: true, expected_gain: FixedQ32::from_raw(gain), cost: 1,
        registry_digest, support_digest: digest(&format!("candidate-support:{name}")),
    }
}
fn select(graph: &PromptFactorProjectionV1, candidates: Vec<PromptCandidate>, budget: u64)
    -> Result<GraphBoundPromptPortfolioReceipt, Error> {
    optimize_with_factor_graph(OptimizationRequest {
        decision_id: id("decision:graph"), objective_digest: digest("objective"),
        registry_snapshot_digest: graph.registry_snapshot_digest(), budget, maximum_selected: 3, candidates,
    }, graph)
}

#[test]
fn graph_conflicts_are_hard_constraints_and_receipt_binds_relation_view() {
    let graph = graph();
    let registry = graph.registry_snapshot_digest();
    let receipt = select(&graph, vec![candidate("candidate:a", "factor:a", 30, registry),
        candidate("candidate:b", "factor:b", 20, registry), candidate("candidate:c", "factor:c", 10, registry)], 3)
        .unwrap_or_else(|error| panic!("selection: {error}"));
    assert_eq!(receipt.portfolio.selected, vec![id("candidate:a"), id("candidate:c")]);
    assert_eq!(receipt.observed_relation_count, 3);
    assert_eq!(receipt.observed_complement_count, 1);
    assert_eq!(receipt.observed_substitute_count, 1);
    assert_eq!(receipt.observed_conflict_count, 1);
    assert!(!receipt.relation_request_digest.is_zero());
    assert_eq!(receipt.factor_graph_generation_digest, graph.generation().generation_digest);
    assert_eq!(receipt.portfolio.total_expected_gain, FixedQ32::from_raw(40));
    assert!(receipt.portfolio.decisions.iter().any(|row| row.candidate_id == id("candidate:b")
        && row.disposition == CandidateDisposition::GraphConflict));
    receipt.validate().unwrap_or_else(|error| panic!("receipt: {error}"));
    assert!(!receipt.authority.grants_any());
}
#[test]
fn candidate_factor_missing_from_complete_graph_fails_closed() {
    let graph = graph();
    let result = select(&graph, vec![candidate("candidate:x", "factor:x", 10, graph.registry_snapshot_digest())], 1);
    assert!(matches!(result, Err(Error::FactorGraph(message)) if message.contains("factor:x")));
}
#[test]
fn registry_snapshot_drift_fails_closed_before_selection() {
    let graph = graph();
    let result = optimize_with_factor_graph(OptimizationRequest {
        decision_id: id("decision:stale"), objective_digest: digest("objective"),
        registry_snapshot_digest: digest("other-registry"), budget: 1, maximum_selected: 1,
        candidates: vec![candidate("candidate:a", "factor:a", 10, graph.registry_snapshot_digest())],
    }, &graph);
    assert!(matches!(result, Err(Error::FactorGraph(message)) if message.contains("registry snapshot")));
}
#[test]
fn graph_substitutes_are_hard_redundancy_constraints() {
    let graph = graph();
    let registry = graph.registry_snapshot_digest();
    let receipt = select(&graph, vec![candidate("candidate:b", "factor:b", 20, registry),
        candidate("candidate:c", "factor:c", 10, registry)], 2).unwrap_or_else(|error| panic!("selection: {error}"));
    assert_eq!(receipt.portfolio.selected, vec![id("candidate:b")]);
    assert_eq!(receipt.observed_substitute_count, 1);
    assert!(receipt.portfolio.decisions.iter().any(|row| row.candidate_id == id("candidate:c")
        && row.disposition == CandidateDisposition::GraphSubstitute));
}
