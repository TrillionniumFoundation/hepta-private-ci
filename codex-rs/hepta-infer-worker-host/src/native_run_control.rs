//! Local durable admission around the actual App Server driver.

#[path = "native_agentd_release.rs"]
mod agentd_release;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativePreparedInputV1;
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
pub use codex_hepta_infer_core::durable_control::native::NativeIntelligenceInputBindingV1 as NativeIntelligenceRunBinding;

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

    /// Recover using only the original owner-retained input. Possibly-sent
    /// requests remain reconcile-only through run_bound; no new model decision
    /// or turn/start is used to reconstruct historical execution.
    pub async fn resume(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        let record = control
            .native_record(&admission.request_id)
            .ok_or("native request is not present in the recovered owner journal")?;
        if record.state == NativeReservationState::Reserved {
            return Err(
                "resume is reconcile-only; an unsent request needs normal current admission".into(),
            );
        }
        let input = record.prepared_input.clone()
            .ok_or("historical native request has no persisted original input; explicit reconciliation is required")?;
        if input.agentd_socket != self.config.agentd_socket
            || u128::from(input.timeout_ms) != self.config.timeout.as_millis()
            || record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
        {
            return Err("resume configuration differs from the original native request".into());
        }
        self.run_bound(
            control,
            admission,
            input.prompt,
            input.context_query,
            input.intelligence.as_ref(),
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
        let input = NativePreparedInputV1 {
            schema_version: 1,
            prompt: prompt.clone(),
            context_query: context_query.clone(),
            agentd_socket: self.config.agentd_socket.clone(),
            timeout_ms: u64::try_from(self.config.timeout.as_millis())?,
            intelligence: intelligence.cloned(),
        };
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
        let record =
            control.reserve_native_prepared(request, admission.maximum_in_flight, input)?;
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
                self.release_settled_agentd_run(&record).await;
                return Ok(output.clone());
            }
            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let settled = control.settle_native(&record.request.request_id, reconciled)?;
                self.release_settled_agentd_run(&settled).await;
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
                self.release_settled_agentd_run(&settled).await;
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
