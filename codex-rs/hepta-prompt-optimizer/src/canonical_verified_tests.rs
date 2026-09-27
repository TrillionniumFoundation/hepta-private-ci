use super::*;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_learning_ledger::{AuthenticatedPrincipalV1, LearningEvidenceRoleV1,
    LearningEvidenceTrustV1, TrustedLearningSignerV1};
use ed25519_dalek::SigningKey;

#[path = "canonical_fixture.rs"]
mod fixture;
use fixture::{digest, id, FixtureSource};

fn case() -> (tempfile::TempDir, DurablePromptRegistry, EnumeratedPromptCandidatesV1, Arc<FixtureSource>) {
    let temp = tempfile::tempdir().unwrap_or_else(|e| panic!("temp: {e}"));
    let (registry, tuple, _, _, _) = fixture::admitted_registry(&temp.path().join("registry"), b"Verify evidence.");
    let candidates = enumerate_factors_v1(registry.registry().unwrap_or_else(|e| panic!("registry: {e}")),
        PromptEnumerationRequestV1 {
            set_id: id("set:verified"), objective_digest: digest("objective"), state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"), model_tuple: tuple, now_unix_ms: 100,
            required_factor_ids: vec![id("factor:verify")], maximum_candidates: 16,
            selection_grammar_digest: digest("grammar"),
        }).unwrap_or_else(|e| panic!("enumerate: {e}"));
    let source = FixtureSource::for_candidates(&candidates);
    (temp, registry, candidates, source)
}

fn priced(candidates: EnumeratedPromptCandidatesV1, source: &Arc<FixtureSource>) -> PricedPromptCandidatesV1 {
    let material = source.pricing(&candidates, 100).unwrap_or_else(|e| panic!("material: {e}"));
    price_factors_v1(candidates, material, source.clone(), 100).unwrap_or_else(|e| panic!("pricing: {e}"))
}

fn selection_request() -> PromptPortfolioRequestV1 {
    PromptPortfolioRequestV1 { portfolio_id: id("portfolio:verified"), graph_query_id: id("query:verified"),
        token_budget: 128, maximum_selected_factors: 16, requested_valid_until_unix_ms: 20_000 }
}

fn trust(objective: Digest32, epoch: u64, same_controller: bool) -> LearningEvidenceVerifierV1 {
    let scope = digest("scope:prompt-fixture");
    let signers = [("generator", 7_u8, LearningEvidenceRoleV1::Generator),
        ("evaluator", 9_u8, LearningEvidenceRoleV1::Evaluator)].into_iter().map(|(name, seed, role)| {
        let key = SigningKey::from_bytes(&[seed; 32]).verifying_key().to_bytes();
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 { principal_id: id(name), credential_chain_digest: Digest32::of_bytes(&key),
                signing_key_digest: Digest32::of_bytes(&key), scope_digest: scope, authority_epoch: epoch,
                authenticated_at: 1, expires_at: 9_000 },
            controller_id: if same_controller { id("shared-controller") } else { id(&format!("{name}-controller")) },
            verifying_key: key, roles: vec![role], revoked_at: None,
        }
    }).collect();
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 { scope_digest: scope, objective_digest: objective,
        authority_epoch: epoch, signers }).unwrap_or_else(|e| panic!("trust: {e}"))
}

#[test]
fn verified_pipeline_prices_selects_and_exercises_real_registry_binding() {
    let (_temp, registry, candidates, _source) = case();
    let (selected, request, _source) = fixture::select(candidates, 100);
    let result = exercise_v1(registry.registry().unwrap_or_else(|e| panic!("registry: {e}")), &selected, request)
        .unwrap_or_else(|e| panic!("exercise: {e}"));
    assert_eq!(result.decision, PromptExerciseActionV1::Exercise);
    assert_eq!(selected.receipt.factor_ids, vec![id("factor:verify")]);
    assert_eq!(selected.receipt.total_token_upper_bound, 4);
    assert_eq!(selected.receipt.expected_utility_q32, FixedQ32::ONE);
    assert_eq!(selected.audit().audit_digest, selected.audit().compute_digest());
    assert!(!result.authority.grants_any());
}

#[test]
fn changed_realization_payload_fails_candidate_recomputation() {
    let (_temp, _registry, mut candidates, _source) = case();
    candidates.inner.candidates[0].realization.payload_digest = digest("different-payload");
    assert_eq!(admission::validate_candidates(&candidates.inner), Err(CanonicalPromptError::Integrity("realization binding")));
}

#[test]
fn candidate_receipt_and_factor_identity_tampering_are_rejected() {
    let (_temp, _registry, candidates, _source) = case();
    let mut changed = candidates.clone();
    changed.inner.receipt.receipt_digest = digest("forged-receipt");
    assert_eq!(admission::validate_candidates(&changed.inner), Err(CanonicalPromptError::Integrity("candidate receipt digest")));
    changed = candidates;
    changed.inner.receipt.candidate_factor_ids[0] = id("factor:wrong");
    assert_eq!(admission::validate_candidates(&changed.inner), Err(CanonicalPromptError::Integrity("candidate identities or order")));
}

#[test]
fn batch_binding_signature_cannot_be_omitted_or_modified() {
    let (_temp, _registry, candidates, source) = case();
    let mut material = source.pricing(&candidates, 100).unwrap_or_else(|e| panic!("material: {e}"));
    material.binding_evidence.signature = [0; 64];
    assert!(matches!(price_factors_v1(candidates, material, source, 100), Err(CanonicalPromptError::Evidence(_))));
}

#[test]
fn individually_signed_estimate_cannot_be_replaced_inside_bound_batch() {
    let (_temp, _registry, candidates, source) = case();
    let mut material = source.pricing(&candidates, 100).unwrap_or_else(|e| panic!("material: {e}"));
    material.estimates[0].expected_incremental_utility_q32 = FixedQ32::ZERO;
    assert!(matches!(price_factors_v1(candidates, material, source, 100), Err(CanonicalPromptError::Evidence(_))));
}

#[test]
fn objective_and_scope_must_match_host_policy() {
    let (_temp, _registry, candidates, source) = case();
    let material = source.pricing(&candidates, 100).unwrap_or_else(|e| panic!("material: {e}"));
    source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"))
        .exercise_policy.objective_digest = digest("other-objective");
    assert_eq!(price_factors_v1(candidates.clone(), material.clone(), source.clone(), 100), Err(CanonicalPromptError::ObjectiveMismatch));
    {
        let mut snapshot = source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"));
        snapshot.exercise_policy.objective_digest = candidates.receipt.objective_digest;
        snapshot.exercise_policy.scope_digest = digest("other-scope");
    }
    assert_eq!(price_factors_v1(candidates, material, source, 100), Err(CanonicalPromptError::ScopeMismatch));
}

#[test]
fn valid_signatures_from_same_controller_are_not_independent_evidence() {
    let (_temp, _registry, candidates, source) = case();
    source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"))
        .verifier = trust(candidates.receipt.objective_digest, 1, true);
    let material = source.pricing(&candidates, 100).unwrap_or_else(|e| panic!("material: {e}"));
    let result = price_factors_v1(candidates, material, source, 100);
    assert!(matches!(result, Err(CanonicalPromptError::Evidence(message)) if message.contains("ControllerCollision")));
}

#[test]
fn raw_pricing_tamper_cannot_pass_selector_replay() {
    let (_temp, _registry, candidates, source) = case();
    let mut priced = priced(candidates, &source);
    let interactions = source.interactions(&priced, 100).unwrap_or_else(|e| panic!("interactions: {e}"));
    priced.inner.rows[0].net_utility_q32 = FixedQ32::ZERO;
    assert_eq!(select_portfolio_v1(&priced, interactions, selection_request(), 100), Err(CanonicalPromptError::Integrity("pricing replay")));
}

#[test]
fn portfolio_expiry_is_bounded_by_all_admitted_evidence() {
    let (_temp, _registry, candidates, source) = case();
    let priced = priced(candidates, &source);
    let interactions = source.interactions(&priced, 100).unwrap_or_else(|e| panic!("interactions: {e}"));
    let selected = select_portfolio_v1(&priced, interactions, selection_request(), 100).unwrap_or_else(|e| panic!("select: {e}"));
    assert_eq!(selected.receipt.valid_until_unix_ms, 9_000);
}

#[test]
fn missing_pair_policy_cannot_change_after_evaluator_signature() {
    let (_temp, _registry, candidates, source) = case();
    let priced = priced(candidates, &source);
    let mut interactions = source.interactions(&priced, 100).unwrap_or_else(|e| panic!("interactions: {e}"));
    interactions.missing_pairs = PromptMissingPairPolicyV1::RequireExplicit;
    assert!(matches!(select_portfolio_v1(&priced, interactions, selection_request(), 100), Err(CanonicalPromptError::Evidence(_))));
}

#[test]
fn exercise_rejects_expired_evidence_and_current_trust_rotation() {
    let (_temp, registry, candidates, _source) = case();
    let (selected, request, source) = fixture::select(candidates, 100);
    let mut expired = request.clone();
    expired.now_unix_ms = 9_000;
    let registry = registry.registry().unwrap_or_else(|e| panic!("registry: {e}"));
    assert_eq!(exercise_v1(registry, &selected, expired), Err(CanonicalPromptError::EvidenceExpired));
    source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"))
        .verifier = trust(selected.objective_digest, 2, false);
    assert_eq!(exercise_v1(registry, &selected, request), Err(CanonicalPromptError::TrustChanged));
}

#[test]
fn exercise_rejects_current_graph_and_policy_drift() {
    let (_temp, registry, candidates, _source) = case();
    let (selected, request, source) = fixture::select(candidates, 100);
    let registry = registry.registry().unwrap_or_else(|e| panic!("registry: {e}"));
    {
        let mut current = source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"));
        current.graph.generation_digest = digest("new-graph");
    }
    assert_eq!(exercise_v1(registry, &selected, request.clone()), Err(CanonicalPromptError::GraphChanged));
    {
        let mut current = source.snapshot.lock().unwrap_or_else(|e| panic!("lock: {e}"));
        current.graph.generation_digest = selected.graph_generation_digest;
        current.exercise_policy.wait_value_q32 = FixedQ32::ONE;
    }
    assert_eq!(exercise_v1(registry, &selected, request), Err(CanonicalPromptError::PolicyChanged));
}

#[test]
fn altered_portfolio_utility_and_receipt_fail_exercise() {
    let (_temp, registry, candidates, _source) = case();
    let (mut selected, request, _source) = fixture::select(candidates, 100);
    selected.inner.receipt.expected_utility_q32 = FixedQ32::ZERO;
    assert_eq!(exercise_v1(registry.registry().unwrap_or_else(|e| panic!("registry: {e}")), &selected, request),
        Err(CanonicalPromptError::Integrity("portfolio accounting")));
}
