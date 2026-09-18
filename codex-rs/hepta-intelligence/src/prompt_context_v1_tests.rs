use super::*;
use codex_hepta_prompt_optimizer::PromptAuthenticationErrorV1;
use codex_hepta_prompt_optimizer::PromptCandidateBindingV1;
use codex_hepta_prompt_optimizer::PromptCandidateEnumerationRequestV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceV1;
use codex_hepta_prompt_optimizer::PromptCostBreakdownV1;
use codex_hepta_prompt_optimizer::PromptExerciseBoundaryV1;
use codex_hepta_prompt_optimizer::PromptModelProfileV1;
use codex_hepta_prompt_optimizer::PromptPortfolioSelectionRequestV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::enumerate_factors_v1;
use codex_hepta_prompt_optimizer::exercise_portfolio_v1;
use codex_hepta_prompt_optimizer::price_factors_v1;
use codex_hepta_prompt_optimizer::select_portfolio_v1;
use codex_hepta_types::FixedQ32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Accept;

impl PromptCandidateSourceAuthenticatorV1 for Accept {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

impl PromptPricingEvidenceAuthenticatorV1 for Accept {
    fn authenticate_pricing_evidence(
        &self,
        _evidence: &PromptPricingEvidenceV1,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

impl PromptRelationSourceAuthenticatorV1 for Accept {
    fn authenticate_relation_source(
        &self,
        _source: &PromptRelationSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

fn fixture() -> (
    PromptCandidateSetReceiptV1,
    PromptPricingReceiptV1,
    PromptRelationSourceV1,
    PromptPortfolioReceiptV1,
    PromptExerciseRequestV1,
    PromptExerciseDecisionV1,
) {
    let mut binding = PromptCandidateBindingV1 {
        candidate_id: id("candidate:001"),
        factor_id: id("factor:001"),
        realization_id: id("realization:001"),
        payload_digest: digest("payload"),
        admission_digest: digest("admission"),
        support_digest: digest("registry-support"),
        token_cost: 7,
        expires_unix_ms: Some(10_000),
        binding_digest: Digest32::ZERO,
    };
    binding.binding_digest = binding.compute_binding_digest();
    let mut source = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry"),
        registry_revision: 2,
        revocation_frontier: 1,
        generation_vector_digest: digest("generation"),
        model_profile: PromptModelProfileV1 {
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            locale_id: id("en-US"),
        },
        bindings: vec![binding],
        omitted_count: 0,
        source_digest: Digest32::ZERO,
    };
    source.source_digest = source.compute_source_digest();
    let candidate_set = enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:context"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: 1,
            now_unix_ms: 100,
            source: source.clone(),
        },
        &Accept,
    )
    .expect("candidate set");
    let zero = PromptCostBreakdownV1 {
        tokens: FixedQ32::ZERO,
        latency: FixedQ32::ZERO,
        context_crowding: FixedQ32::ZERO,
        instruction_interference: FixedQ32::ZERO,
        privacy: FixedQ32::ZERO,
        instability: FixedQ32::ZERO,
        future_context_option_value: FixedQ32::ZERO,
    };
    let mut evidence = PromptPricingEvidenceV1 {
        candidate_id: id("candidate:001"),
        candidate_binding_digest: candidate_set.candidates[0].binding_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        causal_incremental_utility: FixedQ32::ONE,
        confidence: FixedQ32::ONE,
        costs: zero,
        utility_unit_digest: digest("utility-unit"),
        cost_profile_digest: digest("cost-profile"),
        support_digest: digest("causal-support"),
        valid_until_unix_ms: 1_000,
        evidence_digest: Digest32::ZERO,
    };
    evidence.evidence_digest = evidence.compute_evidence_digest();
    let pricing = price_factors_v1(&candidate_set, vec![evidence], 100, &Accept)
        .expect("pricing");
    let mut relations = PromptRelationSourceV1 {
        producer_id: id("knowledge.graph"),
        candidate_set_digest: candidate_set.candidate_set_digest,
        generation_vector_digest: candidate_set.generation_vector_digest,
        hard_constraint_completeness_digest: digest("hard-complete"),
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        source_digest: Digest32::ZERO,
    };
    relations.source_digest = relations.compute_source_digest();
    let portfolio = select_portfolio_v1(
        &candidate_set,
        &pricing,
        PromptPortfolioSelectionRequestV1 {
            selection_id: id("selection:context"),
            token_budget: 50,
            maximum_selected_factors: 1,
            maximum_steps: 2,
            now_unix_ms: 100,
            relations: relations.clone(),
        },
        &Accept,
    )
    .expect("portfolio");
    let exercise_request = PromptExerciseRequestV1 {
        exercise_id: id("exercise:context"),
        boundary: PromptExerciseBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        now_unix_ms: 100,
        current_source: source,
    };
    let exercise = exercise_portfolio_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        exercise_request.clone(),
        &Accept,
    )
    .expect("exercise");
    (
        candidate_set,
        pricing,
        relations,
        portfolio,
        exercise_request,
        exercise,
    )
}

#[test]
fn exercised_portfolio_compiles_as_atomic_trusted_context() {
    let (candidate_set, pricing, relations, portfolio, exercise_request, exercise) = fixture();
    let preparation = prepare_prompt_context_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        &exercise,
        &exercise_request,
        &Accept,
        PromptContextPreparationRequestV1 {
            compilation_id: id("compilation:prompt"),
            serialization_id: id("serialization:prompt"),
            attachment_id: id("attachment:prompt"),
            maximum_context_tokens: 1_000,
            token_budget: 100,
            truncation_policy_digest: digest("truncation"),
            serialized_payload_digest: digest("serialized-payload"),
        },
    )
    .expect("context preparation");

    assert_eq!(
        preparation.compiled.receipt.selected_item_ids,
        vec![id("candidate:001")]
    );
    assert_eq!(
        preparation.compiled.receipt.prompt_portfolio_digest,
        portfolio.receipt_digest
    );
    assert_eq!(preparation.compiled.receipt.used_tokens, 7);
    assert!(!preparation.authority.grants_any());
    preparation
        .validate(&exercise, &portfolio)
        .expect("preparation validates");
}

#[test]
fn invalidated_or_no_intervention_exercise_cannot_compile_prompt_context() {
    let (candidate_set, pricing, relations, portfolio, mut exercise_request, _) = fixture();
    exercise_request.current_state_digest = digest("different-state");
    let exercise = exercise_portfolio_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        exercise_request.clone(),
        &Accept,
    )
    .expect("exercise decision");
    let result = prepare_prompt_context_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        &exercise,
        &exercise_request,
        &Accept,
        PromptContextPreparationRequestV1 {
            compilation_id: id("compilation:invalid"),
            serialization_id: id("serialization:invalid"),
            attachment_id: id("attachment:invalid"),
            maximum_context_tokens: 1_000,
            token_budget: 100,
            truncation_policy_digest: digest("truncation"),
            serialized_payload_digest: digest("payload"),
        },
    );
    assert!(matches!(
        result,
        Err(PromptContextCompositionErrorV1::Invalidated(_))
    ));
}
