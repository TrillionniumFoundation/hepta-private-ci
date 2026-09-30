//! Preserve the durable observation cut and retry owner publication without
//! replaying an external inference effect.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;
use std::time::Duration;

use super::AppServerModelDriver;
use super::NativeBoundaryStatus;
use super::NativeIntelligenceRunBinding;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::RPC_TIMEOUT;
use super::Result;
use super::remaining_before;

pub(super) fn retain_observed_facts(
    recovered: &mut NativeRunOutput,
    previous: Option<&NativeRunOutput>,
) {
    let Some(previous) = previous else {
        return;
    };
    // thread/read does not contain turn-local token usage. Preserve the actual
    // observed lower bound rather than replacing it with unknown usage.
    recovered.observed_output_tokens = previous.observed_output_tokens;
    if matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. }) {
        recovered.owner_authority = previous.owner_authority.clone();
    }
    if matches!(
        previous.boundary_status,
        NativeBoundaryStatus::Cancelled
            | NativeBoundaryStatus::TimedOut
            | NativeBoundaryStatus::Quarantined
    ) || matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
    {
        recovered.boundary_status = previous.boundary_status;
        recovered.stop_reason = match (&previous.stop_reason, &recovered.stop_reason) {
            (Some(previous), Some(current)) if previous != current => Some(
                format!("{previous}; {current}")
                    .chars()
                    .take(1024)
                    .collect(),
            ),
            (Some(previous), _) => Some(previous.clone()),
            (None, current) => current.clone(),
        };
    }
}

pub(super) fn send_budget_before_effect(
    control: &mut DurableInferenceControl,
    token: NativePreEffectAbortToken,
    deadline_ms: u64,
) -> Result<(Duration, NativePreEffectAbortToken)> {
    match remaining_before(deadline_ms) {
        Ok(budget) => Ok((budget.min(RPC_TIMEOUT), token)),
        Err(error) => {
            // Context revalidation can consume the last execution budget. The
            // live one-shot proof still establishes that turn/start was unsent.
            control.abort_native_before_effect(token, error.to_string())?;
            Err(error)
        }
    }
}

impl AppServerModelDriver {
    pub(super) async fn publish_intelligence_terminal(
        &self,
        binding: &NativeIntelligenceRunBinding,
        output: &NativeRunOutput,
    ) -> Result<()> {
        if !output.terminal_observed
            || output.owner_authority != NativeOwnerAuthority::ObservedReady
            || output.codex_terminal_correlation_digest.is_none()
        {
            return Err("intelligence terminal publication requires exact observed correlation and owner authority".into());
        }
        let phase = if output.succeeded() {
            AgentRunPhase::Succeeded
        } else if matches!(
            output.boundary_status,
            NativeBoundaryStatus::Cancelled
                | NativeBoundaryStatus::TimedOut
                | NativeBoundaryStatus::Interrupted
        ) {
            AgentRunPhase::Cancelled
        } else {
            AgentRunPhase::Failed
        };
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let current = owner
            .run_status(binding.run_id.clone())
            .await?
            .ok_or("intelligence run disappeared before terminal publication")?;
        validate_intelligence_receipt(&current, binding, self.config.generation)?;
        // An acknowledgement lost after the owner committed is already settled.
        if current.terminal_observed {
            return if current.phase == phase {
                Ok(())
            } else {
                Err("Agentd terminal state conflicts with the durable operation boundary".into())
            };
        }
        let receipt = owner
            .run_observe_terminal(
                binding.run_id.clone(),
                current.revision,
                phase,
                /*terminal_observed*/ true,
            )
            .await?;
        validate_intelligence_receipt(&receipt, binding, self.config.generation)?;
        if receipt.phase != phase || !receipt.terminal_observed {
            return Err("Agentd did not acknowledge the exact intelligence terminal".into());
        }
        Ok(())
    }
}

fn validate_intelligence_receipt(
    receipt: &AgentRunReceipt,
    binding: &NativeIntelligenceRunBinding,
    generation: u64,
) -> Result<()> {
    if receipt.run_id != binding.run_id
        || receipt.generation != generation
        || receipt.revision < binding.expected_revision
        || receipt.context_digest.as_deref() != Some(binding.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref() != Some(binding.envelope_digest.as_str())
    {
        return Err("Agentd terminal receipt lost the intelligence handoff binding".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_recovery_tests.rs"]
mod tests;
