//! Named Agentd product caller for the sealed canonical prompt optimizer.
//!
//! The pre-dispatch phase executes the complete owner-bound optimizer chain and
//! stages only the exact compiled bytes into the existing PromptRuntimeHost. The
//! terminal phase consumes the runtime-owned physical provider observation and
//! commits it to the learning-ledger owner. No optimizer receipt grants dispatch
//! or ledger-write authority.

use std::fmt;

use codex_hepta_codex_adapter::PromptRuntimeTerminalOutcomeV1;
use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::PromptDeliveryLineageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPairUtilityEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptPortfolioRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingEvidenceV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::price_factors_v1;
use codex_hepta_prompt_optimizer::canonical::select_portfolio_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdPromptPipelineError;
use crate::AgentdPromptPipelineOwner;
use crate::AgentdPromptRuntimeError;
use crate::PromptRuntimeStageDisposition;

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
    pub pair_evidence: Vec<PromptPairUtilityEvidenceV1>,
    pub portfolio_request: PromptPortfolioRequestV1,
    pub exercise_request: PromptExerciseRequestV1,
    pub compilation_request: PromptRegistryCompilationRequestV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCanonicalPromptPreparedV1 {
    portfolio: SelectedPromptPortfolioV1,
    exercise_request: PromptExerciseRequestV1,
    pub compilation_id: StableId,
    pub portfolio_receipt_digest: Digest32,
    pub portfolio_verification_digest: Digest32,
    pub solver_audit_digest: Digest32,
    pub exercise_policy_digest: Digest32,
    pub staged: PromptRuntimeStageDisposition,
    pub product_receipt_digest: Digest32,
}

impl AgentdCanonicalPromptPreparedV1 {
    pub fn portfolio(&self) -> &SelectedPromptPortfolioV1 {
        &self.portfolio
    }

    pub fn exercise_request(&self) -> &PromptExerciseRequestV1 {
        &self.exercise_request
    }

    pub fn validate(&self) -> Result<(), AgentdCanonicalPromptProductError> {
        if self.portfolio_receipt_digest != self.portfolio.receipt.receipt_digest
            || self.portfolio_verification_digest != self.portfolio.verification_digest()
            || self.solver_audit_digest != self.portfolio.audit().audit_digest
            || self.exercise_policy_digest
                != self
                    .exercise_request
                    .policy
                    .digest()
                    .map_err(|_| AgentdCanonicalPromptProductError::Integrity)?
            || self.product_receipt_digest != self.compute_product_receipt_digest()
        {
            return Err(AgentdCanonicalPromptProductError::Integrity);
        }
        Ok(())
    }

    fn compute_product_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.canonical-prompt-product.v1".to_vec();
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.portfolio_receipt_digest,
            self.portfolio_verification_digest,
            self.solver_audit_digest,
            self.exercise_policy_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(match self.staged {
            PromptRuntimeStageDisposition::Inserted => 0,
            PromptRuntimeStageDisposition::Unchanged => 1,
        });
        Digest32::of_bytes(&bytes)
    }
}

pub fn run_canonical_prompt_product_v1(
    owner: &AgentdPromptPipelineOwner,
    verifier: &LearningEvidenceVerifierV1,
    request: AgentdCanonicalPromptProductRequestV1,
) -> Result<AgentdCanonicalPromptPreparedV1, AgentdCanonicalPromptProductError> {
    let candidates = owner
        .enumerate_candidates(request.enumeration)
        .map_err(AgentdCanonicalPromptProductError::Pipeline)?;
    let priced = price_factors_v1(
        candidates,
        &request.completeness,
        &request.completeness_evidence,
        request.pricing_evidence,
        verifier,
        &request.pricing_policy,
        request.exercise_request.now_unix_ms,
    )
    .map_err(|error| AgentdCanonicalPromptProductError::Optimizer(error.to_string()))?;
    let portfolio = select_portfolio_v1(
        &priced,
        &request.graph,
        request.pair_evidence,
        verifier,
        request.portfolio_request,
        request.exercise_request.now_unix_ms,
    )
    .map_err(|error| AgentdCanonicalPromptProductError::Optimizer(error.to_string()))?;
    let compilation_id = request.compilation_request.compilation_id.clone();
    let exercise_policy_digest = request
        .exercise_request
        .policy
        .digest()
        .map_err(|error| AgentdCanonicalPromptProductError::Optimizer(error.to_string()))?;
    let staged = owner
        .compile_and_stage(
            &request.thread_id,
            &request.turn_id,
            &request.model,
            request.requested_deadline_ms,
            &portfolio,
            &request.exercise_request,
            request.compilation_request,
        )
        .map_err(AgentdCanonicalPromptProductError::Pipeline)?;
    let mut result = AgentdCanonicalPromptPreparedV1 {
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        portfolio_verification_digest: portfolio.verification_digest(),
        solver_audit_digest: portfolio.audit().audit_digest,
        exercise_policy_digest,
        portfolio,
        exercise_request: request.exercise_request,
        compilation_id,
        staged,
        product_receipt_digest: Digest32::ZERO,
    };
    result.product_receipt_digest = result.compute_product_receipt_digest();
    result.validate()?;
    Ok(result)
}

pub fn append_canonical_prompt_terminal_v1(
    owner: &AgentdPromptPipelineOwner,
    prepared: &AgentdCanonicalPromptPreparedV1,
    attempt_id: &str,
    mut lineage: PromptDeliveryLineageV1,
    ledger: &mut LearningLedger,
) -> Result<AppendReceipt, AgentdCanonicalPromptProductError> {
    prepared.validate()?;
    let terminal = owner
        .runtime_owner()
        .terminal_record(attempt_id)
        .map_err(AgentdCanonicalPromptProductError::Runtime)?
        .ok_or_else(|| {
            AgentdCanonicalPromptProductError::TerminalUnavailable(attempt_id.to_owned())
        })?;
    if terminal.compilation_id != prepared.compilation_id {
        return Err(AgentdCanonicalPromptProductError::Integrity);
    }
    match terminal.outcome {
        PromptRuntimeTerminalOutcomeV1::NotDispatched => {
            return Err(AgentdCanonicalPromptProductError::NotDispatched(
                attempt_id.to_owned(),
            ));
        }
        PromptRuntimeTerminalOutcomeV1::Indeterminate => {
            return Err(AgentdCanonicalPromptProductError::Indeterminate(
                attempt_id.to_owned(),
            ));
        }
        PromptRuntimeTerminalOutcomeV1::Delivered | PromptRuntimeTerminalOutcomeV1::Rejected => {}
    }
    let observation = terminal.delivery_observation.ok_or_else(|| {
        AgentdCanonicalPromptProductError::TerminalUnavailable(attempt_id.to_owned())
    })?;
    lineage.portfolio_receipt_digest = prepared.portfolio_receipt_digest;
    ledger
        .append_runtime_prompt_delivery_v1(lineage, observation)
        .map_err(|error| AgentdCanonicalPromptProductError::Ledger(error.to_string()))
}

#[derive(Debug)]
pub enum AgentdCanonicalPromptProductError {
    Pipeline(AgentdPromptPipelineError),
    Runtime(AgentdPromptRuntimeError),
    Optimizer(String),
    Ledger(String),
    TerminalUnavailable(String),
    NotDispatched(String),
    Indeterminate(String),
    Integrity,
}

impl fmt::Display for AgentdCanonicalPromptProductError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for AgentdCanonicalPromptProductError {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
