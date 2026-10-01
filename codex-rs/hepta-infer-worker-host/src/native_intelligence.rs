//! Exact owning-Agent intelligence handoff and cancellation observation.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
use tokio::time::Instant;
use tokio::time::timeout_at;

use super::LOCAL_CANCELLED;
use super::LOCAL_DEADLINE_ELAPSED;
use super::NativeBoundaryStatus;
use super::NativeIntelligenceRunBinding;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::RPC_TIMEOUT;
use super::Result;
use super::input::bounded_diagnostic;
use super::input::validate_intelligence_binding;
use super::unix_time_ms;

pub(super) struct IntelligenceObservation<'a> {
    pub binding: &'a NativeIntelligenceRunBinding,
    pub revision: &'a mut u64,
}

pub(super) async fn verify_intelligence_execution(
    owner: &AgentdClient,
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    revision: &mut u64,
    deadline: Instant,
) -> std::result::Result<(), String> {
    let run = read_intelligence_run(owner, binding, deadline).await?;
    verify_intelligence_receipt(generation, binding, revision, &run)
}

async fn read_intelligence_run(
    owner: &AgentdClient,
    binding: &NativeIntelligenceRunBinding,
    deadline: Instant,
) -> std::result::Result<AgentRunReceipt, String> {
    timeout_at(
        deadline.min(Instant::now() + RPC_TIMEOUT),
        owner.run_status(binding.run_id.clone()),
    )
    .await
    .map_err(|_| "owning intelligence status check timed out".to_string())?
    .map_err(|error| {
        bounded_diagnostic(format_args!(
            "owning intelligence status check failed: {error}"
        ))
    })?
    .ok_or_else(|| "owning intelligence run disappeared".to_string())
}

/// Reconcile a verified physical terminal through the existing exact owner
/// CAS. Recovery never issues another turn/start or reconstructs a handoff.
pub(super) async fn reconcile_intelligence_terminal(
    owner: &AgentdClient,
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    output: &mut NativeRunOutput,
    deadline: Instant,
) -> std::result::Result<(), String> {
    let run = read_intelligence_run(owner, binding, deadline).await?;
    let minimum_revision = binding
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| "intelligence dispatch revision overflow during recovery".to_string())?;
    validate_intelligence_receipt_binding(generation, binding, minimum_revision, &run)?;
    if run.terminal_observed {
        if let Err(reason) = verify_intelligence_recovery_receipt(generation, binding, &run, output)
        {
            apply_intelligence_failure(output, reason);
            verify_intelligence_recovery_receipt(generation, binding, &run, output)?;
        }
        return Ok(());
    }
    match run.phase {
        AgentRunPhase::Dispatched | AgentRunPhase::Cancelling => {
            let mut revision = minimum_revision;
            if let Err(reason) =
                verify_intelligence_receipt(generation, binding, &mut revision, &run)
            {
                if reason != LOCAL_CANCELLED && reason != LOCAL_DEADLINE_ELAPSED {
                    return Err(reason);
                }
                apply_intelligence_failure(output, reason);
            }
        }
        AgentRunPhase::Indeterminate => {
            // An indeterminate owner may still retain an earlier cancellation
            // intent. Exact provider terminal truth cannot erase that intent.
            if unix_time_ms().map_err(|error| error.to_string())? >= run.deadline_ms {
                apply_intelligence_failure(output, LOCAL_DEADLINE_ELAPSED.to_string());
            } else if run.cancel_reason.is_some() {
                apply_intelligence_failure(output, LOCAL_CANCELLED.to_string());
            }
        }
        AgentRunPhase::Admitted
        | AgentRunPhase::ContextAttached
        | AgentRunPhase::Cancelled
        | AgentRunPhase::Succeeded
        | AgentRunPhase::Failed => {
            return Err(
                "owning intelligence recovery target is not an exact dispatched run".to_string(),
            );
        }
    }
    commit_intelligence_terminal(owner, generation, binding, run.revision, output)
        .await
        .map_err(|error| {
            bounded_diagnostic(format_args!(
                "Agentd recovered terminal reconciliation required: {error}"
            ))
        })
}

fn verify_intelligence_recovery_receipt(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    run: &AgentRunReceipt,
    output: &NativeRunOutput,
) -> std::result::Result<(), String> {
    let mut revision = binding
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| "intelligence dispatch revision overflow during recovery".to_string())?;
    validate_intelligence_receipt_binding(generation, binding, revision, run)?;
    if run.terminal_observed && run.revision > revision {
        match run.phase {
            AgentRunPhase::Succeeded
                if output.terminal_observed
                    && output.status == NativeRunStatus::Completed
                    && output.boundary_status == NativeBoundaryStatus::Succeeded
                    && output.stop_reason.is_none() =>
            {
                return Ok(());
            }
            AgentRunPhase::Failed
                if output.terminal_observed && output.status == NativeRunStatus::Failed =>
            {
                return Ok(());
            }
            AgentRunPhase::Cancelled
                if output.terminal_observed
                    && (output.status == NativeRunStatus::Interrupted
                        || output.boundary_status == NativeBoundaryStatus::Cancelled) =>
            {
                return Ok(());
            }
            AgentRunPhase::Admitted
            | AgentRunPhase::ContextAttached
            | AgentRunPhase::Dispatched
            | AgentRunPhase::Cancelling
            | AgentRunPhase::Cancelled
            | AgentRunPhase::Succeeded
            | AgentRunPhase::Failed
            | AgentRunPhase::Indeterminate => {}
        }
    }
    verify_intelligence_receipt(generation, binding, &mut revision, run)
}

fn validate_intelligence_receipt_binding(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    revision: u64,
    run: &AgentRunReceipt,
) -> std::result::Result<(), String> {
    if run.run_id != binding.run_id
        || run.generation != generation
        || run.context_digest.as_deref() != Some(binding.context_digest.as_str())
        || run.compilation_receipt_digest.as_deref() != Some(binding.envelope_digest.as_str())
        || run.revision < revision
    {
        return Err("owning intelligence execution binding is stale or mixed".to_string());
    }
    Ok(())
}

fn verify_intelligence_receipt(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    revision: &mut u64,
    run: &AgentRunReceipt,
) -> std::result::Result<(), String> {
    validate_intelligence_receipt_binding(generation, binding, *revision, run)?;
    let deadline_elapsed = unix_time_ms().map_err(|error| error.to_string())? >= run.deadline_ms;
    match run.phase {
        AgentRunPhase::Dispatched if run.revision == *revision && !run.terminal_observed => {
            if deadline_elapsed {
                Err(LOCAL_DEADLINE_ELAPSED.to_string())
            } else {
                Ok(())
            }
        }
        AgentRunPhase::Cancelling | AgentRunPhase::Cancelled => {
            // Only an exact owner's cancellation may advance this local cursor.
            // A newer success/attachment never grants another physical send.
            if run.cancel_reason.is_none()
                || (run.phase == AgentRunPhase::Cancelled) != run.terminal_observed
            {
                return Err("owning intelligence cancellation receipt is inconsistent".to_string());
            }
            *revision = run.revision;
            Err(if deadline_elapsed {
                LOCAL_DEADLINE_ELAPSED.to_string()
            } else {
                LOCAL_CANCELLED.to_string()
            })
        }
        AgentRunPhase::Admitted
        | AgentRunPhase::ContextAttached
        | AgentRunPhase::Dispatched
        | AgentRunPhase::Succeeded
        | AgentRunPhase::Failed
        | AgentRunPhase::Indeterminate => {
            Err("owning intelligence run is no longer the exact dispatched revision".to_string())
        }
    }
}

/// A later owner observation cannot upgrade an already denied worker boundary.
pub(super) fn apply_intelligence_failure(output: &mut NativeRunOutput, reason: String) {
    if !matches!(
        output.boundary_status,
        NativeBoundaryStatus::Cancelled
            | NativeBoundaryStatus::TimedOut
            | NativeBoundaryStatus::Quarantined
    ) {
        output.boundary_status = super::classify_observation_failure(&reason);
    }
    output.stop_reason = output.stop_reason.take().or(Some(reason));
}

/// Publish the local worker outcome independently from provider completion.
/// Late Completed after cancellation or a deadline cannot make Agentd succeed.
pub(super) fn intelligence_terminal_phase(
    output: &NativeRunOutput,
) -> super::Result<AgentRunPhase> {
    if !output.terminal_observed || output.status == NativeRunStatus::Indeterminate {
        return Err("cannot commit a nonterminal intelligence observation".into());
    }
    match output.boundary_status {
        NativeBoundaryStatus::Succeeded if output.succeeded() => Ok(AgentRunPhase::Succeeded),
        NativeBoundaryStatus::Succeeded
        | NativeBoundaryStatus::Failed
        | NativeBoundaryStatus::TimedOut
        | NativeBoundaryStatus::Quarantined => Ok(AgentRunPhase::Failed),
        NativeBoundaryStatus::Interrupted | NativeBoundaryStatus::Cancelled => {
            Ok(AgentRunPhase::Cancelled)
        }
        NativeBoundaryStatus::Indeterminate => {
            Err("cannot commit an indeterminate intelligence boundary".into())
        }
    }
}

pub(super) async fn reconcile_intelligence_start_unknown(
    owner: &AgentdClient,
    binding: Option<&NativeIntelligenceRunBinding>,
    revision: Option<u64>,
    mut output: NativeRunOutput,
) -> NativeRunOutput {
    if let (Some(binding), Some(revision)) = (binding, revision)
        && let Err(error) = owner
            .run_observe_terminal(
                binding.run_id.clone(),
                revision,
                AgentRunPhase::Indeterminate,
                false,
            )
            .await
    {
        let reason = output.stop_reason.take().unwrap_or_default();
        output.stop_reason = Some(bounded_diagnostic(format_args!(
            "{reason}; Agentd reconciliation remains required: {error}"
        )));
    }
    output
}

pub(super) async fn require_intelligence_handoff(
    owner: &AgentdClient,
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
) -> Result<u64> {
    validate_intelligence_binding(binding)?;
    let run = owner
        .run_status(binding.run_id.clone())
        .await?
        .ok_or("intelligence run is not admitted in Agentd")?;
    if run.run_id != binding.run_id
        || run.generation != generation
        || run.phase != AgentRunPhase::ContextAttached
        || run.revision != binding.expected_revision
        || run.context_digest.as_deref() != Some(binding.context_digest.as_str())
        || run.compilation_receipt_digest.as_deref() != Some(binding.envelope_digest.as_str())
        || run.terminal_observed
    {
        return Err("Agentd intelligence handoff is stale or mixed".into());
    }
    Ok(run.revision)
}

pub(super) async fn commit_intelligence_terminal(
    owner: &AgentdClient,
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    expected_revision: u64,
    output: &NativeRunOutput,
) -> Result<()> {
    if !output.terminal_observed
        || !matches!(output.owner_authority, NativeOwnerAuthority::ObservedReady)
        || output.codex_terminal_correlation_digest.is_none()
    {
        return Err("intelligence terminal publication requires exact observed correlation and current owner authority".into());
    }
    let phase = intelligence_terminal_phase(output)?;
    let receipt = owner
        .run_observe_terminal(
            binding.run_id.clone(),
            expected_revision,
            phase,
            /*terminal_observed*/ true,
        )
        .await?;
    if receipt.run_id != binding.run_id
        || receipt.generation != generation
        || receipt.phase != phase
        || !receipt.terminal_observed
        || receipt.context_digest.as_deref() != Some(binding.context_digest.as_str())
        || receipt.compilation_receipt_digest.as_deref() != Some(binding.envelope_digest.as_str())
    {
        return Err("Agentd terminal receipt lost the intelligence handoff binding".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_intelligence_tests.rs"]
mod tests;
