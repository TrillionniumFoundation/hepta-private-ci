//! Local durable admission around the actual App Server driver.

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
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
    pub(super) run_id: String,
    pub(super) expected_revision: u64,
    pub(super) absolute_deadline_ms: u64,
    pub(super) context_digest: String,
    pub(super) envelope_digest: String,
}

impl NativeIntelligenceRunBinding {
    /// Load the immutable product binding through the exact Agentd generation.
    ///
    /// runtime.codex-agentd-admitted-loader-v1: this is the only public
    /// constructor. Callers select a durable run ID but cannot supply its
    /// revision, context or compilation identity.
    pub async fn load_from_agentd(
        socket_path: std::path::PathBuf,
        agent_id: codex_hepta_contracts::AgentId,
        generation: u64,
        run_id: String,
    ) -> Result<Self> {
        let receipt = AgentdClient::new(socket_path, agent_id, generation)?
            .run_status(run_id.clone())
            .await?
            .ok_or("Agentd has no durable admitted work for the requested run")?;
        Self::from_agentd_receipt(&run_id, generation, receipt)
    }

    /// Validate a receipt already obtained through the exact Agentd client.
    ///
    /// runtime.codex-agentd-admitted-binding-v1: callers may select a run ID,
    /// but cannot mint its revision or content identities. `Dispatched` is
    /// accepted only to reopen and reconcile the same operation; its original
    /// pre-dispatch revision is derived by removing the single dispatch CAS.
    fn from_agentd_receipt(
        expected_run_id: &str,
        expected_generation: u64,
        receipt: AgentRunReceipt,
    ) -> Result<Self> {
        if expected_run_id.is_empty()
            || expected_run_id.len() > 256
            || expected_run_id.as_bytes().contains(&0)
            || receipt.run_id != expected_run_id
        {
            return Err("Agentd admitted run identity mismatch".into());
        }
        if expected_generation == 0 || receipt.generation != expected_generation {
            return Err("Agentd admitted run generation mismatch".into());
        }
        if receipt.terminal_observed {
            return Err("Agentd admitted run is already terminal".into());
        }
        let expected_revision = match receipt.phase {
            AgentRunPhase::ContextAttached => {
                if receipt.dispatch_binding_digest.is_some()
                    || receipt.pre_effect_abort_commitment_digest.is_some()
                    || receipt.pre_effect_abort_proof_digest.is_some()
                {
                    return Err("Agentd context-attached run contains dispatch state".into());
                }
                receipt.revision
            }
            AgentRunPhase::Dispatched => {
                if receipt.dispatch_binding_digest.is_none()
                    || receipt.pre_effect_abort_commitment_digest.is_none()
                    || receipt.pre_effect_abort_proof_digest.is_some()
                {
                    return Err("Agentd dispatched run lacks its exact recovery binding".into());
                }
                receipt
                    .revision
                    .checked_sub(1)
                    .ok_or("Agentd dispatch revision underflow")?
            }
            _ => {
                return Err(
                    "Agentd run is not eligible for runtime.codex execution or reconciliation"
                        .into(),
                );
            }
        };
        if expected_revision == 0 {
            return Err("Agentd admitted run revision is zero".into());
        }
        if receipt.deadline_ms == 0 {
            return Err("Agentd admitted run deadline is zero".into());
        }
        let context_digest = receipt
            .context_digest
            .ok_or("Agentd admitted run omitted its context digest")?;
        let envelope_digest = receipt
            .compilation_receipt_digest
            .ok_or("Agentd admitted run omitted its compilation receipt digest")?;
        if !runtime_codex_sha256_hex(&context_digest) || !runtime_codex_sha256_hex(&envelope_digest)
        {
            return Err("Agentd admitted run contains a non-canonical digest".into());
        }
        Ok(Self {
            run_id: receipt.run_id,
            expected_revision,
            absolute_deadline_ms: receipt.deadline_ms,
            context_digest,
            envelope_digest,
        })
    }
}

fn runtime_codex_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
}

#[derive(Clone, Copy)]
pub(super) enum NativeDeadlinePolicy {
    Profile,
    Absolute(u64),
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
            NativeDeadlinePolicy::Profile,
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
            NativeDeadlinePolicy::Profile,
            cancellation,
        )
        .await
    }

    /// Execute an authority-neutral model request within its original absolute
    /// deadline. Queueing or reopening cannot create a fresh execution budget.
    pub async fn run_with_deadline(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        deadline_ms: u64,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_bound(
            control,
            admission,
            prompt,
            /*context_query*/ None,
            /*intelligence*/ None,
            NativeDeadlinePolicy::Absolute(deadline_ms),
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
        deadline: NativeDeadlinePolicy,
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
                deadline,
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
                .cloned()
            {
                self.publish_pending_intelligence_terminal(control, &record.request.request_id)
                    .await?;
                return Ok(output);
            }
            if let Some(reconciled) = self.reconcile_existing(&record, &prompt).await? {
                let request_id = record.request.request_id.clone();
                let settled = control.settle_native(&request_id, reconciled)?;
                let output = settled
                    .observation
                    .ok_or("durable reconciliation omitted its normalized observation")?;
                self.publish_pending_intelligence_terminal(control, &request_id)
                    .await?;
                return Ok(output);
            }
            if let Some(output) = record.observation {
                self.publish_pending_intelligence_terminal(control, &record.request.request_id)
                    .await?;
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
            self.publish_pending_intelligence_terminal(control, &record.request.request_id)
                .await?;
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
                deadline,
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
                self.publish_pending_intelligence_terminal(control, &request_id)
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
    deadline: NativeDeadlinePolicy,
) -> Result<String> {
    let bytes = match (intelligence, deadline) {
        (None, NativeDeadlinePolicy::Absolute(deadline_ms)) => serde_json::to_vec(&(
            "hepta.native-assessment-request.v1",
            prompt,
            context_query,
            socket,
            timeout_ms,
            deadline_ms,
        ))?,
        (None, NativeDeadlinePolicy::Profile) => serde_json::to_vec(&(
            "hepta.native-request.v1",
            prompt,
            context_query,
            socket,
            timeout_ms,
        ))?,
        (Some(binding), NativeDeadlinePolicy::Profile) => serde_json::to_vec(&(
            "hepta.native-intelligence-request.v2",
            prompt,
            context_query,
            socket,
            timeout_ms,
            &binding.run_id,
            binding.expected_revision,
            &binding.context_digest,
            &binding.envelope_digest,
            binding.absolute_deadline_ms,
        ))?,
        (Some(_), NativeDeadlinePolicy::Absolute(_)) => {
            return Err("intelligence deadline is owned by its admitted binding".into());
        }
    };
    Ok(digest(&bytes))
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
