//! Local durable admission around the actual App Server driver.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
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

/// Synchronous durable-control port used by the native model host. Implementations
/// must hold the single-writer journal lock only for one bounded state transition;
/// they must not retain that lock across provider/network awaits.
pub trait NativeControlPort {
    fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn cancel_native(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn stop_native_before_turn_start(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> std::result::Result<NativeRunRecord, ControlError>;
    fn native_record(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<Option<NativeRunRecord>, ControlError>;
}

impl NativeControlPort for DurableInferenceControl {
    fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::reserve_native(self, request, maximum_in_flight)
    }

    fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::dispatch_native(self, request_id, dispatch)
    }

    fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::native_started(self, request_id, turn_id)
    }

    fn cancel_native(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::cancel_native(self, request_id)
    }

    fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::stop_native_before_dispatch(self, request_id, reason)
    }

    fn stop_native_before_turn_start(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::stop_native_before_turn_start(self, request_id, reason)
    }

    fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        DurableInferenceControl::settle_native(self, request_id, output)
    }

    fn native_record(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<Option<NativeRunRecord>, ControlError> {
        Ok(DurableInferenceControl::native_record(self, request_id).cloned())
    }
}

/// Reopen-per-transition production owner. The stable journal lock is therefore
/// held for replay + one fsynced mutation only, never for model execution,
/// provider streaming, health polling, cancellation grace, or reconciliation.
#[derive(Clone, Debug)]
pub struct TransientNativeControl {
    path: PathBuf,
    capacity: usize,
}

impl TransientNativeControl {
    pub fn new(
        path: impl AsRef<Path>,
        capacity: usize,
    ) -> std::result::Result<Self, ControlError> {
        let path = path.as_ref().to_path_buf();
        let control = DurableInferenceControl::open(&path, capacity)?;
        drop(control);
        Ok(Self { path, capacity })
    }

    fn with_control<T>(
        &self,
        operation: impl FnOnce(&mut DurableInferenceControl) -> std::result::Result<T, ControlError>,
    ) -> std::result::Result<T, ControlError> {
        let mut control = DurableInferenceControl::open(&self.path, self.capacity)?;
        operation(&mut control)
    }
}

impl NativeControlPort for TransientNativeControl {
    fn reserve_native(
        &mut self,
        request: NativeRequest,
        maximum_in_flight: usize,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.reserve_native(request, maximum_in_flight))
    }

    fn dispatch_native(
        &mut self,
        request_id: &str,
        dispatch: NativeDispatch,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.dispatch_native(request_id, dispatch))
    }

    fn native_started(
        &mut self,
        request_id: &str,
        turn_id: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.native_started(request_id, turn_id))
    }

    fn cancel_native(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.cancel_native(request_id))
    }

    fn stop_native_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.stop_native_before_dispatch(request_id, reason))
    }

    fn stop_native_before_turn_start(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.stop_native_before_turn_start(request_id, reason))
    }

    fn settle_native(
        &mut self,
        request_id: &str,
        output: NativeRunOutput,
    ) -> std::result::Result<NativeRunRecord, ControlError> {
        self.with_control(|control| control.settle_native(request_id, output))
    }

    fn native_record(
        &mut self,
        request_id: &str,
    ) -> std::result::Result<Option<NativeRunRecord>, ControlError> {
        self.with_control(|control| Ok(control.native_record(request_id).cloned()))
    }
}

impl AppServerModelDriver {
    /// Reserves before any provider call, journals dispatch before `turn/start`,
    /// and commits real observations before returning them to the caller.
    /// Reopening a possibly dispatched run never invokes a model again.
    pub async fn run<C: NativeControlPort>(
        &self,
        control: &mut C,
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
                observed_output_tokens: None,
                terminal_observed: false,
                owner_authority: NativeOwnerAuthority::Unverified,
                stop_reason: Some(
                    "reopened after possible dispatch; reservation held, no replay".to_string(),
                ),
            };
            control.settle_native(&record.request.request_id, output.clone())?;
            return Ok(output);
        }
        let request_id = record.request.request_id;
        match self
            .run_once(control, &request_id, prompt, context_query, cancellation)
            .await
        {
            Ok(output) => {
                if !output.terminal_observed && cancellation.is_cancelled() {
                    control.cancel_native(&request_id)?;
                }
                control.settle_native(&request_id, output.clone())?;
                Ok(output)
            }
            Err(error) => {
                if control
                    .native_record(&request_id)?
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
