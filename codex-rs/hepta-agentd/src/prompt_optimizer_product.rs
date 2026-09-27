//! Named Agentd consumer of the sealed canonical optimizer. The installed
//! evidence source belongs to the embedding, not to a decoded request. Existing
//! PromptRuntimeOwner/App Server still own staging, dispatch and terminal facts.
use crate::{AgentdPromptPipelineError, AgentdPromptPipelineOwner, PromptRuntimeStageDisposition};
use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;
use codex_hepta_prompt_optimizer::canonical::{
    CanonicalPromptError, PromptDecisionBoundaryV1, PromptEnumerationRequestV1,
    PromptEvidenceSourceV1, PromptExerciseRequestV1, PromptPortfolioRequestV1,
    SelectedPromptPortfolioV1, price_factors_v1, select_portfolio_v1,
};
use std::fmt;
use std::sync::Arc;

pub struct AgentdPromptOptimizerV1 {
    pipeline: Arc<AgentdPromptPipelineOwner>,
    source: Arc<dyn PromptEvidenceSourceV1>,
}

#[derive(Clone, Debug)]
pub struct AgentdPromptOptimizationRequestV1 {
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub requested_deadline_ms: u64,
    pub enumeration: PromptEnumerationRequestV1,
    pub selection: PromptPortfolioRequestV1,
    pub compilation: PromptRegistryCompilationRequestV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdPromptOptimizationOutcomeV1 {
    NoIntervention(SelectedPromptPortfolioV1),
    Staged {
        portfolio: SelectedPromptPortfolioV1,
        disposition: PromptRuntimeStageDisposition,
    },
}

#[derive(Debug)]
pub enum AgentdPromptOptimizerError {
    Pipeline(AgentdPromptPipelineError),
    Policy(CanonicalPromptError),
    ClockMismatch,
}
impl fmt::Display for AgentdPromptOptimizerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for AgentdPromptOptimizerError {}

impl AgentdPromptOptimizerV1 {
    /// Supply host-authenticated owner readers at process composition. Neither
    /// this constructor nor a returned portfolio installs a provider capability.
    pub fn new(
        pipeline: Arc<AgentdPromptPipelineOwner>,
        source: Arc<dyn PromptEvidenceSourceV1>,
    ) -> Self {
        Self { pipeline, source }
    }

    pub fn optimize_and_stage(
        &self,
        request: AgentdPromptOptimizationRequestV1,
    ) -> Result<AgentdPromptOptimizationOutcomeV1, AgentdPromptOptimizerError> {
        let now = request.enumeration.now_unix_ms;
        if now == 0
            || now != request.compilation.now_unix_ms
            || request.requested_deadline_ms <= now
        {
            return Err(AgentdPromptOptimizerError::ClockMismatch);
        }
        let candidates = self
            .pipeline
            .enumerate_candidates(request.enumeration)
            .map_err(AgentdPromptOptimizerError::Pipeline)?;
        let material = self
            .source
            .pricing(&candidates, now)
            .map_err(AgentdPromptOptimizerError::Policy)?;
        let priced = price_factors_v1(candidates, material, Arc::clone(&self.source), now)
            .map_err(AgentdPromptOptimizerError::Policy)?;
        let interactions = self
            .source
            .interactions(&priced, now)
            .map_err(AgentdPromptOptimizerError::Policy)?;
        let portfolio = select_portfolio_v1(&priced, interactions, request.selection, now)
            .map_err(AgentdPromptOptimizerError::Policy)?;
        if portfolio.selected.is_empty() {
            return Ok(AgentdPromptOptimizationOutcomeV1::NoIntervention(portfolio));
        }
        let current = self
            .source
            .current()
            .map_err(AgentdPromptOptimizerError::Policy)?;
        let exercise = PromptExerciseRequestV1 {
            decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            current_state_digest: current.exercise_policy.state_digest,
            generation_vector_digest: current.exercise_policy.generation_vector_digest,
            model_tuple: request.compilation.registry_model_tuple.clone(),
            now_unix_ms: now,
            wait_value_q32: current.exercise_policy.wait_value_q32,
            policy_digest: current
                .exercise_policy
                .digest()
                .map_err(AgentdPromptOptimizerError::Policy)?,
        };
        let deadline = request
            .requested_deadline_ms
            .min(portfolio.receipt.valid_until_unix_ms);
        let disposition = self
            .pipeline
            .compile_and_stage(
                &request.thread_id,
                &request.turn_id,
                &request.model,
                deadline,
                &portfolio,
                &exercise,
                request.compilation,
            )
            .map_err(AgentdPromptOptimizerError::Pipeline)?;
        Ok(AgentdPromptOptimizationOutcomeV1::Staged {
            portfolio,
            disposition,
        })
    }
}
