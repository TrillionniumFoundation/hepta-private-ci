use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use super::raw;
use super::solver;
use super::verified;
use super::CanonicalPromptError;
use super::EnumeratedPromptCandidatesV1;
use super::PricedPromptCandidatesV1;
use super::PromptEnumerationRequestV1;
use super::PromptPairUtilityEvidenceV1;
use super::PromptPortfolioRequestV1;
use super::PromptPricingEvidenceV1;
use super::PromptPricingPolicyV1;
use super::SelectedPromptPortfolioV1;
use super::VerifiedPromptExerciseDecisionV1;

#[derive(Clone, Debug)]
pub struct PromptExerciseRequestV1 {
    pub decision_boundary: raw::PromptDecisionBoundaryV1,
    pub current_state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub policy: solver::PromptExercisePolicyV1,
    pub current_graph: KnowledgeGenerationV2,
    pub current_verifier: LearningEvidenceVerifierV1,
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptExerciseRequestV1,
) -> Result<VerifiedPromptExerciseDecisionV1, CanonicalPromptError> {
    solver::exercise_v1(
        registry,
        &request.current_graph,
        &request.current_verifier,
        portfolio,
        solver::PromptExerciseRequestV1 {
            decision_boundary: request.decision_boundary,
            current_state_digest: request.current_state_digest,
            generation_vector_digest: request.generation_vector_digest,
            model_tuple: request.model_tuple,
            now_unix_ms: request.now_unix_ms,
            wait_value_q32: request.wait_value_q32,
            policy: request.policy,
        },
    )
}

#[derive(Clone, Debug)]
pub struct CanonicalPromptPlanInputsV1 {
    pub enumeration: PromptEnumerationRequestV1,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_evidence: SignedLearningEvidenceV1,
    pub pricing_evidence: Vec<PromptPricingEvidenceV1>,
    pub pricing_policy: PromptPricingPolicyV1,
    pub pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    pub portfolio: PromptPortfolioRequestV1,
    pub exercise: PromptExerciseRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPromptPlanV1 {
    pub enumerated: EnumeratedPromptCandidatesV1,
    pub priced: PricedPromptCandidatesV1,
    pub portfolio: SelectedPromptPortfolioV1,
    pub exercise: VerifiedPromptExerciseDecisionV1,
}

pub fn build_canonical_prompt_plan_v1(
    registry: &PromptRegistry,
    inputs: CanonicalPromptPlanInputsV1,
) -> Result<CanonicalPromptPlanV1, CanonicalPromptError> {
    let graph = &inputs.exercise.current_graph;
    let verifier = &inputs.exercise.current_verifier;
    let enumerated = verified::enumerate_factors_v1(registry, inputs.enumeration)?;
    let priced = verified::price_factors_v1(
        enumerated.clone(),
        &inputs.completeness,
        &inputs.completeness_evidence,
        inputs.pricing_evidence,
        verifier,
        &inputs.pricing_policy,
        inputs.exercise.now_unix_ms,
    )?;
    let portfolio = solver::select_portfolio_v1(
        &priced,
        graph,
        inputs.pair_evidence,
        verifier,
        inputs.portfolio,
        inputs.exercise.now_unix_ms,
    )?;
    let exercise = exercise_v1(registry, &portfolio, inputs.exercise)?;
    Ok(CanonicalPromptPlanV1 {
        enumerated,
        priced,
        portfolio,
        exercise,
    })
}
