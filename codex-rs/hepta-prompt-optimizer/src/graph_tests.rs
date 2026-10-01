use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_kg::build_prompt_factor_projection_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptFactorRelation;
use codex_hepta_prompt_registry::PromptFactorRelationKind;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_factor_relation_binding;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::CandidateDisposition;
use crate::OptimizationRequest;
use crate::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn signed_grant(binding: FinalUseBinding, key: &SigningKey, grant_id: &str) -> SignedFinalUseGrant {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("time");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:optimizer-graph".to_owned(),
        authority_epoch: 1,
        grant_id: grant_id.to_owned(),
        nonce: digest(grant_id).into_array(),
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    SignedFinalUseGrant {
        signature: key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    }
}

fn graph() -> PromptFactorProjectionV1 {
    let temp = tempfile::tempdir().expect("temp");
    let mut registry =
        DurablePromptRegistry::open_state_dir(&temp.path().join("registry"), 32).expect("registry");
    let key = SigningKey::from_bytes(&[32; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temp.path().join("authority"),
        "review-authority:optimizer-graph".to_owned(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    for factor_id in ["factor:a", "factor:b", "factor:c"] {
        let factor = PromptFactor {
            factor_id: id(factor_id),
            proposer_id: id("proposer:graph-tests"),
            semantic_version: id("semantic:v1"),
            semantic_purpose: "verify factor relation evidence".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest(&format!("factor-content:{factor_id}")),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        registry
            .register_factor(factor.clone())
            .expect("register factor");
        let scope = digest("admission-scope");
        let evidence = digest(&format!("factor-admission:{factor_id}"));
        let signed = signed_grant(
            final_use_admission_binding(&factor, &id("reviewer:graph-tests"), scope, evidence)
                .expect("binding"),
            &key,
            &format!("admission:{factor_id}"),
        );
        registry
            .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
            .expect("admit factor");
    }
    for (left, right, kind, name) in [
        (
            "factor:a",
            "factor:b",
            PromptFactorRelationKind::Conflicts,
            "a-b-conflict",
        ),
        (
            "factor:a",
            "factor:c",
            PromptFactorRelationKind::Complements,
            "a-c-complement",
        ),
        (
            "factor:b",
            "factor:c",
            PromptFactorRelationKind::Substitutes,
            "b-c-substitute",
        ),
    ] {
        let relation = PromptFactorRelation {
            relation_id: id(&format!("relation:{name}")),
            left_factor_id: id(left),
            right_factor_id: id(right),
            kind,
            evidence_digest: digest(&format!("evidence:{name}")),
        };
        let actor = id("reviewer:relation");
        let scope = digest("relation-scope");
        let signed = signed_grant(
            final_use_factor_relation_binding(
                registry.registry().expect("owner view"),
                &actor,
                scope,
                &relation,
            )
            .expect("binding"),
            &key,
            &format!("relation:{name}"),
        );
        registry
            .register_factor_relation_final_use(&authority, &signed, &actor, scope, relation)
            .expect("register relation");
    }
    let source = registry
        .registry()
        .expect("owner view")
        .factor_graph_source_v1();
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

#[test]
fn graph_bound_receipt_rejects_nested_portfolio_tampering() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let receipt = optimize_with_factor_graph(
        OptimizationRequest {
            decision_id: id("decision:seal"),
            objective_digest: digest("objective"),
            registry_snapshot_digest: registry_digest,
            budget: 3,
            maximum_selected: 3,
            candidates: vec![candidate("candidate:a", "factor:a", 30, registry_digest)],
        },
        &factor_graph,
    )
    .expect("graph optimize");
    let mut mutations = Vec::new();
    let mut changed = receipt.clone();
    changed.portfolio.selected.clear();
    mutations.push(changed);
    let mut changed = receipt.clone();
    changed.portfolio.decisions[0].disposition = CandidateDisposition::Illegal;
    mutations.push(changed);
    let mut changed = receipt.clone();
    changed.portfolio.total_cost += 1;
    mutations.push(changed);
    let mut changed = receipt.clone();
    changed.portfolio.total_expected_gain = FixedQ32::ZERO;
    mutations.push(changed);
    let mut changed = receipt.clone();
    changed.portfolio.unspent_budget += 1;
    mutations.push(changed);
    let mut changed = receipt;
    changed.portfolio.receipt_digest = digest("forged receipt");
    mutations.push(changed);
    for mut changed in mutations {
        // Recomputing the public wrapper cannot change its owner's sealed output.
        changed.receipt_digest = changed.compute_receipt_digest();
        assert_eq!(changed.validate(), Err(Error::InvalidPortfolioReceipt));
    }
}

#[test]
fn graph_optimizer_rejects_oversized_request_before_graph_processing() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let error = optimize_with_factor_graph(
        OptimizationRequest {
            decision_id: id("decision:oversized"),
            objective_digest: digest("objective"),
            registry_snapshot_digest: registry_digest,
            budget: 3,
            maximum_selected: 3,
            candidates: vec![
                candidate("candidate:missing", "factor:missing", 30, registry_digest);
                crate::MAX_CANDIDATES + 1
            ],
        },
        &factor_graph,
    )
    .expect_err("bounded request");
    assert_eq!(error, Error::CandidateLimitExceeded);
}

#[test]
fn authentic_standalone_portfolio_cannot_replace_graph_constrained_selection() {
    let factor_graph = graph();
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:splice"),
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 3,
        maximum_selected: 3,
        candidates: vec![
            candidate("candidate:a", "factor:a", 30, registry_digest),
            candidate("candidate:b", "factor:b", 20, registry_digest),
        ],
    };
    let unconstrained = crate::optimize(request.clone()).expect("standalone optimize");
    let mut constrained =
        optimize_with_factor_graph(request, &factor_graph).expect("graph optimize");
    assert_eq!(
        unconstrained.selected,
        vec![id("candidate:a"), id("candidate:b")]
    );
    assert_eq!(constrained.portfolio.selected, vec![id("candidate:a")]);
    unconstrained
        .validate()
        .expect("authentic standalone receipt");
    constrained.portfolio = unconstrained;
    constrained.receipt_digest = constrained.compute_receipt_digest();
    assert!(matches!(constrained.validate(), Err(Error::FactorGraph(_))));
}
