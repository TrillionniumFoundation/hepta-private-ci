//! Bound provider observations and monotonic native recovery evidence.

use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_protocol::ServerNotification;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_codex_adapter::AdapterStatus;
use codex_hepta_codex_adapter::adapt_observed_event;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::CodexTurnBinding;
use super::LOCAL_CANCELLED;
use super::LOCAL_DEADLINE_ELAPSED;
use super::MAX_OUTPUT_BYTES;
use super::NativeBoundaryStatus;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::downgrade_for_owner_loss;
use super::intelligence_owner::IntelligenceObservation;

/// One exact Agent owns both health and optional intelligence run observation.
/// The interruption grace has no owner and cannot restore lost authority.
pub(super) struct NativeObservationOwner<'a> {
    pub agent: &'a AgentdClient,
    pub intelligence: Option<IntelligenceObservation<'a>>,
}

/// Check time and cancellation independently of stream readiness. An always
/// ready stream must not starve either local boundary.
pub(super) fn check_observation_boundary(
    deadline: Instant,
    cancellation: &CancellationToken,
) -> std::result::Result<(), String> {
    if cancellation.is_cancelled() {
        return Err(LOCAL_CANCELLED.to_string());
    }
    if Instant::now() >= deadline {
        return Err(LOCAL_DEADLINE_ELAPSED.to_string());
    }
    Ok(())
}

pub(super) fn observe_event(
    output: &mut NativeRunOutput,
    observed: &RemoteAppServerObservedEvent,
    binding: &CodexTurnBinding,
) -> std::result::Result<bool, String> {
    let AppServerEvent::ServerNotification(notification) = observed.event() else {
        return Ok(false);
    };
    match notification.as_ref() {
        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
            if usage.thread_id == output.thread_id && usage.turn_id == output.turn_id =>
        {
            let observed_tokens = u64::try_from(usage.token_usage.total.output_tokens)
                .map_err(|_| "invalid negative provider usage".to_string())?;
            if output
                .observed_output_tokens
                .is_some_and(|previous| observed_tokens < previous)
            {
                return Err("provider cumulative usage regressed".to_string());
            }
            output.observed_output_tokens = Some(observed_tokens);
        }
        ServerNotification::TurnCompleted(completed)
            if completed.thread_id == output.thread_id && completed.turn.id == output.turn_id =>
        {
            let receipt = adapt_observed_event(&binding.intent, &binding.turn_id, observed)
                .map_err(|error| format!("invalid App Server terminal witness: {error}"))?
                .ok_or_else(|| "turn/completed did not produce terminal receipt".to_string())?;
            let physical_boundary = match receipt.status {
                AdapterStatus::Succeeded => {
                    output.status = NativeRunStatus::Completed;
                    NativeBoundaryStatus::Succeeded
                }
                AdapterStatus::Failed => {
                    output.status = NativeRunStatus::Failed;
                    NativeBoundaryStatus::Failed
                }
                AdapterStatus::Interrupted => {
                    output.status = NativeRunStatus::Interrupted;
                    NativeBoundaryStatus::Interrupted
                }
                _ => return Err("nonterminal adapter status for turn/completed".to_string()),
            };
            if output.boundary_status == NativeBoundaryStatus::Indeterminate {
                output.boundary_status = physical_boundary;
            }
            output.codex_terminal_correlation_digest = Some(
                receipt
                    .correlation_digest
                    .ok_or_else(|| "terminal receipt omitted correlation digest".to_string())?
                    .to_string(),
            );
            if let Some(error) = &completed.turn.error {
                output.stop_reason = Some(error.message.chars().take(1024).collect());
            }
            output.terminal_observed = true;
            downgrade_for_owner_loss(output);
            return Ok(true);
        }
        _ => {}
    }
    Ok(false)
}

#[cfg(test)]
#[path = "native_observation_tests.rs"]
mod tests;
