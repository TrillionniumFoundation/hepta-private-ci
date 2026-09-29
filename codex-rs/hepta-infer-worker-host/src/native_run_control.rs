//! Local durable admission around the actual App Server driver.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::control_port::NativeControlPort;
use codex_hepta_infer_core::control_contracts::OutputStorageMode;
#[cfg(test)]
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use crate::output_protection::NativeOutputProtector;

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

#[derive(Clone, Copy)]
struct NativeExecutionAuthority<'a> {
    plan: &'a VerifiedExecutionPlan,
    output_protector: Option<&'a dyn NativeOutputProtector>,
}

impl AppServerModelDriver {
    /// Compatibility profile for historical callers. It does not mint an exact
    /// quota/resource/model execution plan and therefore must not be selected by
    /// the production CLI.
    pub async fn run(
        &self,
        control: &mut dyn NativeControlPort,
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
            /*authority*/ None,
            cancellation,
        )
        .await
    }

    /// Production execution with an independently verified exact plan. Digest-
    /// only output policy needs no protector; encrypted policy is rejected before
    /// effect unless `run_authorized_with_output_protector` is used.
    pub async fn run_authorized(
        &self,
        control: &mut dyn NativeControlPort,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        plan: &VerifiedExecutionPlan,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            context_query,
            None,
            Some(NativeExecutionAuthority {
                plan,
                output_protector: None,
            }),
            cancellation,
        )
        .await
    }

    /// Production execution with a host-selected KMS/vault output protector.
    pub async fn run_authorized_with_output_protector(
        &self,
        control: &mut dyn NativeControlPort,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        plan: &VerifiedExecutionPlan,
        output_protector: &dyn NativeOutputProtector,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            context_query,
            None,
            Some(NativeExecutionAuthority {
                plan,
                output_protector: Some(output_protector),
            }),
            cancellation,
        )
        .await
    }

    /// Execute the physical turn only after the exact Agentd intelligence
    /// envelope has reached ContextAttached. This compatibility entrypoint does
    /// not replace an independently signed execution plan.
    pub async fn run_intelligence(
        &self,
        control: &mut dyn NativeControlPort,
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
            None,
            cancellation,
        )
        .await
    }

    /// Exact-plan production spelling for an Agentd intelligence handoff.
    pub async fn run_intelligence_authorized(
        &self,
        control: &mut dyn NativeControlPort,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: NativeIntelligenceRunBinding,
        plan: &VerifiedExecutionPlan,
        output_protector: Option<&dyn NativeOutputProtector>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            context_query,
            Some(&intelligence),
            Some(NativeExecutionAuthority {
                plan,
                output_protector,
            }),
            cancellation,
        )
        .await
    }

    async fn run_bound(
        &self,
        control: &mut dyn NativeControlPort,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: Option<&NativeIntelligenceRunBinding>,
        authority: Option<NativeExecutionAuthority<'_>>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        // Compatibility spelling remains source-compatible but cannot perform
        // reservations, RPCs or effects in the production library.
        if authority.is_none() && !cfg!(test) {
            return Err("an independently verified exact execution plan is required".into());
        }
        if prompt.is_empty() || prompt.len() > super::MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if context_query
            .as_ref()
            .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err("context query must contain 1..2048 bytes".into());
        }
        let payload_digest = native_source_payload_digest(
            &prompt,
            &context_query,
            &self.config.agentd_socket,
            self.config.timeout.as_millis(),
            intelligence,
        )?;
        let request = NativeRequest {
            request_id: admission.request_id,
            principal_id: self.config.agent_id.to_string(),
            worker_generation: self.config.generation,
            model: self.config.model.clone(),
            payload_digest,
        };
        let mut record = control
            .reserve_native(request, admission.maximum_in_flight)
            .await?;
        if let Some(authority) = authority {
            record = control
                .bind_native_execution(&record.request.request_id, authority.plan, unix_time_ms()?)
                .await?;
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
            if authority.is_none()
                && let Some(reconciled) = self.reconcile_existing(&record, &prompt).await?
            {
                let settled = control
                    .settle_native(&record.request.request_id, reconciled)
                    .await?;
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
                boundary_status: NativeBoundaryStatus::Indeterminate,
                output: String::new(),
                observed_output_tokens: None,
                terminal_observed: false,
                owner_authority: NativeOwnerAuthority::Unverified,
                stop_reason: Some(
                    "reopened after possible dispatch; no signed terminal receipt is present; reservation held, no replay"
                        .to_string(),
                ),
                codex_terminal_correlation_digest: None,
            };
            match authority {
                Some(authority) => {
                    control
                        .settle_native_authorized(
                            &record.request.request_id,
                            authority.plan,
                            unix_time_ms()?,
                            output.clone(),
                            None,
                        )
                        .await?;
                }
                None => {
                    control
                        .settle_native(&record.request.request_id, output.clone())
                        .await?;
                }
            }
            return Ok(output);
        }

        if let Some(authority) = authority
            && authority.plan.output_policy().storage_mode == OutputStorageMode::ExternalEncrypted
            && authority.output_protector.is_none()
        {
            control
                .stop_native_before_dispatch(
                    &record.request.request_id,
                    "external-encrypted output policy requires a host output protector".to_string(),
                )
                .await?;
            return Err("external-encrypted output policy requires a host output protector".into());
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
                    control.cancel_native(&request_id).await?;
                }
                match authority {
                    None => {
                        let settled = control.settle_native(&request_id, output).await?;
                        settled.observation.ok_or_else(|| {
                            "durable execution settlement omitted its normalized observation".into()
                        })
                    }
                    Some(authority) => {
                        let live_output = output.clone();
                        let now_unix_ms = unix_time_ms()?;
                        let protected_output = if output.output.is_empty() {
                            None
                        } else if authority.plan.output_policy().storage_mode
                            == OutputStorageMode::ExternalEncrypted
                        {
                            let protector = authority
                                .output_protector
                                .ok_or("missing native output protector")?;
                            match protector
                                .protect(authority.plan, output.output.as_bytes(), now_unix_ms)
                                .await
                            {
                                Ok(protected) => Some(protected),
                                Err(error) => {
                                    let quarantine = NativeRunOutput {
                                        thread_id: output.thread_id.clone(),
                                        turn_id: output.turn_id.clone(),
                                        model: output.model.clone(),
                                        model_provider: output.model_provider.clone(),
                                        status: NativeRunStatus::Indeterminate,
                                        boundary_status: NativeBoundaryStatus::Quarantined,
                                        output: String::new(),
                                        observed_output_tokens: output.observed_output_tokens,
                                        terminal_observed: false,
                                        owner_authority: NativeOwnerAuthority::Unverified,
                                        stop_reason: Some(
                                            format!(
                                                "output protection failed after effect: {error}"
                                            )
                                            .chars()
                                            .take(1024)
                                            .collect(),
                                        ),
                                        codex_terminal_correlation_digest: None,
                                    };
                                    control
                                        .settle_native_authorized(
                                            &request_id,
                                            authority.plan,
                                            now_unix_ms,
                                            quarantine,
                                            None,
                                        )
                                        .await?;
                                    return Err(format!(
                                        "output protection failed after effect; execution quarantined: {error}"
                                    )
                                    .into());
                                }
                            }
                        } else {
                            None
                        };
                        control
                            .settle_native_authorized(
                                &request_id,
                                authority.plan,
                                now_unix_ms,
                                output,
                                protected_output,
                            )
                            .await?;
                        Ok(live_output)
                    }
                }
            }
            Err(error) => {
                if control
                    .native_record(&request_id)
                    .await?
                    .is_some_and(|record| record.state == NativeReservationState::Reserved)
                {
                    // Only Reserved proves turn/start could not have happened.
                    let reason: String = error.to_string().chars().take(1024).collect();
                    control
                        .stop_native_before_dispatch(&request_id, reason)
                        .await?;
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

fn unix_time_ms() -> Result<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
