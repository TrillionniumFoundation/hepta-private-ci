use super::*;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::observe_delivery;
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

use crate::PromptContextPreparationRequestV1;
use crate::prepare_prompt_context_v1;

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

impl PromptExposureAssignmentAuthenticatorV1 for Accept {
    fn authenticate_prompt_assignment(
        &self,
        _assignment: &PromptExposureAssignmentV1,
        _now_unix_ms: u64,
    ) -> Result<(), PromptExposureAuthenticationErrorV1> {
        Ok(())
    }
}

struct Fixture {
    candidate_set: PromptCandidateSetReceiptV1,
    pricing: PromptPricingReceiptV1,
    relations: PromptRelationSourceV1,
    portfolio: PromptPortfolioReceiptV1,
    exercise_request: PromptExerciseRequestV1,
    exercise: PromptExerciseDecisionV1,
    preparation: PromptContextPreparationV1,
}

fn fixture() -> Fixture {
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
            enumeration_id: id("enumeration:exposure"),
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
            selection_id: id("selection:exposure"),
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
        exercise_id: id("exercise:exposure"),
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
    let preparation = prepare_prompt_context_v1(
        &candidate_set,
        &pricing,
        &relations,
        &portfolio,
        &exercise,
        &exercise_request,
        PromptContextPreparationRequestV1 {
            compilation_id: id("compilation:exposure"),
            serialization_id: id("serialization:exposure"),
            attachment_id: id("attachment:exposure"),
            maximum_context_tokens: 1_000,
            token_budget: 100,
            truncation_policy_digest: digest("truncation"),
            serialized_payload_digest: digest("serialized-payload"),
        },
    )
    .expect("preparation");
    Fixture {
        candidate_set,
        pricing,
        relations,
        portfolio,
        exercise_request,
        exercise,
        preparation,
    }
}

fn assignment(portfolio: &PromptPortfolioReceiptV1) -> PromptExposureAssignmentV1 {
    let mut assignment = PromptExposureAssignmentV1 {
        record_id: id("record:prompt-exposure"),
        episode_id: id("episode:prompt-exposure"),
        policy_id: id("prompt-assignment-policy"),
        objective_digest: portfolio.objective_digest,
        arms: vec![
            PromptExposureArmV1 {
                arm_id: id("abstain"),
                portfolio_digest: None,
            },
            PromptExposureArmV1 {
                arm_id: id("portfolio:selected"),
                portfolio_digest: Some(portfolio.receipt_digest),
            },
        ],
        selected_arm_id: id("portfolio:selected"),
        selected_propensity: ProbabilityQ32::ONE,
        candidate_set_completeness_digest: digest("complete-behavior-arms"),
        random_stream_digest: digest("random-stream"),
        support_digest: digest("assignment-support"),
        valid_until_unix_ms: 1_000,
        assignment_digest: Digest32::ZERO,
    };
    assignment.assignment_digest = assignment.compute_assignment_digest();
    assignment
}

#[test]
fn delivered_prompt_portfolio_records_one_complete_causal_decision() {
    let fixture = fixture();
    let delivery = observe_delivery(
        &fixture.preparation.attachment,
        id("delivery:delivered"),
        Some(fixture.preparation.attachment.payload_digest),
        /*terminal_observed*/ true,
        ContextDeliveryDispositionV2::Delivered,
        /*observed_unix_ms*/ 200,
    )
    .expect("delivery observation");
    let assignment = assignment(&fixture.portfolio);
    let mut ledger = LearningLedger::new();

    let receipt = record_prompt_delivery_exposure_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        &fixture.exercise,
        &fixture.exercise_request,
        &fixture.preparation,
        &delivery,
        &assignment,
        /*now_unix_ms*/ 200,
        &Accept,
        &mut ledger,
    )
    .expect("exposure");

    assert_eq!(
        receipt.disposition,
        PromptExposureRecordingDispositionV1::Recorded
    );
    assert_eq!(ledger.records().len(), 1);
    let Some(decision) = receipt.ledger_decision else {
        panic!("delivered exposure must retain the ledger decision");
    };
    assert_eq!(decision.selected_candidate_id, id("portfolio:selected"));
    assert_eq!(
        decision.candidate_ids,
        vec![id("abstain"), id("portfolio:selected")]
    );
    assert_eq!(decision.completeness, CandidateSetCompleteness::Complete);
}

#[test]
fn rejected_or_indeterminate_delivery_never_becomes_causal_exposure() {
    let fixture = fixture();
    for (suffix, disposition, terminal_observed) in [
        ("rejected", ContextDeliveryDispositionV2::Rejected, true),
        (
            "indeterminate",
            ContextDeliveryDispositionV2::Indeterminate,
            false,
        ),
    ] {
        let delivery = observe_delivery(
            &fixture.preparation.attachment,
            id(&format!("delivery:{suffix}")),
            None,
            terminal_observed,
            disposition,
            /*observed_unix_ms*/ 200,
        )
        .expect("delivery observation");
        let assignment = assignment(&fixture.portfolio);
        let mut ledger = LearningLedger::new();
        let receipt = record_prompt_delivery_exposure_v1(
            &fixture.candidate_set,
            &fixture.pricing,
            &fixture.relations,
            &fixture.portfolio,
            &fixture.exercise,
            &fixture.exercise_request,
            &fixture.preparation,
            &delivery,
            &assignment,
            /*now_unix_ms*/ 200,
            &Accept,
            &mut ledger,
        )
        .expect("non-delivery receipt");
        assert!(ledger.records().is_empty());
        assert!(receipt.ledger_decision.is_none());
        assert!(receipt.ledger_receipt.is_none());
    }
}

#[test]
fn incomplete_or_unbound_assignment_witness_cannot_write_the_ledger() {
    let fixture = fixture();
    let delivery = observe_delivery(
        &fixture.preparation.attachment,
        id("delivery:assignment-reject"),
        Some(fixture.preparation.attachment.payload_digest),
        /*terminal_observed*/ true,
        ContextDeliveryDispositionV2::Delivered,
        /*observed_unix_ms*/ 200,
    )
    .expect("delivery observation");
    let mut assignment = assignment(&fixture.portfolio);
    assignment.arms.remove(0);
    assignment.assignment_digest = assignment.compute_assignment_digest();
    let mut ledger = LearningLedger::new();
    assert!(matches!(
        record_prompt_delivery_exposure_v1(
            &fixture.candidate_set,
            &fixture.pricing,
            &fixture.relations,
            &fixture.portfolio,
            &fixture.exercise,
            &fixture.exercise_request,
            &fixture.preparation,
            &delivery,
            &assignment,
            /*now_unix_ms*/ 200,
            &Accept,
            &mut ledger,
        ),
        Err(PromptExposureErrorV1::InvalidAssignment)
    ));
    assert!(ledger.records().is_empty());
}
