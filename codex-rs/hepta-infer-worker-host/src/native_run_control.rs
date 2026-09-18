//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeFinalUseAuthority;
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
use super::policy::FinalUseGrantResolver;
use super::policy::NativeExecutionPolicy;
use super::policy::claimed_authority;

/// Exact admission evidence for one native provider request. Local slot
/// capacity remains an independent ceiling; the quota binding adds
/// request/token/concurrency accounting and is cryptographically bound at the
/// physical turn boundary.
#[derive(Clone, Debug)]
pub struct NativeAdmission {
    pub request_id: String,
    pub maximum_in_flight: usize,
    pub maximum_output_tokens: u64,
    pub maximum_budget_units: u64,
    pub policy: NativeExecutionPolicy,
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
        grant_resolver: &FinalUseGrantResolver<'_>,
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
        let admission_binding = admission.policy.admission_binding(
            unix_seconds()?,
            &self.config.agent_id.to_string(),
            self.config.generation,
            &self.config.model,
            admission.maximum_output_tokens,
            admission.maximum_budget_units,
        )?;
        let request = NativeRequest {
            request_id: admission.request_id,
            principal_id: self.config.agent_id.to_string(),
            worker_generation: self.config.generation,
            model: self.config.model.clone(),
            payload_digest: digest(&serde_json::to_vec(&(
                "hepta.native-request.v2",
                &prompt,
                &context_query,
                &self.config.agentd_socket,
                self.config.timeout.as_millis(),
                admission.maximum_output_tokens,
                admission.maximum_budget_units,
                &admission_binding,
            ))?),
            maximum_output_tokens: admission.maximum_output_tokens,
            maximum_budget_units: admission.maximum_budget_units,
            admission: Some(admission_binding),
        };
        let record = control.reserve_native(request, admission.maximum_in_flight)?;
        if let Some(reason) = &record.pre_dispatch_stop {
            return Err(format!("request stopped before dispatch: {reason}").into());
        }
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record
                .observation
                .as_ref()
                .filter(|output| output.terminal_observed)
                .cloned()
            {
                return Ok(output);
            }
            if let Ok(Some(reconciled)) = self.reconcile_existing(&record).await {
                control.settle_native(&record.request.request_id, reconciled.clone())?;
                return Ok(reconciled);
            }
            if let Some(output) = record.observation {
                return Ok(output);
            }
            let dispatch = record.dispatch.ok_or("missing durable dispatch binding")?;
            let final_use_authority = dispatch
                .final_use
                .as_ref()
                .map(claimed_authority)
                .unwrap_or(NativeFinalUseAuthority::Unverified);
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
                final_use_authority,
                stop_reason: Some(
                    "reopened after possible dispatch; read-only reconciliation found no trusted terminal; reservation held, no replay".to_string(),
                ),
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
                admission.maximum_output_tokens,
                admission.maximum_budget_units,
                &admission.policy,
                cancellation,
                grant_resolver,
            )
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

fn unix_seconds() -> Result<u64> {
    Ok(std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs())
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
