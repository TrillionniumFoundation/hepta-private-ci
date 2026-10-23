//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_types::IdProfileV1;
use codex_hepta_types::StableId;
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

pub use super::input::NativeIntelligenceRunBinding;
use super::input::bounded_diagnostic;
pub(super) use super::input::digest;
use super::input::native_source_payload_digest;
use super::input::validate_native_composition;
use super::recovery::preserve_recovery_evidence;
use super::recovery::reconcile_with_cancellation;

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
        validate_native_composition(&context_query, intelligence)?;
        StableId::with_profile(&admission.request_id, IdProfileV1::Stable)?;
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
            let (record, recovery) = reconcile_with_cancellation(
                control,
                &record.request.request_id,
                cancellation,
                |record| async move {
                    self.reconcile_existing(&record, &prompt, intelligence, cancellation)
                        .await
                },
            )
            .await?;
            if let Some(reconciled) = recovery {
                let settled = control.settle_native(&record.request.request_id, reconciled)?;
                return settled.observation.ok_or_else(|| {
                    "durable reconciliation omitted its normalized observation".into()
                });
            }
            if let Some(mut output) = record.observation.clone() {
                preserve_recovery_evidence(&record, &mut output)?;
                let settled = control.settle_native(&record.request.request_id, output)?;
                return settled.observation.ok_or_else(|| {
                    "durable recovery fallback omitted its normalized observation".into()
                });
            }
            let dispatch = record
                .dispatch
                .as_ref()
                .ok_or("missing durable dispatch binding")?;
            let mut output = NativeRunOutput {
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
            preserve_recovery_evidence(&record, &mut output)?;
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
                    let reason = bounded_diagnostic(format_args!("{error}"));
                    control.stop_native_before_dispatch(&request_id, reason)?;
                }
                Err(error)
            }
        }
    }
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
