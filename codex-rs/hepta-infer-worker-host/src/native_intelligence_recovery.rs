//! Publish already-durable native terminals to the exact Agentd run.
//!
//! Publication is a retryable cross-owner acknowledgement, never a dispatch.
//! The native journal is authoritative for the observed physical terminal; the
//! Agentd coordinator remains authoritative for its current revision and fence.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::super::NativeBoundaryStatus;
use super::AppServerModelDriver;
use super::NativeIntelligenceRunBinding;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::Result;

impl AppServerModelDriver {
    pub(super) async fn reconcile_intelligence_terminal(
        &self,
        binding: Option<&NativeIntelligenceRunBinding>,
        output: &NativeRunOutput,
    ) -> Result<()> {
        let Some(binding) = binding else {
            return Ok(());
        };
        let Some(phase) = terminal_phase(output)? else {
            return Ok(());
        };
        StableId::new(binding.snapshot.run_id.clone())?;
        let context: Digest32 = binding.context_digest.parse()?;
        let envelope: Digest32 = binding.envelope_digest.parse()?;
        if binding.expected_revision == 0 || context.is_zero() || envelope.is_zero() {
            return Err("invalid intelligence terminal binding".into());
        }

        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let health = owner.health().await?;
        if health.fenced {
            return Err("Agentd terminal reconciliation requires an unfenced current owner".into());
        }
        // Already-observed terminals may settle during drain. The owner's read
        // and bound-write gates enforce Running/Draining, independently of
        // readiness to admit a new physical turn.
        let current = owner
            .run_reconciliation_state(binding.snapshot.run_id.clone())
            .await?
            .ok_or("intelligence terminal run has not been recovered by Agentd")?;
        // The control client pins the original Agentd spawn. The retained run
        // separately pins its admission-time lifecycle generation, including
        // when the same spawn advances to Draining before publication.
        binding.validate_current(&current)?;
        let current = current.receipt;
        if current.revision <= binding.expected_revision {
            return Err("Agentd recovered intelligence revision has not crossed dispatch".into());
        }
        if current.terminal_observed {
            if current.phase != phase {
                return Err("Agentd terminal conflicts with the durable native boundary".into());
            }
        } else if !matches!(
            current.phase,
            AgentRunPhase::Dispatched | AgentRunPhase::Cancelling | AgentRunPhase::Indeterminate
        ) {
            return Err("intelligence terminal run has not crossed dispatch".into());
        }

        // Recovery or cancellation may have advanced the coordinator since the
        // original ContextAttached binding. CAS its current exact receipt; a
        // concurrent change leaves this durable terminal available for retry.
        // Even an already-terminal acknowledgement uses the bound write so a
        // read-to-write ABA cannot acknowledge a different admission.
        let receipt = owner
            .run_observe_bound_terminal(codex_hepta_agentd::AgentRunTerminalObservation {
                binding: binding.expected_run_binding(current.revision),
                phase,
                terminal_observed: true,
            })
            .await?;
        binding.validate_receipt(&receipt)?;
        if receipt.phase != phase
            || !receipt.terminal_observed
            || receipt.revision < current.revision
            || receipt.authority_epoch != current.authority_epoch
            || receipt.fence_digest != current.fence_digest
            || receipt.deadline_ms != current.deadline_ms
        {
            return Err("Agentd terminal receipt lost the recovered run binding".into());
        }
        Ok(())
    }
}

fn terminal_phase(output: &NativeRunOutput) -> Result<Option<AgentRunPhase>> {
    if !output.terminal_observed {
        return Ok(None);
    }
    if output.owner_authority != NativeOwnerAuthority::ObservedReady
        || output.status == NativeRunStatus::Indeterminate
    {
        return Err("intelligence terminal publication requires observed owner authority".into());
    }
    let correlation: Digest32 = output
        .codex_terminal_correlation_digest
        .as_ref()
        .ok_or("intelligence terminal publication requires exact correlation")?
        .parse()?;
    if correlation.is_zero() {
        return Err("intelligence terminal correlation is zero".into());
    }
    // Provider completion does not undo local cancellation, timeout or
    // quarantine. Only the normalized local success boundary publishes success.
    let phase = match output.boundary_status {
        NativeBoundaryStatus::Succeeded if output.succeeded() => AgentRunPhase::Succeeded,
        NativeBoundaryStatus::Failed
        | NativeBoundaryStatus::TimedOut
        | NativeBoundaryStatus::Quarantined => AgentRunPhase::Failed,
        NativeBoundaryStatus::Interrupted | NativeBoundaryStatus::Cancelled => {
            AgentRunPhase::Cancelled
        }
        NativeBoundaryStatus::Succeeded | NativeBoundaryStatus::Indeterminate => {
            return Err("durable native terminal has no valid local terminal boundary".into());
        }
    };
    Ok(Some(phase))
}
