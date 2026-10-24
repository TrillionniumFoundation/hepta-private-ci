//! Named Agentd product caller for the canonical prompt optimizer.
//!
//! The executable target exists to make the complete owner composition a real
//! Cargo target rather than a test-only helper. The embedded Agentd host invokes
//! the same functions with its durable registry/runtime owners.

use codex_hepta_agentd::AgentdPromptPipelineOwner;
use codex_hepta_agentd::AgentdPromptRuntimeOwner;
use codex_hepta_agentd::PromptRuntimeStageDisposition;
use codex_hepta_codex_adapter::PromptRuntimeTerminalOutcomeV1;
use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::PromptDeliveryLineageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::EnumeratedPromptCandidatesV1;
use codex_hepta_prompt_optimizer::canonical::PricedPromptCandidatesV1;
use codex_hepta_prompt_optimizer::canonical::PromptEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptExercisePolicyV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPairUtilityEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptPortfolioRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::price_factors_v1;
use codex_hepta_prompt_optimizer::canonical::select_portfolio_v1;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

#[derive(Debug)]
pub enum AgentdCanonicalPromptProductErrorV1 {
    Pipeline(String),
    Optimizer(String),
    TerminalMissing,
    TerminalIndeterminate,
    TerminalObservationMissing,
    Ledger(String),
}

impl std::fmt::Display for AgentdCanonicalPromptProductErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdCanonicalPromptProductErrorV1 {}

#[derive(Clone, Debug)]
pub struct AgentdCanonicalPromptProductRequestV1 {
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub requested_deadline_ms: u64,
    pub enumeration: PromptEnumerationRequestV1,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_evidence: SignedLearningEvidenceV1,
    pub pricing_evidence: Vec<PromptPricingEvidenceV1>,
    pub pricing_policy: PromptPricingPolicyV1,
    pub graph: KnowledgeGenerationV2,
    pub verifier: LearningEvidenceVerifierV1,
    pub pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    pub portfolio: PromptPortfolioRequestV1,
    pub decision_boundary:
        codex_hepta_prompt_optimizer::canonical::PromptDecisionBoundaryV1,
    pub current_state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub wait_value_q32: FixedQ32,
    pub exercise_policy: PromptExercisePolicyV1,
    pub compilation: PromptRegistryCompilationRequestV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCanonicalPromptProductResultV1 {
    pub enumerated: EnumeratedPromptCandidatesV1,
    pub priced: PricedPromptCandidatesV1,
    pub portfolio: SelectedPromptPortfolioV1,
    pub exercise_request: PromptExerciseRequestV1,
    pub stage_disposition: PromptRuntimeStageDisposition,
}

/// Execute the canonical owner chain and stage only a verified portfolio into
/// the real Agentd PromptRuntimeHost used by Codex.
pub fn run_agentd_canonical_prompt_product_v1(
    owner: &AgentdPromptPipelineOwner,
    request: AgentdCanonicalPromptProductRequestV1,
) -> Result<AgentdCanonicalPromptProductResultV1, AgentdCanonicalPromptProductErrorV1> {
    let enumerated = owner
        .enumerate_candidates(request.enumeration)
        .map_err(|error| AgentdCanonicalPromptProductErrorV1::Pipeline(error.to_string()))?;
    let priced = price_factors_v1(
        enumerated.clone(),
        &request.completeness,
        &request.completeness_evidence,
        request.pricing_evidence,
        &request.verifier,
        &request.pricing_policy,
        request.now_unix_ms,
    )
    .map_err(|error| AgentdCanonicalPromptProductErrorV1::Optimizer(error.to_string()))?;
    let portfolio = select_portfolio_v1(
        &priced,
        &request.graph,
        request.pair_evidence,
        &request.verifier,
        request.portfolio,
        request.now_unix_ms,
    )
    .map_err(|error| AgentdCanonicalPromptProductErrorV1::Optimizer(error.to_string()))?;
    let exercise_request = PromptExerciseRequestV1 {
        decision_boundary: request.decision_boundary,
        current_state_digest: request.current_state_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_tuple: request.model_tuple,
        now_unix_ms: request.now_unix_ms,
        wait_value_q32: request.wait_value_q32,
        policy: request.exercise_policy,
        current_graph: request.graph,
        current_verifier: request.verifier,
    };
    let stage_disposition = owner
        .compile_and_stage(
            &request.thread_id,
            &request.turn_id,
            &request.model,
            request.requested_deadline_ms,
            &portfolio,
            &exercise_request,
            request.compilation,
        )
        .map_err(|error| AgentdCanonicalPromptProductErrorV1::Pipeline(error.to_string()))?;
    Ok(AgentdCanonicalPromptProductResultV1 {
        enumerated,
        priced,
        portfolio,
        exercise_request,
        stage_disposition,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptTerminalLedgerDispositionV1 {
    Appended(AppendReceipt),
    NotExposed,
}

/// Admit learning evidence only from a terminal record written by the physical
/// PromptRuntimeHost. Unknown/indeterminate provider state remains open.
pub fn append_agentd_prompt_terminal_to_ledger_v1(
    runtime: &AgentdPromptRuntimeOwner,
    ledger: &mut LearningLedger,
    attempt_id: &str,
    lineage: PromptDeliveryLineageV1,
) -> Result<PromptTerminalLedgerDispositionV1, AgentdCanonicalPromptProductErrorV1> {
    let terminal = runtime
        .terminal_record(attempt_id)
        .map_err(|error| AgentdCanonicalPromptProductErrorV1::Pipeline(error.to_string()))?
        .ok_or(AgentdCanonicalPromptProductErrorV1::TerminalMissing)?;
    match terminal.outcome {
        PromptRuntimeTerminalOutcomeV1::Indeterminate => {
            Err(AgentdCanonicalPromptProductErrorV1::TerminalIndeterminate)
        }
        PromptRuntimeTerminalOutcomeV1::NotDispatched => {
            Ok(PromptTerminalLedgerDispositionV1::NotExposed)
        }
        PromptRuntimeTerminalOutcomeV1::Delivered
        | PromptRuntimeTerminalOutcomeV1::Rejected => {
            let observation = terminal
                .delivery_observation
                .ok_or(AgentdCanonicalPromptProductErrorV1::TerminalObservationMissing)?;
            let receipt = ledger
                .append_runtime_prompt_delivery_v1(lineage, observation)
                .map_err(|error| {
                    AgentdCanonicalPromptProductErrorV1::Ledger(error.to_string())
                })?;
            Ok(PromptTerminalLedgerDispositionV1::Appended(receipt))
        }
    }
}

fn main() {}
