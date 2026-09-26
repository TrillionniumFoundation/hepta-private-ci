use super::*;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::CandidateDisposition;
use crate::OptimizationRequest;
use crate::PromptCandidate;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_millis() as u64
}

fn register_admitted_factor(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    factor_name: &str,
    grant_index: u8,
) {
    let factor_id = id(factor_name);
    let factor = PromptFactor {
        factor_id: factor_id.clone(),
        proposer_id: id("proposer:graph-tests"),
        semantic_version: id("semantic:v1"),
        semantic_purpose: "optimizer relation graph qualification".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:graph-utility")],
        content_digest: digest(&format!("factor-content:{factor_id}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register durable factor");

    let reviewer = id("reviewer:graph-tests");
    let scope = digest(&format!("factor-scope:{factor_id}"));
    let evidence = digest(&format!("factor-admission:{factor_id}"));
    let binding = final_use_admission_binding(&factor, &reviewer, scope, evidence)
        .expect("admission binding");
    let now = now_unix_ms();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner:graph-tests".to_owned(),
        authority_epoch: 1,
        grant_id: format!("grant:graph-tests:{grant_index}"),
        nonce: [grant_index; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .admit_factor_final_use(authority, &signed, &factor_id, scope, evidence)
        .expect("admit durable factor through final-use authority");
}

fn graph() -> PromptFactorProjectionV1 {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing_key = SigningKey::from_bytes(&[71; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temporary.path().join("authority"),
        "security-owner:graph-tests".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("final-use authority");
    let mut registry = DurablePromptRegistry::open_state_dir(
        &temporary.path().join("registry"),
        32,
    )
    .expect("durable registry");
    for (index, factor_id) in ["factor:a", "factor:b", "factor:c"]
        .into_iter()
        .enumerate()
    {
        register_admitted_factor(
            &mut registry,
            &authority,
            &signing_key,
            factor_id,
            u8::try_from(index + 1).expect("bounded grant index"),
        );
    }
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a-b-conflict"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            kind: PromptFactorRelationKind::Conflicts,
            evidence_digest: digest("evidence:a-b-conflict"),
        })
        .expect("register durable conflict");
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:a-c-complement"),
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:c"),
            kind: PromptFactorRelationKind::Complements,
            evidence_digest: digest("evidence:a-c-complement"),
        })
        .expect("register durable complement");
    registry
        .register_factor_relation(PromptFactorRelation {
            relation_id: id("relation:b-c-substitute"),
            left_factor_id: id("factor:b"),
            right_factor_id: id("factor:c"),
            kind: PromptFactorRelationKind::Substitutes,
            evidence_digest: digest("evidence:b-c-substitute"),
        })
        .expect("register durable substitute");
    let source = registry
        .registry()
        .expect("authoritative registry")
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
