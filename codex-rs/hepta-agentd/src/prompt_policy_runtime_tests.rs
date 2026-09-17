use std::fmt::Debug;

use super::*;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_intelligence::PromptPolicyContextRequestV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_optimizer::canonical_evidence::pricing_evidence_signing_payload_v1;
use codex_hepta_prompt_optimizer::canonical_v1::CandidateEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::DecisionBoundaryV1;
use codex_hepta_prompt_optimizer::canonical_v1::ExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::PortfolioSelectionRequestV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::canonical_v1::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::canonical_v1::VerifiedPromptPricingEvidenceV1;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected test error: {error:?}"),
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

fn registry() -> PromptRegistry {
    let model = model_tuple();
    let factor_id = id("factor:a");
    let mut registry = must(PromptRegistry::new(16));
    must(registry.register_factor(PromptFactor {
        factor_id: factor_id.clone(),
        proposer_id: id("proposer"),
        semantic_version: id("v1"),
        content_digest: digest("factor-content"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }));
    must(registry.admit_factor(&factor_id, &id("reviewer"), digest("admission")));
    must(registry.register_realization_v2(PromptRealizationBindingV2 {
        realization_id: id("realization:a"),
        factor_id,
        model_digest: model.model_digest,
        tokenizer_digest: model.tokenizer_digest,
        template_digest: model.template_digest,
        tool_schema_digest: model.tool_schema_digest,
        locale_id: model.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("prompt-payload"),
        token_cost: 1,
        expires_unix_ms: Some(90),
    }));
    registry
}

fn verifier() -> LearningEvidenceVerifierV1 {
    let signing_key = SigningKey::from_bytes(&[9; 32]);
    let verifying_key = signing_key.verifying_key().to_bytes();
    must(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 3,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("evaluator"),
                credential_chain_digest: digest("evaluator-chain"),
                signing_key_digest: Digest32::of_bytes(&verifying_key),
                scope_digest: digest("scope"),
                authority_epoch: 3,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id("evaluator-controller"),
            verifying_key,
            roles: vec![LearningEvidenceRoleV1::Evaluator],
            revoked_at: None,
        }],
    }))
}

fn pricing_evidence() -> VerifiedPromptPricingEvidenceV1 {
    let evidence = PromptPricingEvidenceV1 {
        factor_id: id("factor:a"),
        state_digest: digest("state"),
        causal_estimate_digest: digest("causal-estimate"),
        ndu_utility_digest: digest("ndu"),
        support_audit_digest: digest("support-audit"),
        gross_utility_q32: FixedQ32::ONE,
        downside_q32: FixedQ32::ZERO,
        latency_cost_micros: 0,
        interference_ppm: 0,
        confidence_lower_q32: FixedQ32::from_raw(FixedQ32::ONE.raw() / 2),
        confidence_upper_q32: FixedQ32::ONE,
        context_crowding_cost_q32: FixedQ32::ZERO,
        privacy_cost_q32: FixedQ32::ZERO,
        instability_cost_q32: FixedQ32::ZERO,
        future_context_option_cost_q32: FixedQ32::ZERO,
    };
    let payload = must(pricing_evidence_signing_payload_v1(&evidence));
    let verifier = verifier();
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id("pricing-evidence"),
        principal_id: id("evaluator"),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 3,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[9; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    let verification = must(verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        50,
    ));
    VerifiedPromptPricingEvidenceV1 {
        evidence,
        verification,
    }
}

fn policy_request(exercise_model: PromptModelTupleV2) -> CanonicalPromptPolicyRequestV1 {
    let model = model_tuple();
    CanonicalPromptPolicyRequestV1 {
        enumeration: CandidateEnumerationRequestV1 {
            set_id: id("candidate-set"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation"),
            selection_grammar_digest: digest("grammar"),
            generator_code_digest: digest("generator"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("candidate-truncation"),
            model_tuple: model.clone(),
            now_unix_ms: 50,
            maximum_results: 16,
        },
        pricing_evidence: vec![pricing_evidence()],
        pricing_policy: must(PromptPricingPolicyV1::new(
            FixedQ32::ZERO,
            FixedQ32::ZERO,
            FixedQ32::ZERO,
            FixedQ32::ZERO,
        )),
        portfolio: PortfolioSelectionRequestV1 {
            portfolio_id: id("portfolio:a"),
            token_budget: 10,
            maximum_selected_factors: 1,
            valid_until_unix_ms: 80,
            interactions: Vec::new(),
            hard_constraints: Vec::new(),
        },
        exercise: ExerciseRequestV1 {
            decision_boundary: DecisionBoundaryV1::BeforeModelOrToolDispatch,
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation"),
            model_tuple: exercise_model,
            now_unix_ms: 60,
            wait_value_q32: FixedQ32::ZERO,
            policy_digest: digest("exercise-policy"),
        },
        context: PromptPolicyContextRequestV1 {
            compilation_id: id("compilation"),
            model_profile: ContextModelProfileV2 {
                model_digest: model.model_digest,
                tokenizer_digest: model.tokenizer_digest,
                template_digest: model.template_digest,
                tool_schema_digest: model.tool_schema_digest,
                maximum_context_tokens: 100,
            },
            token_budget: 10,
            truncation_policy_digest: digest("context-truncation"),
            additional_candidates: Vec::new(),
            mandatory_groups: Vec::new(),
        },
    }
}

fn runtime(observed_payload_digest: Digest32) -> PromptRuntimeBindingV1 {
    PromptRuntimeBindingV1 {
        serialization_id: id("serialization"),
        serialized_payload_digest: digest("serialized-payload"),
        attachment_id: id("attachment"),
        thread_id: id("thread"),
        method_id: id("model-dispatch"),
        deadline_ms: 100,
        adapter_now_ms: 70,
        delivery_observation_id: id("delivery-observation"),
        observed_payload_digest: Some(observed_payload_digest),
        delivery_terminal_observed: true,
        delivery_disposition: ContextDeliveryDispositionV2::Delivered,
        delivery_observed_unix_ms: 75,
        app_server_observation: Some(AppServerObservation {
            terminal_observed: true,
            response_digest: digest("app-server-response"),
        }),
        observed_token_positions: Some(vec![1]),
    }
}

fn learning() -> PromptLearningBindingV1 {
    PromptLearningBindingV1 {
        record_id: id("learning-record"),
        episode_id: id("episode"),
        learning_decision_id: id("learning-decision"),
        policy_id: id("prompt.optimizer"),
        policy_digest: digest("prompt-policy"),
    }
}

#[test]
fn agentd_composes_selection_delivery_and_durable_feedback_without_authority() {
    let registry = registry();
    let mut ledger = LearningLedger::new();
    let receipt = must(run_prompt_policy_turn_v1(
        &registry,
        &mut ledger,
        PromptPolicyTurnRequestV1 {
            policy: policy_request(model_tuple()),
            runtime: runtime(digest("serialized-payload")),
            learning: learning(),
        },
    ));
    assert!(receipt.delivery.delivered);
    assert_eq!(receipt.policy.exercise.receipt.decision, ExerciseDispositionV1::Exercise);
    assert_eq!(receipt.learning.artifact.ledger_decision.selected_candidate_id, id("portfolio:a"));
    assert!(!receipt.learning.artifact.causal_evaluation_eligible);
    assert_eq!(ledger.snapshot().records().len(), 1);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn runtime_payload_mismatch_fails_before_learning_append() {
    let registry = registry();
    let mut ledger = LearningLedger::new();
    let result = run_prompt_policy_turn_v1(
        &registry,
        &mut ledger,
        PromptPolicyTurnRequestV1 {
            policy: policy_request(model_tuple()),
            runtime: runtime(digest("wrong-observed-payload")),
            learning: learning(),
        },
    );
    assert!(matches!(
        result,
        Err(PromptPolicyTurnErrorV1::Context(
            ContextCompilerV2Error::DeliveryMismatch
        ))
    ));
    assert!(ledger.snapshot().records().is_empty());
}

#[test]
fn exercise_drift_rejects_before_serialization_and_learning() {
    let registry = registry();
    let mut ledger = LearningLedger::new();
    let mut drifted_model = model_tuple();
    drifted_model.model_digest = digest("other-model");
    let result = run_prompt_policy_turn_v1(
        &registry,
        &mut ledger,
        PromptPolicyTurnRequestV1 {
            policy: policy_request(drifted_model),
            runtime: runtime(digest("serialized-payload")),
            learning: learning(),
        },
    );
    assert_eq!(result, Err(PromptPolicyTurnErrorV1::PolicyRejected));
    assert!(ledger.snapshot().records().is_empty());
}
