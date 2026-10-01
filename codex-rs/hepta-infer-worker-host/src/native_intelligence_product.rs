//! One product composition over the existing Agentd, learning-ledger and App
//! Server owners.
//!
//! Physical prompt bytes are obtained only from the owner-backed prompt
//! realization/context delivery frozen into the Agentd prepared run. The host
//! durably acknowledges the exact Decision before model send, uses the sole
//! App Server path, observes the same Agentd terminal run and then records the
//! independently authenticated Outcome.

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
use codex_hepta_agentd::AgentdIntelligencePhysicalPromptV1;
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
use crate::native_app_server::NativeRunStatus;

pub type NativeIntelligenceProductResult<T> =
    std::result::Result<T, Box<dyn StdError + Send + Sync>>;

#[derive(Clone, Debug)]
pub struct NativeIntelligenceProductReceiptV1 {
    pub decision: AgentdIntelligenceLearningReceiptV1,
    pub execution: NativeRunOutput,
    pub outcome: Option<AgentdIntelligenceLearningReceiptV1>,
    /// The physical observation remains durable and visible even if learning
    /// or the terminal-control RPC needs exact reconciliation.
    pub reconciliation_required: bool,
    /// Fixed stage classification only; no evidence, provider or secret payload.
    pub reconciliation_reason: Option<String>,
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

    pub async fn execute<F, Fut>(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        admitted: AgentdIntelligenceAdmittedOutcomeV1,
        decision_request: AgentdIntelligenceDecisionAppendV1,
        cancellation: &CancellationToken,
        build_outcome: F,
    ) -> NativeIntelligenceProductResult<NativeIntelligenceProductReceiptV1>
    where
        F: FnOnce(&PreparedAgentdIntelligenceRunV1, &RunReceipt, &NativeRunOutput) -> Fut,
        Fut: std::future::Future<
                Output = NativeIntelligenceProductResult<AgentdIntelligenceOutcomeAppendV1>,
            >,
    {
        let (prepared, attached, reconciliation_only) = match admitted {
            AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            } => (prepared, run_receipt, false),
            AgentdIntelligenceAdmittedOutcomeV1::ReconciliationRequired {
                prepared,
                run_receipt,
            } => (prepared, run_receipt, true),
            AgentdIntelligenceAdmittedOutcomeV1::Abstained => {
                return Err("abstained intelligence run has no physical execution".into());
            }
            AgentdIntelligenceAdmittedOutcomeV1::SlowPath => {
                return Err("slow-path intelligence run requires a different product route".into());
            }
        };
        if admission.request_id != attached.run_id {
            return Err("native admission identity differs from the canonical run".into());
        }
        let physical = prepared.physical_prompt()?;
        let prompt = String::from_utf8(physical.payload.clone())
            .map_err(|_| "owner-backed physical prompt is not UTF-8")?;
        let binding = binding_for_admitted_v1(&prepared, &attached, &physical)?;

        let decision = self
            .learning
            .record_decision_before_dispatch_v1(&prepared, decision_request)
            .await?;
        require_acknowledged("Decision", &decision)?;

        let (execution, control_reconciliation_reason) = if reconciliation_only {
            let reconciled = self
                .driver
                .reconcile_intelligence(control, admission, prompt, binding.clone(), cancellation)
                .await?;
            (reconciled.execution, reconciled.reconciliation_reason)
        } else {
            (
                self.driver
                    .run_intelligence(
                        control,
                        admission,
                        prompt,
                        /*context_query*/ None,
                        binding.clone(),
                        cancellation,
                    )
                    .await?,
                None,
            )
        };
        if !execution.terminal_observed {
            return Ok(NativeIntelligenceProductReceiptV1 {
                decision,
                execution,
                outcome: None,
                reconciliation_required: true,
                reconciliation_reason: Some(
                    control_reconciliation_reason
                        .unwrap_or("physical terminal observation unavailable")
                        .to_string(),
                ),
            });
        }
        // Never discard a terminal provider observation merely because its
        // acknowledgement/evidence producer or learning destination is absent.
        let closure: std::result::Result<AgentdIntelligenceLearningReceiptV1, &'static str> =
            async {
                let terminal = self
                    .agentd
                    .run_status(binding.run_id.clone())
                    .await
                    .map_err(|_| "terminal Agentd status unavailable")?
                    .ok_or("Agentd terminal receipt unavailable")?;
                let terminal = local_terminal_receipt_v1(terminal, &execution)?;
                let request = build_outcome(&prepared, &terminal, &execution)
                    .await
                    .map_err(|_| "terminal Outcome evidence unavailable")?;
                if request.run_receipt != terminal
                    || request.provider_terminal_digest
                        != native_provider_terminal_digest_v1(&execution)
                            .map_err(|_| "terminal provider observation invalid")?
                {
                    return Err("Outcome source substituted the observed physical terminal");
                }
                self.learning
                    .record_outcome_after_terminal_v1(&prepared, request)
                    .await
                    .map_err(|_| "terminal Outcome append unavailable")
            }
            .await;
        let (outcome, closure_reason) = match closure {
            Ok(receipt) => (Some(receipt), None),
            Err(reason) => (None, Some(reason.to_string())),
        };
        let reconciliation_required = !outcome.as_ref().is_some_and(|receipt| {
            receipt.disposition == AgentdIntelligenceLearningDispositionV1::Acknowledged
                && receipt.append.is_some()
        });
        Ok(NativeIntelligenceProductReceiptV1 {
            decision,
            execution,
            outcome,
            reconciliation_required,
            reconciliation_reason: if reconciliation_required {
                closure_reason.or_else(|| {
                    Some(
                        control_reconciliation_reason
                            .unwrap_or("terminal Outcome append not acknowledged")
                            .to_string(),
                    )
                })
            } else {
                None
            },
        })
    }
}

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
    physical: &AgentdIntelligencePhysicalPromptV1,
) -> NativeIntelligenceProductResult<NativeIntelligenceRunBinding> {
    let attachment = prepared.context_attachment();
    if receipt.phase != RunPhase::ContextAttached
        || receipt.terminal_observed
        || receipt.run_id != attachment.run_id
        || receipt.authority_epoch != attachment.authority_epoch
        || receipt.generation != attachment.generation
        || receipt.fence_digest != attachment.fence_digest
        || receipt.deadline_ms != attachment.deadline_ms
        || receipt.context_digest.as_deref() != Some(attachment.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref()
            != Some(attachment.compilation_receipt_digest.as_str())
        || attachment.compilation_receipt_digest != prepared.envelope.envelope_digest.to_string()
        || attachment.context_digest != physical.attachment_digest.to_string()
        || prepared.envelope.prompt_receipt_digest != physical.prompt_stage_digest
        || prepared.envelope.context_receipt_digest != physical.attachment_digest
        || Digest32::of_bytes(&physical.payload) != physical.payload_digest
    {
        return Err(
            "admitted intelligence run is not the exact owner-backed ContextAttached envelope"
                .into(),
        );
    }
    Ok(NativeIntelligenceRunBinding {
        run_id: receipt.run_id.clone(),
        expected_revision: receipt.revision,
        context_digest: attachment.context_digest,
        envelope_digest: prepared.envelope.envelope_digest.to_string(),
        prompt_digest: physical.payload_digest.to_string(),
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
    execution: &NativeRunOutput,
) -> std::result::Result<RunReceipt, &'static str> {
    if !execution.terminal_observed {
        return Err("physical terminal observation unavailable");
    }
    let expected_phase = match execution.status {
        NativeRunStatus::Completed => RunPhase::Succeeded,
        NativeRunStatus::Failed => RunPhase::Failed,
        NativeRunStatus::Interrupted => RunPhase::Cancelled,
        NativeRunStatus::Indeterminate => {
            return Err("physical terminal observation unavailable");
        }
    };
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
        || !matches!(
            phase,
            RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
        )
    {
        return Err("terminal Agentd receipt not verified");
    }
    // An acknowledged Outcome must describe the same physical terminal. An
    // already-terminal Agentd run cannot wash away a conflicting observation
    // simply because both receipts independently claim terminality.
    if phase != expected_phase {
        return Err("terminal Agentd phase differs from physical observation");
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

#[cfg(test)]
#[path = "native_intelligence_product_tests.rs"]
mod tests;
