//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeIntelligenceInputBindingV2;
use codex_hepta_infer_core::durable_control::native::NativePreparedInputV2;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunSnapshotV2;
use sha2::Digest;
use sha2::Sha256;
use tokio_util::sync::CancellationToken;

use super::AppServerModelDriver;
use super::NativeContextDelivery;
use super::NativeContextRequest;
use super::NativeOwnerAuthority;
use super::NativeRunOutput;
use super::NativeRunStatus;
use super::Result;

#[path = "native_intelligence_recovery.rs"]
mod intelligence_recovery;

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
    /// Original Agentd run identity, including its admission-time lifecycle
    /// generation. This is distinct from the worker's Agentd spawn generation.
    pub snapshot: codex_hepta_agentd::AgentRunSnapshot,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

impl NativeIntelligenceRunBinding {
    fn prepared_input(&self) -> NativeIntelligenceInputBindingV2 {
        NativeIntelligenceInputBindingV2 {
            snapshot: NativeRunSnapshotV2 {
                run_id: self.snapshot.run_id.clone(),
                request_digest: self.snapshot.request_digest.clone(),
                objective_digest: self.snapshot.objective_digest.clone(),
                body_digest: self.snapshot.body_digest.clone(),
                artifact_set_digest: self.snapshot.artifact_set_digest.clone(),
                authority_epoch: self.snapshot.authority_epoch,
                generation: self.snapshot.generation,
                fence_digest: self.snapshot.fence_digest.clone(),
                deadline_ms: self.snapshot.deadline_ms,
            },
            expected_revision: self.expected_revision,
            context_digest: self.context_digest.clone(),
            envelope_digest: self.envelope_digest.clone(),
        }
    }

    fn from_prepared_input(input: &NativeIntelligenceInputBindingV2) -> Self {
        Self {
            snapshot: codex_hepta_agentd::AgentRunSnapshot {
                run_id: input.snapshot.run_id.clone(),
                request_digest: input.snapshot.request_digest.clone(),
                objective_digest: input.snapshot.objective_digest.clone(),
                body_digest: input.snapshot.body_digest.clone(),
                artifact_set_digest: input.snapshot.artifact_set_digest.clone(),
                authority_epoch: input.snapshot.authority_epoch,
                generation: input.snapshot.generation,
                fence_digest: input.snapshot.fence_digest.clone(),
                deadline_ms: input.snapshot.deadline_ms,
            },
            expected_revision: input.expected_revision,
            context_digest: input.context_digest.clone(),
            envelope_digest: input.envelope_digest.clone(),
        }
    }

    pub(super) fn expected_run_binding(
        &self,
        expected_revision: u64,
    ) -> codex_hepta_agentd::AgentRunBinding {
        codex_hepta_agentd::AgentRunBinding {
            snapshot: self.snapshot.clone(),
            expected_revision,
            context_digest: self.context_digest.clone(),
            compilation_receipt_digest: self.envelope_digest.clone(),
        }
    }

    pub(super) fn validate_current(
        &self,
        current: &codex_hepta_agentd::AgentRunReconciliationState,
    ) -> Result<()> {
        if current.snapshot != self.snapshot {
            return Err(
                "Agentd original run snapshot differs from the durable native binding".into(),
            );
        }
        self.validate_receipt(&current.receipt)
    }

    pub(super) fn validate_receipt(
        &self,
        receipt: &codex_hepta_agentd::AgentRunReceipt,
    ) -> Result<()> {
        if receipt.revision < self.expected_revision
            || receipt.run_id != self.snapshot.run_id
            || receipt.generation != self.snapshot.generation
            || receipt.authority_epoch != self.snapshot.authority_epoch
            || receipt.fence_digest != self.snapshot.fence_digest
            || receipt.deadline_ms != self.snapshot.deadline_ms
            || receipt.context_digest.as_deref() != Some(self.context_digest.as_str())
            || receipt.compilation_receipt_digest.as_deref() != Some(self.envelope_digest.as_str())
        {
            return Err("Agentd receipt differs from the durable intelligence binding".into());
        }
        Ok(())
    }
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
            NativeContextRequest {
                query: context_query,
                delivery: NativeContextDelivery::Attach,
            },
            /*intelligence*/ None,
            cancellation,
        )
        .await
    }

    /// Retrieve and finally revalidate the same owner context, choosing whether
    /// its explicit attachment reaches the model. Withhold is not memory-off:
    /// the host must independently isolate other memory/history/tool paths.
    /// The intervention is part of durable admission, so a request ID cannot
    /// switch delivery policy on retry. Existing Attach request identities stay
    /// compatible with `run` and retained journals.
    pub async fn run_with_context_delivery(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: String,
        delivery: NativeContextDelivery,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            NativeContextRequest {
                query: Some(context_query),
                delivery,
            },
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
            NativeContextRequest {
                query: context_query,
                delivery: NativeContextDelivery::Attach,
            },
            Some(&intelligence),
            cancellation,
        )
        .await
    }

    /// Reconcile a possibly dispatched request using only its retained V3
    /// input. This never accepts a replacement prompt or admission snapshot and
    /// cannot enter run_once: the record must already have crossed Reserved.
    pub async fn resume(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        let record = control
            .native_record(&admission.request_id)
            .cloned()
            .ok_or("resume requires an existing durable native request")?;
        if record.state == NativeReservationState::Reserved
            || record.pre_dispatch_stop.is_some()
            || record.dispatch_rejection.is_some()
            || record.dispatch.is_none()
        {
            return Err("resume requires a possibly dispatched native request".into());
        }
        let input = record.prepared_input_v2.ok_or(
            "resume requires the original retained V3 input; legacy input is not inferred",
        )?;
        if input.payload_digest()? != record.request.payload_digest
            || record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
            || input.agentd_socket != self.config.agentd_socket
            || u128::from(input.timeout_ms) != self.config.timeout.as_millis()
        {
            return Err("resume configuration differs from the durable native request".into());
        }
        let intelligence = input
            .intelligence
            .as_ref()
            .map(NativeIntelligenceRunBinding::from_prepared_input);
        // The exclusive mutable journal owner remains borrowed throughout:
        // no concurrent caller can replace this non-Reserved record.
        self.run_bound(
            control,
            admission,
            input.prompt,
            NativeContextRequest {
                query: input.context_query,
                delivery: NativeContextDelivery::Attach,
            },
            intelligence.as_ref(),
            cancellation,
        )
        .await
    }

    async fn run_bound(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_request: NativeContextRequest,
        intelligence: Option<&NativeIntelligenceRunBinding>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > super::MAX_PROMPT_BYTES {
            return Err("prompt must contain 1..32768 bytes".into());
        }
        if context_request
            .query
            .as_ref()
            .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err("context query must contain 1..2048 bytes".into());
        }
        if context_request.delivery == NativeContextDelivery::Withhold
            && context_request.query.is_none()
        {
            return Err("withheld delivery requires an explicit retrieval query".into());
        }
        let original_digest = native_source_payload_digest(
            &prompt,
            &context_request.query,
            &self.config.agentd_socket,
            self.config.timeout.as_millis(),
            intelligence,
        )?;
        let payload_digest = match context_request.delivery {
            NativeContextDelivery::Attach => original_digest,
            NativeContextDelivery::Withhold => digest(&serde_json::to_vec(&(
                "hepta.native-context-intervention.v1",
                "delivery_off",
                original_digest,
            ))?),
        };
        let request = NativeRequest {
            request_id: admission.request_id,
            principal_id: self.config.agent_id.to_string(),
            worker_generation: self.config.generation,
            model: self.config.model.clone(),
            payload_digest,
        };
        let record = if context_request.delivery == NativeContextDelivery::Attach {
            let prepared = NativePreparedInputV2 {
                schema_version: 2,
                prompt: prompt.clone(),
                context_query: context_request.query.clone(),
                agentd_socket: self.config.agentd_socket.clone(),
                timeout_ms: self.config.timeout.as_millis().try_into()?,
                intelligence: intelligence.map(NativeIntelligenceRunBinding::prepared_input),
            };
            control.reserve_native_prepared_v2(request, admission.maximum_in_flight, prepared)?
        } else {
            // V2 retained input does not encode delivery policy. Keep the existing
            // Withhold identity without reinterpreting it as Attach during resume.
            // Its explicit run_with_context_delivery retry remains bound to the
            // original digest; resume refuses records without retained V3 input.
            control.reserve_native(request, admission.maximum_in_flight)?
        };
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
                self.reconcile_intelligence_terminal(intelligence, output)
                    .await?;
                return Ok(output.clone());
            }
            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let settled = control.settle_native(&record.request.request_id, reconciled)?;
                let output = settled
                    .observation
                    .ok_or("durable reconciliation omitted its normalized observation")?;
                self.reconcile_intelligence_terminal(intelligence, &output)
                    .await?;
                return Ok(output);
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
                context_request,
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
                let output = settled
                    .observation
                    .ok_or("durable execution settlement omitted its normalized observation")?;
                self.reconcile_intelligence_terminal(intelligence, &output)
                    .await?;
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
            "hepta.native-intelligence-request.v3",
            prompt,
            context_query,
            socket,
            timeout_ms,
            &binding.snapshot,
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
