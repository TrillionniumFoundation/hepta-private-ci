//! Agentd-owned product composition for the sealed prompt optimizer.
//!
//! This is the only product-intended path that constructs a prompt portfolio.
//! It authenticates and seals enumeration, pricing and graph evidence before
//! selecting a portfolio, revalidates trust/graph context at exercise time,
//! compiles exact registry bytes and stages them for the existing Codex dispatch
//! boundary. Terminal delivery remains runtime-owned and is appended to the
//! learning ledger only after a terminal physical-provider observation exists.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_codex_adapter::PromptRuntimeTerminalOutcomeV1;
use codex_hepta_intelligence::PromptRegistryCompilationRequestV2;
use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::PromptDeliveryLineageV1;
use codex_hepta_prompt_optimizer::canonical::PromptEnumerationRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPortfolioRequestV1;
use codex_hepta_prompt_optimizer::canonical::PromptPricingPolicyV1;
use codex_hepta_prompt_optimizer::verified::PromptCompletenessEvidenceV2;
use codex_hepta_prompt_optimizer::verified::PromptExerciseContextV2;
use codex_hepta_prompt_optimizer::verified::PromptPairUtilityEvidenceV2;
use codex_hepta_prompt_optimizer::verified::PromptPricingEvidenceV2;
use codex_hepta_prompt_optimizer::verified::VerifiedEnumeratedPromptCandidatesV2;
use codex_hepta_prompt_optimizer::verified::VerifiedPromptError;
use codex_hepta_prompt_optimizer::verified::price_factors_verified_v2;
use codex_hepta_prompt_optimizer::verified::select_portfolio_verified_v2;
use codex_hepta_prompt_optimizer::verified::verify_exercise_context_v2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdPromptPipelineOwner;
use crate::AgentdPromptRuntimeOwner;
use crate::PromptRuntimeStageDisposition;

#[derive(Clone, Debug)]
pub struct AgentdPromptOptimizationRequestV2 {
    pub enumeration: PromptEnumerationRequestV1,
    pub completeness: PromptCompletenessEvidenceV2,
    pub pricing_evidence: Vec<PromptPricingEvidenceV2>,
    pub pricing_policy: PromptPricingPolicyV1,
    pub graph: KnowledgeGenerationV2,
    pub pair_evidence: Vec<PromptPairUtilityEvidenceV2>,
    pub portfolio: PromptPortfolioRequestV1,
    pub exercise: PromptExerciseRequestV1,
    pub compilation: PromptRegistryCompilationRequestV2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdPromptProductDispositionV2 {
    Staged(PromptRuntimeStageDisposition),
    NoIntervention,
    Wait,
    RejectStale,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdPromptProductReceiptV2 {
    pub candidate_receipt_digest: Digest32,
    pub pricing_set_digest: Digest32,
    pub portfolio_receipt_digest: Digest32,
    pub exercise_receipt_digest: Digest32,
    pub portfolio_audit_digest: Digest32,
    pub compilation_binding_id: StableId,
    pub disposition: AgentdPromptProductDispositionV2,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl AgentdPromptProductReceiptV2 {
    pub fn validate(&self) -> Result<(), AgentdPromptProductErrorV2> {
        for digest in [
            self.candidate_receipt_digest,
            self.pricing_set_digest,
            self.portfolio_receipt_digest,
            self.exercise_receipt_digest,
            self.portfolio_audit_digest,
            self.receipt_digest,
        ] {
            if digest.is_zero() {
                return Err(AgentdPromptProductErrorV2::Integrity);
            }
        }
        if self.compilation_binding_id.as_str().is_empty()
            || self.authority.grants_any()
            || self.receipt_digest != self.compute_receipt_digest()
        {
            return Err(AgentdPromptProductErrorV2::Integrity);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.prompt-product-receipt.v2".to_vec();
        for digest in [
            self.candidate_receipt_digest,
            self.pricing_set_digest,
            self.portfolio_receipt_digest,
            self.exercise_receipt_digest,
            self.portfolio_audit_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        let compilation_id = self.compilation_binding_id.as_str().as_bytes();
        bytes.extend_from_slice(
            &u64::try_from(compilation_id.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(compilation_id);
        match self.disposition {
            AgentdPromptProductDispositionV2::Staged(stage) => {
                bytes.push(0);
                bytes.push(match stage {
                    PromptRuntimeStageDisposition::Inserted => 0,
                    PromptRuntimeStageDisposition::Unchanged => 1,
                });
            }
            AgentdPromptProductDispositionV2::NoIntervention => bytes.push(1),
            AgentdPromptProductDispositionV2::Wait => bytes.push(2),
            AgentdPromptProductDispositionV2::RejectStale => bytes.push(3),
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Debug)]
pub enum AgentdPromptProductErrorV2 {
    InvalidProductBinding(&'static str),
    Optimizer(VerifiedPromptError),
    Pipeline(String),
    Runtime(String),
    TerminalNotObserved,
    TerminalNotFinal,
    Ledger(String),
    Integrity,
}

impl fmt::Display for AgentdPromptProductErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdPromptProductErrorV2 {}

/// Execute the complete authenticated prompt product path and stage its exact
/// bytes for the existing runtime.codex provider boundary.
#[allow(clippy::too_many_arguments)]
pub fn optimize_compile_and_stage_prompt_v2(
    pipeline: &AgentdPromptPipelineOwner,
    verifier: &LearningEvidenceVerifierV1,
    thread_id: &str,
    turn_id: &str,
    model: &str,
    requested_deadline_ms: u64,
    request: AgentdPromptOptimizationRequestV2,
) -> Result<AgentdPromptProductReceiptV2, AgentdPromptProductErrorV2> {
    validate_product_request(&request)?;
    let candidates = pipeline
        .enumerate_candidates(request.enumeration)
        .map_err(|error| AgentdPromptProductErrorV2::Pipeline(error.to_string()))?;
    let candidates = VerifiedEnumeratedPromptCandidatesV2::try_from_v1(candidates)
        .map_err(AgentdPromptProductErrorV2::Optimizer)?;
    let candidate_receipt_digest = candidates.receipt.receipt_digest;
    let priced = price_factors_verified_v2(
        candidates,
        request.completeness,
        request.pricing_evidence,
        verifier,
        &request.pricing_policy,
        request.exercise.now_unix_ms,
    )
    .map_err(AgentdPromptProductErrorV2::Optimizer)?;
    let pricing_set_digest = priced.pricing_set_digest;
    let portfolio = select_portfolio_verified_v2(
        &priced,
        &request.graph,
        request.pair_evidence,
        verifier,
        request.portfolio,
        request.exercise.now_unix_ms,
    )
    .map_err(AgentdPromptProductErrorV2::Optimizer)?;
    let exercise_context = PromptExerciseContextV2 {
        request: request.exercise,
        current_graph_generation_digest: request.graph.generation_digest,
        current_trust_digest: verifier.trust_digest(),
        current_scope_digest: verifier.scope_digest(),
        current_objective_digest: verifier.objective_digest(),
        current_authority_epoch: verifier.authority_epoch(),
    };
    let exercise = verify_exercise_context_v2(&portfolio, exercise_context.clone())
        .map_err(AgentdPromptProductErrorV2::Optimizer)?;
    let compilation_binding_id = prompt_verified_compilation_id_v2(
        candidate_receipt_digest,
        pricing_set_digest,
        portfolio.receipt.receipt_digest,
        exercise.receipt_digest,
        exercise.portfolio_audit_digest(),
    )?;
    if request.compilation.compilation_id != compilation_binding_id {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "compilation identity",
        ));
    }
    let disposition = match exercise.decision {
        PromptExerciseActionV1::Exercise => {
            if request.compilation.token_budget
                < u64::from(portfolio.receipt.total_token_upper_bound)
            {
                return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
                    "compilation token budget",
                ));
            }
            let stage = pipeline
                .compile_and_stage(
                    thread_id,
                    turn_id,
                    model,
                    requested_deadline_ms,
                    portfolio.as_v1(),
                    &exercise_context.request,
                    request.compilation,
                )
                .map_err(|error| AgentdPromptProductErrorV2::Pipeline(error.to_string()))?;
            AgentdPromptProductDispositionV2::Staged(stage)
        }
        PromptExerciseActionV1::NoIntervention => {
            AgentdPromptProductDispositionV2::NoIntervention
        }
        PromptExerciseActionV1::Wait => AgentdPromptProductDispositionV2::Wait,
        PromptExerciseActionV1::RejectStale => AgentdPromptProductDispositionV2::RejectStale,
    };
    let mut receipt = AgentdPromptProductReceiptV2 {
        candidate_receipt_digest,
        pricing_set_digest,
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        exercise_receipt_digest: exercise.receipt_digest,
        portfolio_audit_digest: exercise.portfolio_audit_digest(),
        compilation_binding_id,
        disposition,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate()?;
    Ok(receipt)
}

/// Admit only a terminal runtime.codex delivery observation into learning.ledger.
/// A dispatch claim, missing terminal, NotDispatched or Indeterminate outcome is
/// never converted into exposure evidence.
pub fn append_prompt_terminal_to_learning_v2(
    runtime: &AgentdPromptRuntimeOwner,
    ledger: &mut LearningLedger,
    attempt_id: &str,
    expected_portfolio_receipt_digest: Digest32,
    lineage: PromptDeliveryLineageV1,
) -> Result<AppendReceipt, AgentdPromptProductErrorV2> {
    if expected_portfolio_receipt_digest.is_zero()
        || lineage.portfolio_receipt_digest != expected_portfolio_receipt_digest
    {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "portfolio lineage",
        ));
    }
    let terminal = runtime
        .terminal_record(attempt_id)
        .map_err(|error| AgentdPromptProductErrorV2::Runtime(error.to_string()))?
        .ok_or(AgentdPromptProductErrorV2::TerminalNotObserved)?;
    terminal
        .validate()
        .map_err(|error| AgentdPromptProductErrorV2::Runtime(error.to_string()))?;
    match terminal.outcome {
        PromptRuntimeTerminalOutcomeV1::Delivered | PromptRuntimeTerminalOutcomeV1::Rejected => {}
        PromptRuntimeTerminalOutcomeV1::NotDispatched
        | PromptRuntimeTerminalOutcomeV1::Indeterminate => {
            return Err(AgentdPromptProductErrorV2::TerminalNotFinal);
        }
    }
    let observation = terminal
        .delivery_observation
        .ok_or(AgentdPromptProductErrorV2::TerminalNotObserved)?;
    ledger
        .append_runtime_prompt_delivery_v1(lineage, observation)
        .map_err(|error| AgentdPromptProductErrorV2::Ledger(error.to_string()))
}

pub fn prompt_verified_compilation_id_v2(
    candidate_receipt_digest: Digest32,
    pricing_set_digest: Digest32,
    portfolio_receipt_digest: Digest32,
    exercise_receipt_digest: Digest32,
    portfolio_audit_digest: Digest32,
) -> Result<StableId, AgentdPromptProductErrorV2> {
    let mut bytes = b"hepta.agentd.prompt-verified-compilation.v2".to_vec();
    for digest in [
        candidate_receipt_digest,
        pricing_set_digest,
        portfolio_receipt_digest,
        exercise_receipt_digest,
        portfolio_audit_digest,
    ] {
        if digest.is_zero() {
            return Err(AgentdPromptProductErrorV2::Integrity);
        }
        bytes.extend_from_slice(digest.as_array());
    }
    StableId::new(format!(
        "prompt-compilation:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| AgentdPromptProductErrorV2::Integrity)
}

fn validate_product_request(
    request: &AgentdPromptOptimizationRequestV2,
) -> Result<(), AgentdPromptProductErrorV2> {
    if request.enumeration.now_unix_ms != request.exercise.now_unix_ms
        || request.compilation.now_unix_ms != request.exercise.now_unix_ms
    {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "time snapshot",
        ));
    }
    if request.enumeration.model_tuple != request.exercise.model_tuple
        || request.compilation.registry_model_tuple != request.exercise.model_tuple
    {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "model tuple",
        ));
    }
    if request.enumeration.objective_digest != request.completeness.context.objective_digest
        || request.enumeration.state_digest != request.completeness.receipt.state_digest
        || request.enumeration.state_digest != request.exercise.current_state_digest
        || request.enumeration.selection_grammar_digest
            != request.completeness.context.selection_grammar_digest
    {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "objective or state",
        ));
    }
    if request.enumeration.generation_vector_digest
        != request.graph.generation_vector_digest
        || request.enumeration.generation_vector_digest
            != request.exercise.generation_vector_digest
    {
        return Err(AgentdPromptProductErrorV2::InvalidProductBinding(
            "generation vector",
        ));
    }
    Ok(())
}
