//! Agentd-owned composition path for the canonical prompt policy.
//!
//! This host sequences owner-native modules but does not absorb their facts:
//! registry admission stays with `prompt.registry`, selection stays with
//! `prompt.optimizer`, context compilation stays with `context.compiler`,
//! delivery observation stays with `runtime.codex`, and durable causal facts
//! stay with `learning.ledger`.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_codex_adapter::AppServerObservation;
use codex_hepta_codex_adapter::Error as CodexAdapterError;
use codex_hepta_codex_adapter::PromptDeliveryErrorV1;
use codex_hepta_codex_adapter::PromptDeliveryObservationV1;
use codex_hepta_codex_adapter::adapt;
use codex_hepta_codex_adapter::intent_for_context_attachment_v1;
use codex_hepta_codex_adapter::observe_prompt_delivery_v1;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextDeliveryObservationV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::observe_delivery;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_intelligence::CanonicalPromptPolicyReceiptV1;
use codex_hepta_intelligence::CanonicalPromptPolicyRequestV1;
use codex_hepta_intelligence::PromptPolicyErrorV1;
use codex_hepta_intelligence::run_canonical_prompt_policy_v1;
use codex_hepta_learning_ledger::LearningDecisionV1;
use codex_hepta_learning_ledger::LearningDecisionV1Error;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::PromptCausalSupportV1;
use codex_hepta_learning_ledger::PromptLearningAppendReceiptV1;
use codex_hepta_learning_ledger::PromptLearningDecisionRequestV1;
use codex_hepta_learning_ledger::append_prompt_learning_decision_v1;
use codex_hepta_learning_ledger::canonical_prompt_action_set_digest;
use codex_hepta_prompt_optimizer::canonical_v1::ExerciseDispositionV1;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const ABSTAIN_ID: &str = "abstain";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRuntimeBindingV1 {
    pub serialization_id: StableId,
    pub serialized_payload_digest: Digest32,
    pub attachment_id: StableId,
    pub thread_id: StableId,
    pub method_id: StableId,
    pub deadline_ms: u64,
    pub adapter_now_ms: u64,
    pub delivery_observation_id: StableId,
    pub delivery_disposition: ContextDeliveryDispositionV2,
    pub delivery_observed_unix_ms: u64,
    pub app_server_observation: Option<AppServerObservation>,
    pub observed_token_positions: Option<Vec<u32>>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptLearningBindingV1 {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub learning_decision_id: StableId,
    pub policy_id: StableId,
    pub policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPolicyTurnRequestV1 {
    pub policy: CanonicalPromptPolicyRequestV1,
    pub runtime: PromptRuntimeBindingV1,
    pub learning: PromptLearningBindingV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPolicyTurnReceiptV1 {
    pub policy: CanonicalPromptPolicyReceiptV1,
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
    pub native_delivery: ContextDeliveryObservationV2,
    pub delivery: PromptDeliveryObservationV1,
    pub learning: PromptLearningAppendReceiptV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPolicyTurnErrorV1 {
    Policy(PromptPolicyErrorV1),
    PolicyRejected,
    MissingCompiledContext,
    MissingCanonicalContext,
    Context(ContextCompilerV2Error),
    Codex(CodexAdapterError),
    Delivery(PromptDeliveryErrorV1),
    Learning(LearningDecisionV1Error),
    InvalidRuntimeTime,
    InvalidLearningDigest,
    InvalidDeliveryObservation,
}

impl fmt::Display for PromptPolicyTurnErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptPolicyTurnErrorV1 {}

impl From<PromptPolicyErrorV1> for PromptPolicyTurnErrorV1 {
    fn from(value: PromptPolicyErrorV1) -> Self {
        Self::Policy(value)
    }
}

impl From<ContextCompilerV2Error> for PromptPolicyTurnErrorV1 {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Context(value)
    }
}

impl From<CodexAdapterError> for PromptPolicyTurnErrorV1 {
    fn from(value: CodexAdapterError) -> Self {
        Self::Codex(value)
    }
}

impl From<PromptDeliveryErrorV1> for PromptPolicyTurnErrorV1 {
    fn from(value: PromptDeliveryErrorV1) -> Self {
        Self::Delivery(value)
    }
}

impl From<LearningDecisionV1Error> for PromptPolicyTurnErrorV1 {
    fn from(value: LearningDecisionV1Error) -> Self {
        Self::Learning(value)
    }
}

/// Execute one complete prompt-policy observation chain through the existing
/// owner-native modules and append the resulting decision lineage to the
/// in-memory learning ledger.
///
/// The caller supplies the actual serialized payload digest and app-server
/// observation; this function never fabricates provider success. An exercise
/// rejection fails before serialization so stale context cannot enter the Codex
/// request path.
pub fn run_prompt_policy_turn_v1(
    registry: &PromptRegistry,
    ledger: &mut LearningLedger,
    request: PromptPolicyTurnRequestV1,
) -> Result<PromptPolicyTurnReceiptV1, PromptPolicyTurnErrorV1> {
    validate_bindings(&request.runtime, &request.learning)?;
    let policy = run_canonical_prompt_policy_v1(registry, request.policy)?;
    if policy.exercise.receipt.decision == ExerciseDispositionV1::Reject {
        return Err(PromptPolicyTurnErrorV1::PolicyRejected);
    }
    let compiled = policy
        .compiled_context
        .as_ref()
        .ok_or(PromptPolicyTurnErrorV1::MissingCompiledContext)?;
    let canonical_context = policy
        .canonical_context
        .as_ref()
        .ok_or(PromptPolicyTurnErrorV1::MissingCanonicalContext)?;
    let serialization = record_serialization(
        compiled,
        request.runtime.serialization_id,
        request.runtime.serialized_payload_digest,
    )?;
    let attachment = build_attachment(
        compiled,
        &serialization,
        request.runtime.attachment_id,
    )?;
    let intent = intent_for_context_attachment_v1(
        &attachment,
        request.runtime.thread_id,
        request.runtime.method_id,
        request.runtime.deadline_ms,
    )?;
    let adapter_receipt = adapt(
        request.runtime.adapter_now_ms,
        intent,
        request.runtime.app_server_observation,
    )?;
    let (observed_payload_digest, terminal_observed) = match request.runtime.delivery_disposition {
        ContextDeliveryDispositionV2::Delivered => (Some(attachment.payload_digest), true),
        ContextDeliveryDispositionV2::Rejected => (None, true),
        ContextDeliveryDispositionV2::Indeterminate => (None, false),
    };
    let native_delivery = observe_delivery(
        &attachment,
        request.runtime.delivery_observation_id,
        observed_payload_digest,
        terminal_observed,
        request.runtime.delivery_disposition,
        request.runtime.delivery_observed_unix_ms,
    )?;
    let delivery = observe_prompt_delivery_v1(
        compiled,
        canonical_context,
        &serialization,
        &attachment,
        &native_delivery,
        &adapter_receipt,
        request.runtime.observed_token_positions,
    )?;

    let abstain_id = StableId::new(ABSTAIN_ID.to_string())
        .map_err(|_| PromptPolicyTurnErrorV1::InvalidLearningDigest)?;
    let chosen_id = match policy.exercise.receipt.decision {
        ExerciseDispositionV1::Exercise => policy.portfolio.receipt.portfolio_id.clone(),
        ExerciseDispositionV1::Wait => abstain_id.clone(),
        ExerciseDispositionV1::Reject => return Err(PromptPolicyTurnErrorV1::PolicyRejected),
    };
    let mut action_ids = vec![abstain_id];
    if policy.portfolio.receipt.portfolio_id != action_ids[0] {
        action_ids.push(policy.portfolio.receipt.portfolio_id.clone());
    }
    let action_set_digest = canonical_prompt_action_set_digest(&action_ids)?;
    let learning_decision = LearningDecisionV1::new_deterministic(
        request.learning.learning_decision_id,
        request.learning.episode_id,
        action_set_digest,
        request.learning.policy_digest,
        chosen_id,
    )?;
    let learning = append_prompt_learning_decision_v1(
        ledger,
        PromptLearningDecisionRequestV1 {
            record_id: request.learning.record_id,
            objective_digest: policy.candidates.receipt.objective_digest,
            policy_id: request.learning.policy_id,
            action_ids,
            decision: learning_decision,
            support: PromptCausalSupportV1 {
                candidate_completeness_digest: policy.candidates.completeness_digest,
                prompt_candidate_receipt_digest: policy.candidates.receipt.receipt_digest,
                prompt_pricing_set_digest: policy.pricing.set_digest,
                prompt_portfolio_receipt_digest: policy.portfolio.receipt.receipt_digest,
                prompt_exercise_receipt_digest: policy.exercise.receipt.receipt_digest,
                context_compilation_receipt_digest: canonical_context.receipt_digest,
                delivery_observation_receipt_digest: delivery.receipt_digest,
                delivered: delivery.delivered,
            },
        },
    )?;

    let mut bytes = b"hepta.agentd.prompt-policy-turn.v1".to_vec();
    for digest in [
        policy.trace_digest,
        serialization.receipt_digest,
        attachment.attachment_digest,
        native_delivery.observation_digest,
        delivery.receipt_digest,
        learning.artifact.learning_decision.receipt_digest,
        learning.ledger_receipt.record_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let receipt_digest = Digest32::of_bytes(&bytes);
    Ok(PromptPolicyTurnReceiptV1 {
        policy,
        serialization,
        attachment,
        native_delivery,
        delivery,
        learning,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_bindings(
    runtime: &PromptRuntimeBindingV1,
    learning: &PromptLearningBindingV1,
) -> Result<(), PromptPolicyTurnErrorV1> {
    if runtime.serialized_payload_digest.is_zero()
        || learning.policy_digest.is_zero()
    {
        return Err(PromptPolicyTurnErrorV1::InvalidLearningDigest);
    }
    if runtime.deadline_ms == 0
        || runtime.adapter_now_ms == 0
        || runtime.delivery_observed_unix_ms == 0
        || runtime.adapter_now_ms >= runtime.deadline_ms
    {
        return Err(PromptPolicyTurnErrorV1::InvalidRuntimeTime);
    }
    match (
        runtime.delivery_disposition,
        runtime.app_server_observation.as_ref(),
    ) {
        (ContextDeliveryDispositionV2::Delivered, Some(observation))
        | (ContextDeliveryDispositionV2::Rejected, Some(observation)) => {
            if !observation.terminal_observed {
                return Err(PromptPolicyTurnErrorV1::InvalidDeliveryObservation);
            }
        }
        (ContextDeliveryDispositionV2::Indeterminate, None) => {}
        (ContextDeliveryDispositionV2::Indeterminate, Some(observation)) => {
            if observation.terminal_observed {
                return Err(PromptPolicyTurnErrorV1::InvalidDeliveryObservation);
            }
        }
        (_, None) => return Err(PromptPolicyTurnErrorV1::InvalidDeliveryObservation),
    }
    Ok(())
}

#[cfg(test)]
#[path = "prompt_policy_runtime_tests.rs"]
mod tests;
