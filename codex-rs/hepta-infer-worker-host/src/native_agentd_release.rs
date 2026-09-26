//! Retire only the ephemeral Agentd row after the existing inference owner has
//! durably released the exact run. Failure leaves a replayable cleanup debt;
//! it never changes the settled output or authorizes another physical send.
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;

use super::AppServerModelDriver;
use super::NativeRunStatus;
use super::Result;

impl AppServerModelDriver {
    pub(super) async fn release_settled_agentd_run(&self, record: &NativeRunRecord) {
        // Cleanup must not hold a durably completed result behind the general
        // control-client budget. A timeout preserves the original replay debt.
        match tokio::time::timeout(
            std::time::Duration::from_secs(1),
            self.try_release_settled_agentd_run(record),
        )
        .await
        {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                let message: String = error.to_string().chars().take(512).collect();
                eprintln!("Agentd terminal row release remains pending: {message}");
            }
            Err(_) => {
                eprintln!("Agentd terminal row release timed out; durable result retained");
            }
        }
    }

    async fn try_release_settled_agentd_run(&self, record: &NativeRunRecord) -> Result<()> {
        if record.state != NativeReservationState::Released {
            return Ok(());
        }
        let Some(input) = &record.prepared_input else {
            return Ok(());
        };
        let Some(binding) = &input.intelligence else {
            return Ok(());
        };
        let Some(output) = &record.observation else {
            return Ok(());
        };
        if !output.terminal_observed || output.codex_terminal_correlation_digest.is_none() {
            return Ok(());
        }
        if input.agentd_socket != self.config.agentd_socket
            || record.request.principal_id != self.config.agent_id.to_string()
            || record.request.worker_generation != self.config.generation
            || record.request.model != self.config.model
        {
            return Err("settled run does not match the configured Agentd owner".into());
        }
        let phase = match output.status {
            NativeRunStatus::Completed => AgentRunPhase::Succeeded,
            NativeRunStatus::Failed => AgentRunPhase::Failed,
            NativeRunStatus::Interrupted => AgentRunPhase::Cancelled,
            NativeRunStatus::Indeterminate => return Ok(()),
        };
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let Some(current) = owner.run_status(binding.run_id.clone()).await? else {
            // An absent projection is not permission to reconstruct or execute it.
            return Ok(());
        };
        if current.run_id != binding.run_id
            || current.generation != self.config.generation
            || current.phase != phase
            || !current.terminal_observed
            || current.context_digest.as_deref() != Some(binding.context_digest.as_str())
            || current.compilation_receipt_digest.as_deref()
                != Some(binding.envelope_digest.as_str())
        {
            return Err(
                "Agentd terminal projection differs from the durably settled binding".into(),
            );
        }
        let released = owner
            .run_release_closed(binding.run_id.clone(), current.revision)
            .await?;
        if released != current {
            return Err("Agentd released receipt differs from its exact terminal revision".into());
        }
        Ok(())
    }
}
