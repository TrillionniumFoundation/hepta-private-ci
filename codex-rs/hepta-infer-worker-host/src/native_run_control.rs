//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use super::AppServerModelDriver;
use super::NativeFinalUseAdmission;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::Result;

/// Explicit local capacity policy; the first request pins the journal's limit.
/// This limits admitted runs, not provider tokens, billing or device memory.
pub struct NativeLocalSlotAdmission {
    pub request_id: String,
    pub maximum_in_flight: usize,
}

/// Compatibility name for callers compiled against the earlier local-slot API.
/// New production code should use NativeLocalSlotAdmission so it cannot be
/// confused with the target economic/resource reservation contract.
#[doc(hidden)]
pub type NativeAdmission = NativeLocalSlotAdmission;

impl AppServerModelDriver {
    /// Reserves before any provider call, journals dispatch before `turn/start`,
    /// and commits real observations before returning them to the caller.
    /// Reopening a possibly dispatched run never invokes a model again.
    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeLocalSlotAdmission,
        final_use: Option<NativeFinalUseAdmission<'_>>,
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
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record.observation {
                return Ok(output);
            }
            let dispatch = record.dispatch.ok_or("missing durable dispatch binding")?;
            let output = NativeRunOutput {
                thread_id: dispatch.thread_id,
                turn_id: record.turn_id.unwrap_or_default(),
                model: record.request.model,
                model_provider: dispatch.model_provider,
                status: NativeRunStatus::Indeterminate,
                output: String::new(),
                output_digest: Some(digest(b"")),
                output_retained: true,
                observed_output_tokens: None,
                terminal_observed: false,
                owner_authority: NativeOwnerAuthority::Unverified,
                final_use_authorized: dispatch.final_use_witness.is_some(),
                stop_reason: Some(
                    "reopened after possible dispatch; reservation held, no replay".to_string(),
                ),
            };
            let settled = control.settle_native(&record.request.request_id, output)?;
            return settled
                .observation
                .ok_or_else(|| "missing durable reopened observation".into());
        }
        let final_use = final_use.ok_or(
            "kernel final-use authority and an independently signed grant are required before provider dispatch",
        )?;
        let request = record.request;
        let request_id = request.request_id.clone();
        match self
            .run_once(
                control,
                &request,
                &final_use,
                prompt,
                context_query,
                cancellation,
            )
            .await
        {
            Ok(mut output) => {
                if !output.terminal_observed && cancellation.is_cancelled() {
                    control.cancel_native(&request_id)?;
                }
                output.output_digest = Some(digest(output.output.as_bytes()));
                output.output_retained = true;
                control.settle_native(&request_id, output.clone())?;
                Ok(output)
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
