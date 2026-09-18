use super::*;
use crate::PromptAuthenticationErrorV1;
use crate::PromptCandidateBindingV1;
use crate::PromptCandidateEnumerationRequestV1;
use crate::PromptCandidateSourceAuthenticatorV1;
use crate::PromptCostBreakdownV1;
use crate::PromptModelProfileV1;
use crate::PromptPortfolioSelectionRequestV1;
use crate::PromptPricingEvidenceAuthenticatorV1;
use crate::PromptPricingEvidenceV1;
use crate::PromptRelationSourceAuthenticatorV1;
use crate::enumerate_factors_v1;
use crate::price_factors_v1;
use crate::select_portfolio_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> codex_hepta_types::FixedQ32 {
    codex_hepta_types::FixedQ32::from_raw(value << 32)
}

struct Accept;

impl PromptCandidateSourceAuthenticatorV1 for Accept {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), crate::PromptAuthenticationErrorV1> {
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

struct Fixture {
    candidate_set: PromptCandidateSetReceiptV1,
    pricing: PromptPricingReceiptV1,
    relations: PromptRelationSourceV1,
    portfolio: PromptPortfolioReceiptV1,
    current_source: PromptCandidateSourceV1,
}

fn fixture() -> Fixture {
    let mut binding = PromptCandidateBindingV1 {
        candidate_id: id("candidate:001"),
        factor_id: id("factor:001"),
        realization_id: id("realization:001"),
        payload_digest: digest("payload"),
        admission_digest: digest("admission"),
        support_digest: digest("registry-support"),
        token_cost: 5,
        expires_unix_ms: Some(10_000),
        binding_digest: Digest32::ZERO,
    };
    binding.binding_digest = binding.compute_binding_digest();
    let mut source = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry-v1"),
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
    let current_source = source.clone();
    let candidate_set = enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:exercise"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: 1,
            now_unix_ms: 100,
            source,
        },
        &Accept,
    )
    .expect("candidate set");
    let zero_cost = PromptCostBreakdownV1 {
        tokens: codex_hepta_types::FixedQ32::ZERO,
        latency: codex_hepta_types::FixedQ32::ZERO,
        context_crowding: codex_hepta_types::FixedQ32::ZERO,
        instruction_interference: codex_hepta_types::FixedQ32::ZERO,
        privacy: codex_hepta_types::FixedQ32::ZERO,
        instability: codex_hepta_types::FixedQ32::ZERO,
        future_context_option_value: codex_hepta_types::FixedQ32::ZERO,
    };
    let mut evidence = PromptPricingEvidenceV1 {
        candidate_id: id("candidate:001"),
        candidate_binding_digest: candidate_set.candidates[0].binding_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        causal_incremental_utility: q32(10),
        confidence: codex_hepta_types::FixedQ32::ONE,
        costs: zero_cost,
        utility_unit_digest: digest("utility-unit"),
        cost_profile_digest: digest("cost-profile"),
        support_digest: digest("causal-support"),
        valid_until_unix_ms: 1_000,
        evidence_digest: Digest32::ZERO,
    };
    evidence.evidence_digest = evidence.compute_evidence_digest();
    let pricing =
        price_factors_v1(&candidate_set, vec![evidence], /*now_unix_ms*/ 100, &Accept)
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
            selection_id: id("selection:exercise"),
            token_budget: 20,
            maximum_selected_factors: 1,
            maximum_steps: 2,
            now_unix_ms: 100,
            relations: relations.clone(),
        },
        &Accept,
    )
    .expect("portfolio");
    Fixture {
        candidate_set,
        pricing,
        relations,
        portfolio,
        current_source,
    }
}

fn request(current_source: PromptCandidateSourceV1) -> PromptExerciseRequestV1 {
    PromptExerciseRequestV1 {
        exercise_id: id("exercise:1"),
        boundary: PromptExerciseBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state"),
        now_unix_ms: 100,
        current_source,
    }
}

#[test]
fn unrelated_registry_revision_drift_does_not_invalidate_unchanged_selected_binding() {
    let fixture = fixture();
    let mut current = fixture.current_source.clone();
    current.registry_snapshot_digest = digest("registry-v2");
    current.registry_revision = 3;
    current.revocation_frontier = 2;
    current.source_digest = current.compute_source_digest();
    let request = request(current);
    let decision = exercise_portfolio_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        request.clone(),
        &Accept,
    )
    .expect("revalidation");
    assert_eq!(
        decision.disposition,
        PromptExerciseDispositionV1::ExercisePortfolio
    );
    decision
        .validate_for(
            &fixture.candidate_set,
            &fixture.pricing,
            &fixture.relations,
            &fixture.portfolio,
            &request,
        )
        .expect("decision validates");
}

#[test]
fn missing_or_changed_selected_binding_invalidates_delivery() {
    let fixture = fixture();
    let mut missing = fixture.current_source.clone();
    missing.bindings.clear();
    missing.omitted_count = 1;
    missing.source_digest = missing.compute_source_digest();
    let missing = exercise_portfolio_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        request(missing),
        &Accept,
    )
    .expect("revalidation");
    assert_eq!(
        missing.disposition,
        PromptExerciseDispositionV1::Invalidated(
            PromptExerciseInvalidationV1::SelectedCandidateUnavailable
        )
    );

    let mut changed = fixture.current_source.clone();
    changed.bindings[0].admission_digest = digest("new-admission");
    changed.bindings[0].binding_digest = changed.bindings[0].compute_binding_digest();
    changed.source_digest = changed.compute_source_digest();
    let changed = exercise_portfolio_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        request(changed),
        &Accept,
    )
    .expect("revalidation");
    assert_eq!(
        changed.disposition,
        PromptExerciseDispositionV1::Invalidated(
            PromptExerciseInvalidationV1::SelectedBindingDrift
        )
    );
}

#[test]
fn model_or_state_drift_invalidates_before_delivery() {
    let fixture = fixture();
    let mut model_drift = fixture.current_source.clone();
    model_drift.model_profile.model_digest = digest("other-model");
    model_drift.source_digest = model_drift.compute_source_digest();
    let model_drift = exercise_portfolio_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        request(model_drift),
        &Accept,
    )
    .expect("revalidation");
    assert_eq!(
        model_drift.disposition,
        PromptExerciseDispositionV1::Invalidated(
            PromptExerciseInvalidationV1::ModelProfileDrift
        )
    );

    let mut state_request = request(fixture.current_source.clone());
    state_request.current_state_digest = digest("other-state");
    let state_drift = exercise_portfolio_v1(
        &fixture.candidate_set,
        &fixture.pricing,
        &fixture.relations,
        &fixture.portfolio,
        state_request,
        &Accept,
    )
    .expect("revalidation");
    assert_eq!(
        state_drift.disposition,
        PromptExerciseDispositionV1::Invalidated(PromptExerciseInvalidationV1::StateDrift)
    );
}
