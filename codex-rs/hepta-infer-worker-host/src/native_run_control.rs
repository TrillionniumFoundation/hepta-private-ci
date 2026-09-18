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
    /// Reserves before any provider call, journals dispatch before `turn/start`,
    /// and commits real observations before returning them to the caller.
    /// Reopening a possibly dispatched run never submits a replacement model turn.
    /// It uses Core's exact client-message reconciliation to recover the
    /// original turn or prove that no durable admission happened.
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
        if let Some(reason) = &record.reconciled_no_admission {
            return Err(format!(
                "request has no durable provider admission: {reason}; retry requires a new request id"
            )
            .into());
        }
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = &record.observation
                && output.terminal_observed
                && output.observed_output_tokens.is_some()
            {
                return Ok(output.clone());
            }
            let request_id = record.request.request_id.clone();
            let fallback = record.observation.clone().or_else(|| {
                record.dispatch.clone().map(|dispatch| NativeRunOutput {
                    thread_id: dispatch.thread_id,
                    turn_id: record.turn_id.clone().unwrap_or_default(),
                    model: record.request.model.clone(),
                    model_provider: dispatch.model_provider,
                    status: NativeRunStatus::Indeterminate,
                    output: String::new(),
                    observed_output_tokens: None,
                    terminal_observed: false,
                    owner_authority: NativeOwnerAuthority::Unverified,
                    stop_reason: Some(
                        "reopened after possible dispatch; exact reconciliation pending".to_string(),
                    ),
                })
            });
            match self
                .reconcile_once(control, &request_id, &prompt, cancellation)
                .await
            {
                Ok(Some(output)) => {
                    control.settle_native(&request_id, output.clone())?;
                    return Ok(output);
                }
                Ok(None) => {
                    return Err(
                        "Core reconciliation proved that the original request was never durably admitted; retry requires a new request id"
                            .into(),
                    );
                }
                Err(error) => {
                    let mut output = fallback.ok_or("missing durable dispatch binding")?;
                    if !output.terminal_observed {
                        output.stop_reason = Some(
                            format!("provider reconciliation unavailable: {error}")
                                .chars()
                                .take(1024)
                                .collect(),
                        );
                        control.settle_native(&request_id, output.clone())?;
                    }
                    return Ok(output);
                }
            }
        }
        let request_id = record.request.request_id;
        match self
            .run_once(
                control,
                &request_id,
                prompt.clone(),
                context_query,
                cancellation,
            )
            .await
        {
            Ok(output) => {
                if !output.terminal_observed && cancellation.is_cancelled() {
                    control.cancel_native(&request_id)?;
                }
                let settled = control.settle_native(&request_id, output.clone())?;
                if !output.terminal_observed && output.turn_id.is_empty() {
                    match self
                        .reconcile_once(control, &request_id, &prompt, cancellation)
                        .await
                    {
                        Ok(Some(recovered)) => {
                            control.settle_native(&request_id, recovered.clone())?;
                            return Ok(recovered);
                        }
                        Ok(None) => {
                            return Err(
                                "Core reconciliation proved that the original request was never durably admitted; retry requires a new request id"
                                    .into(),
                            );
                        }
                        Err(_) => {}
                    }
                }
                Ok(settled.observation.unwrap_or(output))
            }
            Err(error) => {
                if control
                    .native_record(&request_id)
                    .is_some_and(|record| record.state == NativeReservationState::Reserved)
                {
                    // Only Reserved proves turn/start could not have happened.
                    let reason: String = error.to_string().chars().take(1024).collect();
                    control.stop_native_before_dispatch(&request_id, reason)?;
                }
                Err(error)
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
