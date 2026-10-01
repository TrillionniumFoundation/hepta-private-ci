//! Project an already-durable physical terminal into the current Agentd owner.
//! This path only observes history and never sends a model request.

use super::*;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentdClient;

impl AppServerModelDriver {
    pub(super) async fn reconcile_intelligence_terminal(
        &self,
        intelligence: Option<&NativeIntelligenceRunBinding>,
        output: &NativeRunOutput,
    ) -> std::result::Result<(), &'static str> {
        let Some(binding) = intelligence else {
            return Ok(());
        };
        if !output.terminal_observed
            || !matches!(output.owner_authority, NativeOwnerAuthority::ObservedReady)
            || output.codex_terminal_correlation_digest.is_none()
        {
            return Err("native terminal lacks current owner attestation");
        }
        // Control diagnostics stay separate from the exact native observation.
        self.project_intelligence_terminal(binding, output).await
    }

    async fn project_intelligence_terminal(
        &self,
        binding: &NativeIntelligenceRunBinding,
        output: &NativeRunOutput,
    ) -> std::result::Result<(), &'static str> {
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )
        .map_err(|_| "terminal reconciliation owner identity invalid")?;
        let health = owner
            .health()
            .await
            .map_err(|_| "terminal reconciliation owner unavailable")?;
        if !health.ready || health.fenced {
            return Err("terminal reconciliation owner not current");
        }
        let run = owner
            .run_status(binding.run_id.clone())
            .await
            .map_err(|_| "terminal reconciliation run status unavailable")?
            .ok_or("Agentd run is unavailable during terminal reconciliation")?;
        if run.run_id != binding.run_id
            || self.config.generation.checked_add(1) != Some(run.generation)
            || run.context_digest.as_deref() != Some(binding.context_digest.as_str())
            || run.compilation_receipt_digest.as_deref() != Some(binding.envelope_digest.as_str())
        {
            return Err("terminal reconciliation binding stale or mixed");
        }
        let revision = if run.phase == AgentRunPhase::ContextAttached {
            if run.revision != binding.expected_revision {
                return Err("terminal reconciliation attachment revision changed");
            }
            // Rehydrated ephemeral run state inherits an already-observed
            // dispatch. This transition cannot authorize a physical send.
            owner
                .run_mark_dispatched(binding.run_id.clone(), run.revision)
                .await
                .map_err(|_| "terminal reconciliation dispatch projection unavailable")?
                .revision
        } else {
            run.revision
        };
        super::super::commit_intelligence_terminal(&owner, binding, revision, output)
            .await
            .map_err(|error| {
                if error.to_string() == super::super::LOCAL_CANCELLED {
                    super::super::LOCAL_CANCELLED
                } else {
                    "terminal reconciliation observation projection unavailable"
                }
            })
    }
}
