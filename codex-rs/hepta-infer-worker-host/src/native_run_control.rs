//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use crate::native_observability::record_indeterminate;
use crate::native_observability::record_provider_receipt_resolution;
use crate::native_observability::record_reconciliation_attempt;
use crate::native_observability::record_reconciliation_failure;
use crate::native_observability::record_reconciliation_success;
use crate::native_observability::record_terminal;
use crate::provider_receipt::ProviderReceiptResolution;
use crate::provider_receipt::VerifiedProviderTerminalReceipt;

use super::AppServerModelDriver;
use super::NativeBoundaryStatus;
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

    /// Inspect one existing dispatch through exact App Server history. This API
    /// never calls `turn/start`; lack of exact evidence remains indeterminate.
    pub async fn resolve_indeterminate(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        expected_prompt: &str,
    ) -> Result<NativeRunOutput> {
        if expected_prompt.is_empty() || expected_prompt.len() > super::MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or("native request not found")?;
        if record.state == NativeReservationState::Reserved
            || record.pre_dispatch_stop.is_some()
            || record.dispatch_rejection.is_some()
        {
            return Err("native request has no reconcile-only provider dispatch".into());
        }
        if let Some(output) = record
            .observation
            .as_ref()
            .filter(|output| output.terminal_observed && output.observed_output_tokens.is_some())
        {
            observe_output_metrics(request_id, output);
            return Ok(output.clone());
        }
        record_reconciliation_attempt();
        match self.reconcile_existing(&record, expected_prompt).await {
            Ok(Some(output)) => {
                let settled = control.settle_native(request_id, output)?;
                let output = settled
                    .observation
                    .ok_or("durable reconciliation omitted its normalized observation")?;
                record_reconciliation_success();
                observe_output_metrics(request_id, &output);
                Ok(output)
            }
            Ok(None) => {
                record_reconciliation_failure();
                let output = match record.observation.clone() {
                    Some(output) => output,
                    None => indeterminate_output(&record)?,
                };
                if control
                    .native_record(request_id)
                    .is_some_and(|current| current.observation.is_none())
                {
                    control.settle_native(request_id, output.clone())?;
                }
                observe_output_metrics(request_id, &output);
                Ok(output)
            }
            Err(error) => {
                record_reconciliation_failure();
                record_indeterminate(request_id);
                Err(error)
            }
        }
    }

    /// Apply an independently verified provider terminal/usage receipt to one
    /// exact durable dispatch. Provider evidence cannot upgrade owner authority.
    pub fn resolve_with_provider_receipt(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        receipt: &VerifiedProviderTerminalReceipt,
    ) -> Result<ProviderReceiptResolution> {
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or("native request not found")?;
        record_reconciliation_attempt();
        let mut resolution = match receipt.resolve(&record) {
            Ok(resolution) => resolution,
            Err(error) => {
                record_reconciliation_failure();
                return Err(error.into());
            }
        };
        let settled = match control.settle_native(request_id, resolution.output.clone()) {
            Ok(settled) => settled,
            Err(error) => {
                record_reconciliation_failure();
                return Err(error.into());
            }
        };
        resolution.output = settled
            .observation
            .ok_or("provider receipt settlement omitted its normalized observation")?;
        record_reconciliation_success();
        record_provider_receipt_resolution();
        observe_output_metrics(request_id, &resolution.output);
        Ok(resolution)
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
                observe_output_metrics(&record.request.request_id, output);
                return Ok(output.clone());
            }
            record_reconciliation_attempt();
            match self.reconcile_existing(&record, &prompt).await {
                Ok(Some(reconciled)) => {
                    let settled = control.settle_native(&record.request.request_id, reconciled)?;
                    let output = settled.observation.ok_or_else(|| {
                        "durable reconciliation omitted its normalized observation"
                    })?;
                    record_reconciliation_success();
                    observe_output_metrics(&record.request.request_id, &output);
                    return Ok(output);
                }
                Ok(None) => {
                    record_reconciliation_failure();
                }
                Err(error) => {
                    record_reconciliation_failure();
                    record_indeterminate(&record.request.request_id);
                    return Err(error);
                }
            }
            if let Some(output) = record.observation.clone() {
                observe_output_metrics(&record.request.request_id, &output);
                return Ok(output);
            }
            let output = indeterminate_output(&record)?;
            control.settle_native(&record.request.request_id, output.clone())?;
            observe_output_metrics(&record.request.request_id, &output);
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
                let output = settled.observation.ok_or_else(|| {
                    "durable execution settlement omitted its normalized observation"
                })?;
                observe_output_metrics(&request_id, &output);
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
                } else {
                    record_indeterminate(&request_id);
                }
                Err(error)
            }
        }
    }
}

fn indeterminate_output(record: &NativeRunRecord) -> Result<NativeRunOutput> {
    let dispatch = record
        .dispatch
        .as_ref()
        .ok_or("reconciliation requires durable dispatch")?;
    Ok(NativeRunOutput {
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
            "reopened after possible dispatch; exact history found no terminal evidence; reservation held, no replay"
                .to_string(),
        ),
        codex_terminal_correlation_digest: None,
    })
}

fn observe_output_metrics(request_id: &str, output: &NativeRunOutput) {
    if output.terminal_observed {
        record_terminal(request_id, output.observed_output_tokens.is_some());
    } else {
        record_indeterminate(request_id);
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
