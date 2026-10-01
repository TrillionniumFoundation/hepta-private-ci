//! Deterministic matching of owner run receipts to the worker boundary.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

use super::NativeIntelligenceRunBinding;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

pub(crate) const LOCAL_CANCELLED: &str = "cancelled";
pub(crate) const LOCAL_DEADLINE_ELAPSED: &str = "deadline elapsed";

/// Bind the run lifecycle epoch to the same owner's observed current epoch,
/// independently from the control connection's process spawn generation.
pub(super) fn validate_intelligence_owner_generation(
    expected_generation: u64,
    observed_generation: u64,
    run: &AgentRunReceipt,
) -> std::result::Result<(), String> {
    if expected_generation == 0
        || observed_generation != expected_generation
        || run.generation != expected_generation
    {
        return Err("owning intelligence lifecycle generation is stale or mixed".to_string());
    }
    Ok(())
}

pub(super) fn verify_intelligence_recovery_receipt<Now>(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    run: &AgentRunReceipt,
    output: &NativeRunOutput,
    observed_now: Now,
) -> std::result::Result<(), String>
where
    Now: FnOnce() -> std::result::Result<u64, String>,
{
    if matches_intelligence_terminal_receipt(generation, binding, run, output)? {
        return Ok(());
    }
    let mut revision = binding
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| "intelligence dispatch revision overflow during recovery".to_string())?;
    verify_intelligence_receipt(generation, binding, &mut revision, run, observed_now()?)
}

/// Historical owner publication records the worker boundary, not just the
/// provider status. Matching this already-observed fact requires no live clock.
pub(super) fn matches_intelligence_terminal_receipt(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    run: &AgentRunReceipt,
    output: &NativeRunOutput,
) -> std::result::Result<bool, String> {
    let revision = binding
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| "intelligence dispatch revision overflow during recovery".to_string())?;
    validate_intelligence_receipt_binding(generation, binding, revision, run)?;
    Ok(run.terminal_observed
        && run.revision > revision
        && intelligence_terminal_phase(output).is_ok_and(|phase| phase == run.phase))
}

pub(super) fn validate_intelligence_receipt_binding(
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

pub(super) fn verify_intelligence_receipt(
    generation: u64,
    binding: &NativeIntelligenceRunBinding,
    revision: &mut u64,
    run: &AgentRunReceipt,
    now_ms: u64,
) -> std::result::Result<(), String> {
    validate_intelligence_receipt_binding(generation, binding, *revision, run)?;
    let deadline_elapsed = now_ms >= run.deadline_ms;
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

/// Publish the local worker outcome independently from provider completion.
/// Late Completed after cancellation or a deadline cannot make Agentd succeed.
pub(crate) fn intelligence_terminal_phase(output: &NativeRunOutput) -> Result<AgentRunPhase> {
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

#[cfg(test)]
#[path = "native_intelligence_receipt_tests.rs"]
mod tests;
