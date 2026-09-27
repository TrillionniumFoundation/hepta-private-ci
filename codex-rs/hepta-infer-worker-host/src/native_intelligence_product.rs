//! One product composition over the existing Agentd, learning-ledger and App
//! Server owners.
//!
//! This module does not introduce a second executor or fact store. It requires
//! the exact Agentd-prepared run, durably acknowledges that run's Decision, uses
//! the existing `AppServerModelDriver::run_intelligence` physical path, reads the
//! terminal receipt back from the same Agentd lifecycle owner, and then durably
//! acknowledges the matching Outcome.

use std::error::Error as StdError;
use std::sync::Arc;

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdIntelligenceAdmittedOutcomeV1;
use codex_hepta_agentd::AgentdIntelligenceDecisionAppendV1;
use codex_hepta_agentd::AgentdIntelligenceLearningDispositionV1;
use codex_hepta_agentd::AgentdIntelligenceLearningHostV1;
use codex_hepta_agentd::AgentdIntelligenceLearningReceiptV1;
use codex_hepta_agentd::AgentdIntelligenceOutcomeAppendV1;
use codex_hepta_agentd::PreparedAgentdIntelligenceRunV1;
use codex_hepta_agentd::RunPhase;
use codex_hepta_agentd::RunReceipt;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::AppServerModelDriver;
use crate::native_app_server::NativeAdmission;
use crate::native_app_server::NativeIntelligenceRunBinding;
use crate::native_app_server::NativeRunOutput;

pub type NativeIntelligenceProductResult<T> =
    std::result::Result<T, Box<dyn StdError + Send + Sync>>;

#[derive(Clone, Debug)]
pub struct NativeIntelligenceProductReceiptV1 {
    pub decision: AgentdIntelligenceLearningReceiptV1,
    pub execution: NativeRunOutput,
    pub outcome: Option<AgentdIntelligenceLearningReceiptV1>,
}

pub struct NativeIntelligenceProductHostV1 {
    driver: AppServerModelDriver,
    agentd: AgentdClient,
    learning: Arc<AgentdIntelligenceLearningHostV1>,
}

impl NativeIntelligenceProductHostV1 {
    #[must_use]
    pub fn new(
        driver: AppServerModelDriver,
        agentd: AgentdClient,
        learning: Arc<AgentdIntelligenceLearningHostV1>,
    ) -> Self {
        Self {
            driver,
            agentd,
            learning,
        }
    }

    /// Execute one canonical intelligence run without caller-assembled
    /// intermediate dispatch state.
    ///
    /// `build_outcome` supplies the independently authenticated observer record
    /// after the physical terminal state is known. It cannot alter the prepared
    /// run, Agentd terminal receipt or durable native observation passed to it.
    #[allow(clippy::too_many_arguments)]
    pub async fn execute<F>(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        admitted: AgentdIntelligenceAdmittedOutcomeV1,
        decision_request: AgentdIntelligenceDecisionAppendV1,
        cancellation: &CancellationToken,
        build_outcome: F,
    ) -> NativeIntelligenceProductResult<NativeIntelligenceProductReceiptV1>
    where
        F: FnOnce(
            &PreparedAgentdIntelligenceRunV1,
            &RunReceipt,
            &NativeRunOutput,
        ) -> NativeIntelligenceProductResult<AgentdIntelligenceOutcomeAppendV1>,
    {
        let (prepared, attached) = match admitted {
            AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            } => (prepared, run_receipt),
            AgentdIntelligenceAdmittedOutcomeV1::Abstained => {
                return Err("abstained intelligence run has no physical execution".into());
            }
            AgentdIntelligenceAdmittedOutcomeV1::SlowPath => {
                return Err("slow-path intelligence run requires a different product route".into());
            }
        };
        let binding = binding_for_admitted_v1(&prepared, &attached, &prompt)?;

        let decision = self
            .learning
            .record_decision_before_dispatch_v1(&prepared, decision_request)
            .await?;
        require_acknowledged("Decision", &decision)?;

        let execution = self
            .driver
            .run_intelligence(
                control,
                admission,
                prompt,
                context_query,
                binding.clone(),
                cancellation,
            )
            .await?;

        if !execution.terminal_observed {
            return Ok(NativeIntelligenceProductReceiptV1 {
                decision,
                execution,
                outcome: None,
            });
        }

        let terminal = self
            .agentd
            .run_status(binding.run_id.clone())
            .await?
            .ok_or("Agentd terminal receipt disappeared after physical observation")?;
        let terminal = local_terminal_receipt_v1(terminal)?;
        let outcome_request = build_outcome(&prepared, &terminal, &execution)?;
        let outcome = self
            .learning
            .record_outcome_after_terminal_v1(&prepared, outcome_request)
            .await?;
        require_acknowledged("Outcome", &outcome)?;

        Ok(NativeIntelligenceProductReceiptV1 {
            decision,
            execution,
            outcome: Some(outcome),
        })
    }
}

/// Digest the exact durable provider observation used by an Outcome builder.
/// The separately authenticated observer evidence remains mandatory in the
/// learning request; this digest is not self-issued evaluation authority.
pub fn native_provider_terminal_digest_v1(
    output: &NativeRunOutput,
) -> NativeIntelligenceProductResult<Digest32> {
    if !output.terminal_observed {
        return Err("provider observation is not terminal".into());
    }
    let mut bytes = b"hepta.runtime.codex.native-terminal.v1\0".to_vec();
    bytes.extend_from_slice(&serde_json::to_vec(output)?);
    Ok(Digest32::of_bytes(&bytes))
}

fn binding_for_admitted_v1(
    prepared: &PreparedAgentdIntelligenceRunV1,
    receipt: &RunReceipt,
    prompt: &str,
) -> NativeIntelligenceProductResult<NativeIntelligenceRunBinding> {
    if prompt.is_empty() {
        return Err("canonical physical prompt is empty".into());
    }
    let attachment = prepared.context_attachment();
    if receipt.phase != RunPhase::ContextAttached
        || receipt.terminal_observed
        || receipt.run_id != attachment.run_id
        || receipt.context_digest.as_deref() != Some(attachment.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref()
            != Some(attachment.compilation_receipt_digest.as_str())
        || attachment.compilation_receipt_digest != prepared.envelope.envelope_digest.to_string()
    {
        return Err("admitted intelligence run is not the exact ContextAttached envelope".into());
    }
    Ok(NativeIntelligenceRunBinding {
        run_id: receipt.run_id.clone(),
        expected_revision: receipt.revision,
        context_digest: attachment.context_digest,
        envelope_digest: prepared.envelope.envelope_digest.to_string(),
        prompt_digest: Digest32::of_bytes(prompt.as_bytes()).to_string(),
    })
}

fn require_acknowledged(
    kind: &'static str,
    receipt: &AgentdIntelligenceLearningReceiptV1,
) -> NativeIntelligenceProductResult<()> {
    if receipt.disposition != AgentdIntelligenceLearningDispositionV1::Acknowledged
        || receipt.append.is_none()
    {
        return Err(format!(
            "{kind} was not durably acknowledged; physical progression is forbidden"
        )
        .into());
    }
    Ok(())
}

fn local_terminal_receipt_v1(
    value: AgentRunReceipt,
) -> NativeIntelligenceProductResult<RunReceipt> {
    let phase = match value.phase {
        AgentRunPhase::Admitted => RunPhase::Admitted,
        AgentRunPhase::ContextAttached => RunPhase::ContextAttached,
        AgentRunPhase::Dispatched => RunPhase::Dispatched,
        AgentRunPhase::Cancelling => RunPhase::Cancelling,
        AgentRunPhase::Cancelled => RunPhase::Cancelled,
        AgentRunPhase::Succeeded => RunPhase::Succeeded,
        AgentRunPhase::Failed => RunPhase::Failed,
        AgentRunPhase::Indeterminate => RunPhase::Indeterminate,
    };
    if !value.terminal_observed
        || !matches!(phase, RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed)
    {
        return Err("physical observation lacks a terminal Agentd receipt".into());
    }
    Ok(RunReceipt {
        run_id: value.run_id,
        revision: value.revision,
        phase,
        context_digest: value.context_digest,
        authority_epoch: value.authority_epoch,
        generation: value.generation,
        fence_digest: value.fence_digest,
        deadline_ms: value.deadline_ms,
        cancel_reason: value.cancel_reason,
        cancel_ack_deadline_ms: value.cancel_ack_deadline_ms,
        compilation_receipt_digest: value.compilation_receipt_digest,
        terminal_observed: value.terminal_observed,
        idempotent: value.idempotent,
    })
}
