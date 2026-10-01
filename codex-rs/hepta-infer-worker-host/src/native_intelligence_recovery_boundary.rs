//! A fresh ThreadRead terminal refines provider facts, never a durable stop.
//! Cached terminals bypass this normalization and retain their exact digest.

use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use tokio::time::Instant;

use super::super::AppServerModelDriver;
use super::super::LOCAL_CANCELLED;
use super::super::NativeIntelligenceRunBinding;
use super::super::RPC_TIMEOUT;
use super::super::intelligence_observation::NativeIntelligenceObservationBindingV1;

impl AppServerModelDriver {
    pub(super) async fn revalidate_intelligence_recovery_v1(
        &self,
        record: &NativeRunRecord,
        binding: &NativeIntelligenceRunBinding,
        output: &mut NativeRunOutput,
    ) {
        match AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        ) {
            Ok(owner) => {
                let mut current = NativeIntelligenceObservationBindingV1 {
                    run: binding.clone(),
                    revision: binding.expected_revision,
                    generation: self.config.generation + 1,
                };
                current
                    .revalidate_recovered_terminal(&owner, output, Instant::now() + RPC_TIMEOUT)
                    .await;
            }
            Err(_) => {
                output.boundary_status = NativeBoundaryStatus::Quarantined;
                retain_stop_reason(output, "intelligence recovery control identity unavailable");
            }
        }
        retain_intelligence_recovery_boundary_v1(record, output);
        // Check the terminal publication receipt before the first terminal is
        // frozen. A cancel racing the status check cannot leave a successful
        // immutable observation with only a later reconciliation diagnostic.
        if let Err(reason) = self
            .reconcile_intelligence_terminal(Some(binding), output)
            .await
        {
            if matches!(
                output.boundary_status,
                NativeBoundaryStatus::Succeeded
                    | NativeBoundaryStatus::Failed
                    | NativeBoundaryStatus::Interrupted
                    | NativeBoundaryStatus::Indeterminate
            ) {
                output.boundary_status = if reason == LOCAL_CANCELLED {
                    NativeBoundaryStatus::Cancelled
                } else {
                    NativeBoundaryStatus::Quarantined
                };
            }
            retain_stop_reason(output, reason);
        }
    }
}

pub(super) fn retain_intelligence_recovery_boundary_v1(
    record: &NativeRunRecord,
    output: &mut NativeRunOutput,
) {
    if let Some(previous) = record.observation.as_ref() {
        // ThreadRead does not report token usage. Keep previously observed
        // usage rather than replacing a known cumulative count with None.
        if output.observed_output_tokens.is_none() {
            output.observed_output_tokens = previous.observed_output_tokens;
        }
        if let NativeOwnerAuthority::Lost { .. } = &previous.owner_authority {
            output.owner_authority = previous.owner_authority.clone();
            output.boundary_status = NativeBoundaryStatus::Quarantined;
        } else {
            output.boundary_status = match (previous.boundary_status, output.boundary_status) {
                (NativeBoundaryStatus::Quarantined, _) | (_, NativeBoundaryStatus::Quarantined) => {
                    NativeBoundaryStatus::Quarantined
                }
                (NativeBoundaryStatus::TimedOut, _) | (_, NativeBoundaryStatus::TimedOut) => {
                    NativeBoundaryStatus::TimedOut
                }
                (NativeBoundaryStatus::Cancelled, _) | (_, NativeBoundaryStatus::Cancelled) => {
                    NativeBoundaryStatus::Cancelled
                }
                (_, current) => current,
            };
        }
        if matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
            || matches!(
                previous.boundary_status,
                NativeBoundaryStatus::Cancelled
                    | NativeBoundaryStatus::TimedOut
                    | NativeBoundaryStatus::Quarantined
            )
        {
            retain_stop_reason(
                output,
                previous
                    .stop_reason
                    .as_deref()
                    .unwrap_or("durable native stop retained during terminal reconciliation"),
            );
        }
    }
    if matches!(output.owner_authority, NativeOwnerAuthority::Lost { .. }) {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
    }
    if record.cancel_requested {
        if !matches!(
            output.boundary_status,
            NativeBoundaryStatus::TimedOut | NativeBoundaryStatus::Quarantined
        ) {
            output.boundary_status = NativeBoundaryStatus::Cancelled;
        }
        retain_stop_reason(
            output,
            "durable native cancellation retained during terminal reconciliation",
        );
    }
}

fn retain_stop_reason(output: &mut NativeRunOutput, reason: &str) {
    output.stop_reason = Some(match output.stop_reason.take() {
        Some(existing) if existing == reason => existing,
        Some(existing) => format!("{existing}; {reason}").chars().take(1024).collect(),
        None => reason.chars().take(1024).collect(),
    });
}
