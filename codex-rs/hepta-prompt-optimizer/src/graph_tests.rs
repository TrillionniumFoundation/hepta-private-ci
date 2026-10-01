use super::*;
use crate::CandidateDisposition;
use crate::PromptCandidate;
use codex_hepta_contracts::FinalUseAuthority;
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
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::OptimizationRequest;

type TestResult<T = ()> = std::result::Result<T, Box<dyn std::error::Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn register_admitted_factor(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    factor_id: &str,
) -> TestResult {
    let factor_id = id(factor_id)?;
    let factor = PromptFactor {
        factor_id: factor_id.clone(),
        proposer_id: id("proposer:graph-tests")?,
        semantic_version: id("semantic:v1")?,
        semantic_purpose: "governed factor interaction fixture".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")?],
        content_digest: digest(&format!("factor-content:{factor_id}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry.register_factor(factor.clone())?;
    let scope = digest("reviewed-scope:graph-tests");
    let evidence = digest(&format!("factor-admission:{factor_id}"));
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:graph-tests".to_owned(),
        authority_epoch: 1,
        grant_id: format!("grant:{factor_id}"),
        nonce: digest(&format!("nonce:{factor_id}")).into_array(),
        binding: final_use_admission_binding(
            &factor,
            &id("reviewer:graph-tests")?,
            scope,
            evidence,
        )?,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes()?)
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry.admit_factor_final_use(authority, &signed, &factor_id, scope, evidence)?;
    Ok(())
}

fn graph() -> TestResult<PromptFactorProjectionV1> {
    let temporary = tempfile::tempdir()?;
    let mut registry =
        DurablePromptRegistry::open_state_dir(&temporary.path().join("registry"), 32)?;
    let signing_key = SigningKey::from_bytes(&[37; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &temporary.path().join("authority"),
        "authority:graph-tests".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    for factor_id in ["factor:a", "factor:b", "factor:c"] {
        register_admitted_factor(&mut registry, &authority, &signing_key, factor_id)?;
    }
    registry.register_factor_relation(PromptFactorRelation {
        relation_id: id("relation:a-b-conflict")?,
        left_factor_id: id("factor:a")?,
        right_factor_id: id("factor:b")?,
        kind: PromptFactorRelationKind::Conflicts,
        evidence_digest: digest("evidence:a-b-conflict"),
    })?;
    registry.register_factor_relation(PromptFactorRelation {
        relation_id: id("relation:a-c-complement")?,
        left_factor_id: id("factor:a")?,
        right_factor_id: id("factor:c")?,
        kind: PromptFactorRelationKind::Complements,
        evidence_digest: digest("evidence:a-c-complement"),
    })?;
    registry.register_factor_relation(PromptFactorRelation {
        relation_id: id("relation:b-c-substitute")?,
        left_factor_id: id("factor:b")?,
        right_factor_id: id("factor:c")?,
        kind: PromptFactorRelationKind::Substitutes,
        evidence_digest: digest("evidence:b-c-substitute"),
    })?;
    let source = registry.registry()?.factor_graph_source_v1();
    Ok(build_prompt_factor_projection_v1(
        Generation::new(1)?,
        digest("prompt-generation-vector"),
        &source,
    )?)
}

fn candidate(
    name: &str,
    factor_id: &str,
    gain: i64,
    registry_digest: Digest32,
) -> TestResult<PromptCandidate> {
    Ok(PromptCandidate {
        candidate_id: id(name)?,
        factor_id: id(factor_id)?,
        realization_id: id(&format!("realization:{name}"))?,
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(gain),
        cost: 1,
        registry_digest,
        support_digest: digest(&format!("candidate-support:{name}")),
    })
}

#[test]
fn graph_conflicts_are_hard_constraints_and_receipt_binds_relation_view() -> TestResult {
    let factor_graph = graph()?;
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:graph")?,
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 3,
        maximum_selected: 3,
        candidates: vec![
            candidate("candidate:a", "factor:a", 30, registry_digest)?,
            candidate("candidate:b", "factor:b", 20, registry_digest)?,
            candidate("candidate:c", "factor:c", 10, registry_digest)?,
        ],
    };
    let receipt = optimize_with_factor_graph(request, &factor_graph)?;
    assert_eq!(
        receipt.portfolio.selected,
        vec![id("candidate:a")?, id("candidate:c")?]
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
    let conflicting_candidate_id = id("candidate:b")?;
    assert!(receipt.portfolio.decisions.iter().any(|decision| {
        decision.candidate_id == conflicting_candidate_id
            && decision.disposition == CandidateDisposition::GraphConflict
    }));
    receipt.validate()?;
    assert!(!receipt.authority.grants_any());
    Ok(())
}

#[test]
fn candidate_factor_missing_from_complete_graph_fails_closed() -> TestResult {
    let factor_graph = graph()?;
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:missing")?,
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate("candidate:x", "factor:x", 10, registry_digest)?],
    };
    let error = optimize_with_factor_graph(request, &factor_graph)
        .err()
        .ok_or("optimization accepted a factor missing from the complete graph")?;
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("factor:x")),
        "unexpected error: {error:?}"
    );
    Ok(())
}

#[test]
fn registry_snapshot_drift_fails_closed_before_selection() -> TestResult {
    let factor_graph = graph()?;
    let request = OptimizationRequest {
        decision_id: id("decision:stale-registry")?,
        objective_digest: digest("objective"),
        registry_snapshot_digest: digest("different-registry"),
        budget: 1,
        maximum_selected: 1,
        candidates: vec![candidate(
            "candidate:a",
            "factor:a",
            10,
            factor_graph.registry_snapshot_digest(),
        )?],
    };
    let error = optimize_with_factor_graph(request, &factor_graph)
        .err()
        .ok_or("optimization accepted a stale registry snapshot")?;
    assert!(
        matches!(&error, Error::FactorGraph(message) if message.contains("registry snapshot")),
        "unexpected error: {error:?}"
    );
    Ok(())
}

#[test]
fn graph_substitutes_are_hard_redundancy_constraints() -> TestResult {
    let factor_graph = graph()?;
    let registry_digest = factor_graph.registry_snapshot_digest();
    let request = OptimizationRequest {
        decision_id: id("decision:substitute")?,
        objective_digest: digest("objective"),
        registry_snapshot_digest: registry_digest,
        budget: 2,
        maximum_selected: 2,
        candidates: vec![
            candidate("candidate:b", "factor:b", 20, registry_digest)?,
            candidate("candidate:c", "factor:c", 10, registry_digest)?,
        ],
    };
    let receipt = optimize_with_factor_graph(request, &factor_graph)?;
    assert_eq!(receipt.portfolio.selected, vec![id("candidate:b")?]);
    assert_eq!(receipt.observed_substitute_count, 1);
    let substituted_candidate_id = id("candidate:c")?;
    assert!(receipt.portfolio.decisions.iter().any(|decision| {
        decision.candidate_id == substituted_candidate_id
            && decision.disposition == CandidateDisposition::GraphSubstitute
    }));
    Ok(())
}
