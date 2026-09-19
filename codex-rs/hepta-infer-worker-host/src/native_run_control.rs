//! Local durable admission around the actual App Server driver.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdRunPhase;
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
                // Historical terminal replay is already authorized by the
                // durable inference journal. It must not regain a dependency
                // on a possibly retired Agentd generation or contact provider.
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
                // The inference-control journal is the result authority. Only
                // after it has durably settled may the bounded Agentd lifecycle
                // ledger retire a closed run. If cleanup fails, replay of the
                // same durable observation retries cleanup without redispatch.
                control.settle_native(&request_id, output.clone())?;
                if output.terminal_observed {
                    self.finish_agentd_lifecycle(&request_id, &output).await?;
                }
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

    async fn finish_agentd_lifecycle(
        &self,
        request_id: &str,
        output: &NativeRunOutput,
    ) -> Result<()> {
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let Some(mut receipt) = owner.run_get(request_id.to_string()).await? else {
            // A prior replay may already have retired the closed lifecycle row.
            return Ok(());
        };

        if !matches!(
            receipt.phase,
            AgentdRunPhase::Cancelled | AgentdRunPhase::Succeeded | AgentdRunPhase::Failed
        ) {
            let phase = super::lifecycle_phase_for_output(output.status);
            if phase == AgentdRunPhase::Indeterminate {
                return Err(
                    "terminal provider observation mapped to an indeterminate Agentd phase".into(),
                );
            }
            receipt = owner
                .run_observe_terminal(request_id.to_string(), receipt.revision, phase, true)
                .await?;
        }

        if !matches!(
            receipt.phase,
            AgentdRunPhase::Cancelled | AgentdRunPhase::Succeeded | AgentdRunPhase::Failed
        ) {
            return Err("terminal inference output did not close the Agentd lifecycle".into());
        }
        owner
            .run_remove_closed(request_id.to_string(), receipt.revision)
            .await?;
        Ok(())
    }
}

pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "native_run_control_tests.rs"]
mod tests;
