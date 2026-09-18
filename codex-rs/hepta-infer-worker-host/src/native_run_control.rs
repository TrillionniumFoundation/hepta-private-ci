//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use super::AppServerModelDriver;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::Result;

/// Explicit local capacity policy; the first request pins the journal's limit.
/// This limits admitted runs, not provider tokens, billing or device memory.
pub struct NativeAdmission {
    pub request_id: String,
    pub maximum_in_flight: usize,
}

impl AppServerModelDriver {
    /// Reserves before any provider call, journals provider identity before
    /// `turn/start`, and commits real observations before returning them.
    /// Reopening a possibly dispatched run reconciles the durable App Server
    /// thread/client-message identity; it never performs a blind fresh replay.
    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > super::MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if context_query
            .as_ref()
            .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err("context query must contain 1..2048 bytes".into());
        }
        let request = NativeRequest {
            request_id: admission.request_id,
            principal_id: self.config.agent_id.to_string(),
            worker_generation: self.config.generation,
            model: self.config.model.clone(),
            payload_digest: digest(&serde_json::to_vec(&(
                "hepta.native-request.v1",
                &prompt,
                &context_query,
                &self.config.agentd_socket,
                self.config.timeout.as_millis(),
            ))?),
        };
        let record = control.reserve_native(request, admission.maximum_in_flight)?;
        if let Some(reason) = &record.pre_dispatch_stop {
            return Err(format!("request stopped before dispatch: {reason}").into());
        }

        // A fully reconciled terminal observation is immutable and idempotent.
        // Terminal provider facts without usage are intentionally revisited so
        // late/replayed token evidence can complete accounting.
        if record.state == NativeReservationState::Released
            && record
                .observation
                .as_ref()
                .is_some_and(|output| output.observed_output_tokens.is_some())
        {
            return Ok(record.observation.expect("checked observation"));
        }

        let request_id = record.request.request_id.clone();
        let result = if record.state == NativeReservationState::Reserved {
            self.run_once(control, &request_id, prompt, context_query, cancellation)
                .await
        } else {
            self.reconcile_once(control, &request_id, prompt, context_query, cancellation)
                .await
        };

        match result {
            Ok(output) => {
                if !output.terminal_observed && cancellation.is_cancelled() {
                    let current = control
                        .native_record(&request_id)
                        .ok_or("native record disappeared")?;
                    if current.state != NativeReservationState::Released
                        && current.state != NativeReservationState::Reserved
                        && !current.cancel_requested
                    {
                        control.cancel_native(&request_id)?;
                    }
                }
                control.settle_native(&request_id, output.clone())?;
                Ok(output)
            }
            Err(error) => {
                let current = control
                    .native_record(&request_id)
                    .cloned()
                    .ok_or("native record disappeared")?;
                if current.state == NativeReservationState::Reserved {
                    // Only Reserved proves provider dispatch could not have happened.
                    let reason: String = error.to_string().chars().take(1024).collect();
                    control.stop_native_before_dispatch(&request_id, reason)?;
                    return Err(error);
                }
                // Reconciliation transport failure is itself not evidence of a
                // provider outcome. Persist a bounded indeterminate observation
                // while retaining the exact thread/turn binding for a later retry.
                let dispatch = current.dispatch.ok_or("missing durable dispatch binding")?;
                let output = NativeRunOutput {
                    thread_id: dispatch.thread_id,
                    turn_id: current.turn_id.unwrap_or_default(),
                    model: current.request.model,
                    model_provider: dispatch.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: current
                        .observation
                        .as_ref()
                        .map(|value| value.output.clone())
                        .unwrap_or_default(),
                    observed_output_tokens: current
                        .observation
                        .as_ref()
                        .and_then(|value| value.observed_output_tokens),
                    terminal_observed: false,
                    owner_authority: current
                        .observation
                        .as_ref()
                        .map(|value| value.owner_authority.clone())
                        .unwrap_or(NativeOwnerAuthority::Unverified),
                    stop_reason: Some(
                        format!("provider reconciliation unavailable: {error}")
                            .chars()
                            .take(1024)
                            .collect(),
                    ),
                };
                control.settle_native(&request_id, output.clone())?;
                Ok(output)
            }
        }
    }
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
