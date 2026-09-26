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

/// Exact Agentd intelligence handoff that must already be attached before a
/// physical App Server turn can start.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeIntelligenceRunBinding {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

impl AppServerModelDriver {
    /// Reserves before any provider call, journals dispatch before `turn/start`,
    /// and commits real observations before returning them to the caller.
    /// Reopening a possibly dispatched run never invokes a model again.
    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            context_query,
            /*intelligence*/ None,
            cancellation,
        )
        .await
    }

    /// Execute the physical turn only after the exact Agentd intelligence
    /// envelope has reached ContextAttached. The worker cannot mint this binding.
    pub async fn run_intelligence(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: NativeIntelligenceRunBinding,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            context_query,
            Some(&intelligence),
            cancellation,
        )
        .await
    }

    async fn run_bound(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: Option<&NativeIntelligenceRunBinding>,
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
            payload_digest: native_source_payload_digest(
                &prompt,
                &context_query,
                &self.config.agentd_socket,
                self.config.timeout.as_millis(),
                intelligence,
            )?,
        };
        let record = control.reserve_native(request, admission.maximum_in_flight)?;
        if record.pre_effect_abort_pending {
            self.reconcile_pending_pre_effect_abort(control, &record)
                .await?;
            let reason = record
                .pre_dispatch_stop
                .as_deref()
                .unwrap_or("pre-effect abort pending");
            return Err(format!("request stopped before effect entry: {reason}").into());
        }
        if let Some(reason) = &record.pre_dispatch_stop {
            return Err(format!("request stopped before dispatch: {reason}").into());
        }
        if let Some(rejection) = &record.dispatch_rejection {
            return Err(format!(
                "turn/start was explicitly rejected before start ({:?}): {}",
                rejection.status, rejection.reason
            )
            .into());
        }
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record
                .observation
                .as_ref()
                .filter(|output| output.terminal_observed)
            {
                return Ok(output.clone());
            }
            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let settled = control.settle_native(&record.request.request_id, reconciled)?;
                return settled.observation.ok_or_else(|| {
                    "durable reconciliation omitted its normalized observation".into()
                });
            }
            if let Some(output) = record.observation {
                return Ok(output);
            }
            let dispatch = record
                .dispatch
                .as_ref()
                .ok_or("missing durable dispatch binding")?;
            let output = NativeRunOutput {
                thread_id: dispatch.thread_id.clone(),
                turn_id: record.turn_id.clone().unwrap_or_default(),
                model: record.request.model.clone(),
                model_provider: dispatch.model_provider.clone(),
                status: NativeRunStatus::Indeterminate,
                boundary_status: codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus::Indeterminate,
                output: String::new(),
                observed_output_tokens: None,
                terminal_observed: false,
                owner_authority: NativeOwnerAuthority::Unverified,
                stop_reason: Some(
                    "reopened after possible dispatch; thread/read found no exact terminal evidence; reservation held, no replay"
                        .to_string(),
                ),
                codex_terminal_correlation_digest: None,
            };
            control.settle_native(&record.request.request_id, output.clone())?;
            return Ok(output);
        }
        let request_id = record.request.request_id;
        match self
            .run_once(
                control,
                &request_id,
                prompt,
                context_query,
                intelligence,
                cancellation,
            )
            .await
        {
            Ok(output) => {
                if !output.terminal_observed && cancellation.is_cancelled() {
                    control.cancel_native(&request_id)?;
                }
                let settled = control.settle_native(&request_id, output)?;
                settled.observation.ok_or_else(|| {
                    "durable execution settlement omitted its normalized observation".into()
                })
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

fn native_source_payload_digest(
    prompt: &str,
    context_query: &Option<String>,
    socket: &std::path::Path,
    timeout_ms: u128,
    intelligence: Option<&NativeIntelligenceRunBinding>,
) -> Result<String> {
    let bytes = match intelligence {
        None => serde_json::to_vec(&(
            "hepta.native-request.v1",
            prompt,
            context_query,
            socket,
            timeout_ms,
        ))?,
        Some(binding) => serde_json::to_vec(&(
            "hepta.native-intelligence-request.v2",
            prompt,
            context_query,
            socket,
            timeout_ms,
            &binding.run_id,
            binding.expected_revision,
            &binding.context_digest,
            &binding.envelope_digest,
        ))?,
    };
    Ok(digest(&bytes))
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
