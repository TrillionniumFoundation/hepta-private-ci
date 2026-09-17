use std::fmt::Debug;

use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptRoleV2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected fixture error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("en-US"),
    }
}

fn registry_with_factors(factors: &[(&str, u32)]) -> PromptRegistry {
    let mut registry = must(PromptRegistry::new(64));
    let model = model_tuple();
    for (name, token_cost) in factors {
        let factor_id = id(&format!("factor:{name}"));
        must(registry.register_factor(PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id(&format!("proposer:{name}")),
            semantic_version: id("v1"),
            content_digest: digest(&format!("factor-content:{name}")),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        }));
        must(registry.admit_factor(&factor_id, &id("reviewer"), digest("admission")));
        must(registry.register_realization_v2(PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{name}")),
            factor_id,
            model_digest: model.model_digest,
            tokenizer_digest: model.tokenizer_digest,
            template_digest: model.template_digest,
            tool_schema_digest: model.tool_schema_digest,
            locale_id: model.locale_id.clone(),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: digest(&format!("payload:{name}")),
            token_cost: *token_cost,
            expires_unix_ms: Some(90),
        }));
    }
    registry
}

fn enumerate(registry: &PromptRegistry) -> EnumeratedPromptCandidatesV1 {
    must(enumerate_factors_v1(
        registry,
        CandidateEnumerationRequestV1 {
            set_id: id("candidate-set"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation"),
            selection_grammar_digest: digest("grammar"),
            generator_code_digest: digest("generator-code"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            model_tuple: model_tuple(),
            now_unix_ms: 50,
            maximum_results: 128,
        },
    ))
}

fn trusted_signer(role: LearningEvidenceRoleV1, seed: u8) -> TrustedLearningSignerV1 {
    let verifying_key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(match role {
                LearningEvidenceRoleV1::Generator => "generator",
                LearningEvidenceRoleV1::Observer => "observer",
                LearningEvidenceRoleV1::Evaluator => "evaluator",
            }),
            credential_chain_digest: digest(match role {
                LearningEvidenceRoleV1::Generator => "generator-chain",
                LearningEvidenceRoleV1::Observer => "observer-chain",
                LearningEvidenceRoleV1::Evaluator => "evaluator-chain",
            }),
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(match role {
            LearningEvidenceRoleV1::Generator => "controller-generator",
            LearningEvidenceRoleV1::Observer => "controller-observer",
            LearningEvidenceRoleV1::Evaluator => "controller-evaluator",
        }),
        verifying_key,
        roles: vec![role],
        revoked_at: None,
    }
}

fn verifier() -> LearningEvidenceVerifierV1 {
    must(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted_signer(LearningEvidenceRoleV1::Generator, 1),
            trusted_signer(LearningEvidenceRoleV1::Evaluator, 2),
        ],
    }))
}

fn pricing_payload(evidence: &PromptPricingEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v1".to_vec();
    super::push_id(&mut bytes, &evidence.factor_id);
    for value in [
        evidence.state_digest,
        evidence.causal_estimate_digest,
        evidence.ndu_utility_digest,
        evidence.support_audit_digest,
    ] {
        bytes.extend_from_slice(value.as_array());
    }
    for value in [
        evidence.gross_utility_q32,
        evidence.downside_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
        evidence.context_crowding_cost_q32,
        evidence.privacy_cost_q32,
        evidence.instability_cost_q32,
        evidence.future_context_option_cost_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&evidence.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&evidence.interference_ppm.to_be_bytes());
    bytes
}

fn verified_pricing(
    name: &str,
    gross: i64,
    lower: i64,
    upper: i64,
    role: LearningEvidenceRoleV1,
) -> VerifiedPromptPricingEvidenceV1 {
    let evidence = PromptPricingEvidenceV1 {
        factor_id: id(&format!("factor:{name}")),
        state_digest: digest("state"),
        causal_estimate_digest: digest(&format!("causal:{name}")),
        ndu_utility_digest: digest("ndu"),
        support_audit_digest: digest(&format!("support:{name}")),
        gross_utility_q32: FixedQ32::from_raw(gross),
        downside_q32: FixedQ32::ZERO,
        latency_cost_micros: 0,
        interference_ppm: 0,
        confidence_lower_q32: FixedQ32::from_raw(lower),
        confidence_upper_q32: FixedQ32::from_raw(upper),
        context_crowding_cost_q32: FixedQ32::ZERO,
        privacy_cost_q32: FixedQ32::ZERO,
        instability_cost_q32: FixedQ32::ZERO,
        future_context_option_cost_q32: FixedQ32::ZERO,
    };
    let payload = pricing_payload(&evidence);
    assert_eq!(Digest32::of_bytes(&payload), must(evidence.payload_digest()));
    let verifier = verifier();
    let (principal, seed) = match role {
        LearningEvidenceRoleV1::Generator => ("generator", 1),
        LearningEvidenceRoleV1::Evaluator => ("evaluator", 2),
        LearningEvidenceRoleV1::Observer => panic!("observer is not in this fixture"),
    };
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{name}")),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    let verification = must(verifier.verify(role, &signed, &payload, 50));
    VerifiedPromptPricingEvidenceV1 {
        evidence,
        verification,
    }
}

fn zero_cost_policy() -> PromptPricingPolicyV1 {
    must(PromptPricingPolicyV1::new(
        FixedQ32::ZERO,
        FixedQ32::ZERO,
        FixedQ32::ZERO,
        FixedQ32::ZERO,
    ))
}

#[test]
fn canonical_pipeline_selects_profitable_prerequisite_bundle_and_revalidates_registry() {
    let mut registry = registry_with_factors(&[("a", 2), ("b", 1)]);
    let enumerated = enumerate(&registry);
    assert_eq!(
        enumerated.receipt.candidate_factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert!(!enumerated.receipt.authority.grants_any());
    let candidate_json = must(enumerated.receipt.to_canonical_json());
    assert_eq!(
        must(PromptCandidateSetReceiptV1::from_canonical_json(
            &candidate_json
        )),
        enumerated.receipt
    );

    let pricing = must(price_factors_v1(
        &enumerated,
        vec![
            verified_pricing("a", 100, 90, 110, LearningEvidenceRoleV1::Evaluator),
            verified_pricing("b", -1, -2, 0, LearningEvidenceRoleV1::Evaluator),
        ],
        &zero_cost_policy(),
    ));
    let portfolio = must(select_portfolio_v1(
        &pricing,
        PortfolioSelectionRequestV1 {
            portfolio_id: id("portfolio"),
            token_budget: 10,
            maximum_selected_factors: 2,
            valid_until_unix_ms: 80,
            interactions: vec![PairInteractionV1 {
                left_factor_id: id("factor:a"),
                right_factor_id: id("factor:b"),
                marginal_gain_q32: FixedQ32::ZERO,
                support_digest: digest("pair:a:b"),
            }],
            hard_constraints: vec![HardConstraintV1::Requires {
                factor_id: id("factor:a"),
                prerequisite_factor_id: id("factor:b"),
                support_digest: digest("requires:a:b"),
            }],
        },
    ));
    assert_eq!(
        portfolio.receipt.factor_ids,
        vec![id("factor:a"), id("factor:b")]
    );
    assert_eq!(portfolio.receipt.expected_utility_q32, FixedQ32::from_raw(99));
    assert_eq!(portfolio.receipt.total_token_upper_bound, 3);
    assert!(!portfolio.receipt.authority.grants_any());

    let exercise = must(exercise_v1(
        &registry,
        &enumerated,
        &pricing,
        &portfolio,
        ExerciseRequestV1 {
            decision_boundary: DecisionBoundaryV1::BeforeModelOrToolDispatch,
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation"),
            model_tuple: model_tuple(),
            now_unix_ms: 60,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        },
    ));
    assert_eq!(exercise.receipt.decision, ExerciseDispositionV1::Exercise);
    assert_eq!(exercise.reason, ExerciseReasonV1::CurrentAndPreferred);
    assert!(!exercise.receipt.authority.grants_any());

    must(registry.revoke_factor(&id("factor:a")));
    let rejected = must(exercise_v1(
        &registry,
        &enumerated,
        &pricing,
        &portfolio,
        ExerciseRequestV1 {
            decision_boundary: DecisionBoundaryV1::BeforeModelOrToolDispatch,
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation"),
            model_tuple: model_tuple(),
            now_unix_ms: 70,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        },
    ));
    assert_eq!(rejected.receipt.decision, ExerciseDispositionV1::Reject);
    assert_eq!(rejected.reason, ExerciseReasonV1::RegistryDrift);
}

#[test]
fn missing_pair_support_never_becomes_zero_interaction() {
    let registry = registry_with_factors(&[("a", 1), ("b", 1)]);
    let enumerated = enumerate(&registry);
    let pricing = must(price_factors_v1(
        &enumerated,
        vec![
            verified_pricing("a", 10, 9, 11, LearningEvidenceRoleV1::Evaluator),
            verified_pricing("b", 9, 8, 10, LearningEvidenceRoleV1::Evaluator),
        ],
        &zero_cost_policy(),
    ));
    let portfolio = must(select_portfolio_v1(
        &pricing,
        PortfolioSelectionRequestV1 {
            portfolio_id: id("sparse-portfolio"),
            token_budget: 10,
            maximum_selected_factors: 2,
            valid_until_unix_ms: 80,
            interactions: Vec::new(),
            hard_constraints: Vec::new(),
        },
    ));
    assert_eq!(portfolio.receipt.factor_ids, vec![id("factor:a")]);
    assert_eq!(portfolio.receipt.expected_utility_q32, FixedQ32::from_raw(10));
}

#[test]
fn pricing_rejects_a_cryptographically_valid_generator_as_an_evaluator() {
    let registry = registry_with_factors(&[("a", 1)]);
    let enumerated = enumerate(&registry);
    let result = price_factors_v1(
        &enumerated,
        vec![verified_pricing(
            "a",
            10,
            9,
            11,
            LearningEvidenceRoleV1::Generator,
        )],
        &zero_cost_policy(),
    );
    assert_eq!(
        result,
        Err(CanonicalPromptError::EvidenceRoleMismatch(
            "factor:a".to_string()
        ))
    );
}

#[test]
fn canonical_json_rejects_unknown_fields_and_noncanonical_whitespace() {
    let registry = registry_with_factors(&[("a", 1)]);
    let enumerated = enumerate(&registry);
    let bytes = must(enumerated.receipt.to_canonical_json());
    let mut spaced = b" ".to_vec();
    spaced.extend_from_slice(&bytes);
    assert_eq!(
        PromptCandidateSetReceiptV1::from_canonical_json(&spaced),
        Err(CanonicalPromptError::NonCanonicalEncoding)
    );

    let mut value: serde_json::Value = must(serde_json::from_slice(&bytes));
    value["unexpectedCriticalField"] = serde_json::Value::Bool(true);
    let edited = must(serde_json::to_vec(&value));
    assert!(matches!(
        PromptCandidateSetReceiptV1::from_canonical_json(&edited),
        Err(CanonicalPromptError::Json(_))
    ));
}
