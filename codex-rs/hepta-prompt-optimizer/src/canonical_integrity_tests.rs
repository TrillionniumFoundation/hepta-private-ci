//! Exercise producer provenance with actual registry and signed pricing owners.

use super::*;

struct PricingInputs {
    completeness: CandidateSetCompletenessReceiptV1,
    completeness_evidence: SignedLearningEvidenceV1,
    evidence: Vec<PromptPricingEvidenceV1>,
    verifier: LearningEvidenceVerifierV1,
    policy: PromptPricingPolicyV1,
}

fn signed_evidence(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{role:?}")),
        principal_id: id("prompt.optimizer"),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 1,
        expires_at: 10_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn pricing_inputs(candidates: &EnumeratedPromptCandidatesV1, utility: FixedQ32) -> PricingInputs {
    let key = SigningKey::from_bytes(&[17; 32]);
    let public = key.verifying_key().to_bytes();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: candidates.receipt.objective_digest,
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("prompt.optimizer"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: Digest32::of_bytes(&public),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 10_000,
            },
            controller_id: id("controller:prompt"),
            verifying_key: public,
            roles: vec![
                LearningEvidenceRoleV1::Generator,
                LearningEvidenceRoleV1::Evaluator,
            ],
            revoked_at: None,
        }],
    })
    .expect("host pricing trust");
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).expect("bounded candidates"),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_evidence = signed_evidence(
        &verifier,
        &key,
        LearningEvidenceRoleV1::Generator,
        &candidate_completeness_signing_payload_v1(&completeness).expect("complete generator"),
    );
    let evidence = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let mut evidence = PromptPricingEvidenceV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                model_tuple_digest: candidates.model_tuple.digest(),
                expected_incremental_utility_q32: utility,
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: utility,
                confidence_upper_q32: utility,
                support_count: 1,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest("support-audit"),
                evidence: completeness_evidence.clone(),
            };
            evidence.evidence = signed_evidence(
                &verifier,
                &key,
                LearningEvidenceRoleV1::Evaluator,
                &pricing_evidence_signing_payload_v1(&evidence),
            );
            evidence
        })
        .collect();
    PricingInputs {
        completeness,
        completeness_evidence,
        evidence,
        verifier,
        policy: PromptPricingPolicyV1 {
            policy_id: id("pricing-policy"),
            token_cost_per_token_q32: FixedQ32::ZERO,
            latency_cost_per_micro_q32: FixedQ32::ZERO,
            interference_cost_per_ppm_q32: FixedQ32::ZERO,
            downside_weight_q32: FixedQ32::ZERO,
            minimum_support_count: 1,
            maximum_interference_ppm: 0,
        },
    }
}

fn enumerate(registry: &DurablePromptRegistry, set: &str) -> EnumeratedPromptCandidatesV1 {
    enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id(set),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: model_tuple(),
            now_unix_ms: 100,
            required_factor_ids: vec![id("factor:a")],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("real enumeration")
}

fn price(
    candidates: EnumeratedPromptCandidatesV1,
    inputs: PricingInputs,
) -> Result<PricedPromptCandidatesV1, CanonicalPromptError> {
    price_factors_v1(
        candidates,
        &inputs.completeness,
        &inputs.completeness_evidence,
        inputs.evidence,
        &inputs.verifier,
        &inputs.policy,
        100,
    )
}

fn select(
    priced: &PricedPromptCandidatesV1,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    select_portfolio_v1(
        priced,
        &graph(&["factor:a"], Vec::new()),
        Vec::new(),
        &verifier(),
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:provenance"),
            graph_query_id: id("query:provenance"),
            token_budget: 16,
            maximum_selected_factors: 1,
            requested_valid_until_unix_ms: 5_000,
        },
        100,
    )
}

fn exercise_request() -> PromptExerciseRequestV1 {
    PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: model_tuple(),
        now_unix_ms: 200,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy"),
    }
}

#[test]
fn enumerated_owner_rejects_binding_mutation_and_valid_output_graft_before_pricing() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, ..) = registry_fixture(&temp.path().join("registry"), &[4]);
    let original = enumerate(&registry, "set:a");
    let inputs = pricing_inputs(&original, FixedQ32::ONE);
    let mut changed = original.clone();
    changed.candidates[0].realization.token_cost = 1;
    changed.candidates[0].binding_digest = changed.candidates[0].realization.digest();
    // Keep the generator's original completeness digests and signed evidence.
    // The old pricing boundary compared only those claims, not these bytes.
    assert_eq!(
        price(changed, inputs),
        Err(CanonicalPromptError::OwnerOutputDrift("enumerated"))
    );

    let other = enumerate(&registry, "set:b");
    let inputs = pricing_inputs(&other, FixedQ32::ONE);
    let mut changed = original;
    changed.registry_snapshot = other.registry_snapshot;
    changed.model_tuple = other.model_tuple;
    changed.generation_vector_digest = other.generation_vector_digest;
    changed.candidates_digest = other.candidates_digest;
    changed.canonical_order_digest = other.canonical_order_digest;
    changed.omitted_count = other.omitted_count;
    changed.candidates = other.candidates;
    changed.receipt = other.receipt;
    assert_eq!(
        price(changed, inputs),
        Err(CanonicalPromptError::OwnerOutputDrift("enumerated"))
    );
}

#[test]
fn priced_owner_rejects_utility_mutation_and_valid_output_graft_before_selection() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, ..) = registry_fixture(&temp.path().join("registry"), &[4]);
    let candidates = enumerate(&registry, "set:a");
    let original = price(
        candidates.clone(),
        pricing_inputs(&candidates, FixedQ32::ONE),
    )
    .expect("signed pricing");
    let mut changed = original.clone();
    changed.rows[0].net_utility_q32 = FixedQ32::from_raw(2 << 32);
    assert_eq!(
        select(&changed),
        Err(CanonicalPromptError::OwnerOutputDrift("priced"))
    );
    let other = price(
        candidates.clone(),
        pricing_inputs(&candidates, FixedQ32::from_raw(2 << 32)),
    )
    .expect("independent signed pricing");
    select(&other).expect("other pricing is independently valid");
    let mut changed = original;
    changed.candidates = other.candidates;
    changed.completeness_digest = other.completeness_digest;
    changed.pricing_policy_digest = other.pricing_policy_digest;
    changed.rows = other.rows;
    changed.pricing_set_digest = other.pricing_set_digest;
    changed.authority = other.authority;
    assert_eq!(
        select(&changed),
        Err(CanonicalPromptError::OwnerOutputDrift("priced"))
    );
}

#[test]
fn selected_owner_preserves_wait_and_stale_semantics_but_rejects_public_mutations() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, ..) = registry_fixture(&temp.path().join("registry"), &[4]);
    let candidates = enumerate(&registry, "set:a");
    let priced = price(
        candidates.clone(),
        pricing_inputs(&candidates, FixedQ32::ONE),
    )
    .expect("signed pricing");
    let selected = select(&priced).expect("real selection");
    let owner = registry.registry().expect("registry");
    assert_eq!(
        exercise_v1(owner, &selected, exercise_request())
            .expect("live exercise")
            .decision,
        PromptExerciseActionV1::Exercise
    );
    let mut waiting = exercise_request();
    waiting.wait_value_q32 = FixedQ32::ONE;
    assert_eq!(
        exercise_v1(owner, &selected, waiting.clone())
            .expect("wait")
            .decision,
        PromptExerciseActionV1::Wait
    );
    let mut changed = selected.clone();
    changed.receipt.expected_utility_q32 = FixedQ32::from_raw(2 << 32);
    assert_eq!(
        exercise_v1(owner, &changed, waiting),
        Err(CanonicalPromptError::OwnerOutputDrift("selected"))
    );
    let mut expired = exercise_request();
    expired.now_unix_ms = selected.receipt.valid_until_unix_ms;
    assert_eq!(
        exercise_v1(owner, &selected, expired.clone())
            .expect("expired")
            .decision,
        PromptExerciseActionV1::RejectStale
    );
    let mut changed = selected.clone();
    changed.receipt.valid_until_unix_ms += 1_000;
    assert_eq!(
        exercise_v1(owner, &changed, expired),
        Err(CanonicalPromptError::OwnerOutputDrift("selected"))
    );
    let mut stale = exercise_request();
    stale.current_state_digest = digest("new-state");
    assert_eq!(
        exercise_v1(owner, &selected, stale.clone())
            .expect("state stale")
            .decision,
        PromptExerciseActionV1::RejectStale
    );
    let mut changed = selected.clone();
    changed.state_digest = stale.current_state_digest;
    assert_eq!(
        exercise_v1(owner, &changed, stale),
        Err(CanonicalPromptError::OwnerOutputDrift("selected"))
    );
    let mut changed = selected.clone();
    changed.selected[0].realization.token_cost = 1;
    changed.selected[0].binding_digest = changed.selected[0].realization.digest();
    assert_eq!(
        exercise_v1(owner, &changed, exercise_request()),
        Err(CanonicalPromptError::OwnerOutputDrift("selected"))
    );

    let other_priced = price(
        candidates.clone(),
        pricing_inputs(&candidates, FixedQ32::from_raw(2 << 32)),
    )
    .expect("other signed pricing");
    let other = select(&other_priced).expect("other real selection");
    exercise_v1(owner, &other, exercise_request()).expect("other selection is independently valid");
    let mut changed = selected;
    changed.receipt = other.receipt;
    changed.selected = other.selected;
    changed.objective_digest = other.objective_digest;
    changed.state_digest = other.state_digest;
    changed.model_tuple = other.model_tuple;
    changed.model_tuple_digest = other.model_tuple_digest;
    changed.generation_vector_digest = other.generation_vector_digest;
    changed.pricing_set_digest = other.pricing_set_digest;
    changed.graph_generation_digest = other.graph_generation_digest;
    changed.selection_method = other.selection_method;
    changed.optimality = other.optimality;
    assert_eq!(
        exercise_v1(owner, &changed, exercise_request()),
        Err(CanonicalPromptError::OwnerOutputDrift("selected"))
    );
}
