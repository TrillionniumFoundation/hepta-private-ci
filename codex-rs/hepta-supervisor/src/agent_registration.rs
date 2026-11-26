use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;

use crate::MAX_SUPERVISORD_ROSTER;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::runtime::AgentSlot;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn register_agent(
        &mut self,
        manifest: AgentManifest,
    ) -> Result<(), SupervisorError> {
        let snapshot = self.registry.load()?;
        if let Some(record) = snapshot.agent(&manifest.agent_id) {
            if record.manifest != manifest {
                return Err(SupervisorError::Invalid(
                    "registered manifest identity differs".to_string(),
                ));
            }
            if !self.slots.contains_key(&manifest.agent_id) {
                return Err(SupervisorError::Invalid(
                    "registered Agent requires owner recovery".to_string(),
                ));
            }
            return Ok(());
        }
        if snapshot.agents.len() >= usize::from(MAX_SUPERVISORD_ROSTER) {
            return Err(SupervisorError::Invalid(
                "registered fleet capacity exhausted".to_string(),
            ));
        }
        let record = self.registry.register(manifest)?;
        self.driver
            .prepare_agent_registration(&record)
            .map_err(|error| crate::runtime::driver_error(&record.manifest.agent_id, error))?;
        self.slots
            .insert(record.manifest.agent_id, AgentSlot::new(&self.config));
        Ok(())
    }

    pub(crate) fn retire_agent(&mut self, agent_id: &AgentId) -> Result<PathBuf, SupervisorError> {
        let record = self.registry.load_agent(agent_id)?;
        self.ensure_configuration_ready(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if slot.runtime.is_some()
            || slot.matrix.runtime.is_some()
            || slot.restart_pending
            || slot.release_change.is_some()
            || slot.signed_recovery_required()
            || slot
                .release_transaction
                .as_ref()
                .is_some_and(|transaction| !transaction.phase.terminal())
            || !matches!(
                record.lifecycle.lifecycle,
                AgentLifecycle::Stopped | AgentLifecycle::Failed
            )
            || crate::lease::read_lease(record.layout.owner_run_root())?.is_some()
            || crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
            || crate::control_intent::has_unresolved(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            return Err(SupervisorError::Invalid(
                "Agent retirement requires resolved process and control ownership".to_string(),
            ));
        }
        self.driver
            .validate_agent_retirement(agent_id)
            .map_err(|error| crate::runtime::driver_error(agent_id, error))?;
        let result = self
            .registry
            .retire_agent(agent_id, record.lifecycle.generation);
        // A rename can succeed before directory fsync fails. Remove the retired
        // slot only after verifying the physical archive; the error still reports
        // unknown durability and can be resolved by a retirement status read.
        if result.is_ok()
            || self
                .registry
                .retired_agent_path(agent_id)
                .ok()
                .flatten()
                .is_some()
        {
            self.slots.remove(agent_id);
        }
        Ok(result?)
    }

    pub(crate) fn ensure_configuration_ready(
        &self,
        agent_id: &AgentId,
    ) -> Result<(), SupervisorError> {
        let record = self.registry.load_agent(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let signed = crate::signed_intent::read_intent(record.layout.owner_run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let transaction =
            crate::release_transaction::read_release_transaction(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let restart =
            crate::restart_journal::read_main_restart_budget(record.layout.owner_run_root())?;
        // Reading also verifies the companion budget's integrity. It records
        // attempts, not a pending operation; live retry state remains owner-held.
        crate::restart_journal::read_restart_journal(record.layout.owner_run_root())?;
        if slot.pending_control.is_some()
            || slot.deferred_agent_action.is_some()
            || slot.restart_pending
            || slot.restart_not_before.is_some()
            || slot.matrix.retry_at.is_some()
            || slot.matrix.restart_after_exit
            || slot.release_change.is_some()
            || signed.is_some_and(|intent| !intent.status.terminal())
            || transaction.is_some_and(|transaction| !transaction.phase.terminal())
            || restart.is_some_and(|budget| budget.pending)
            || crate::control_intent::has_unresolved(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            return Err(SupervisorError::Invalid(
                "configuration requires resolved control and restart ownership".to_string(),
            ));
        }
        let ordinary = crate::read_mutation_status(record.layout.owner_run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let emergency =
            crate::mutation_journal_slots::read_emergency(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .map(|owned| owned.status);
        if ordinary
            .into_iter()
            .chain(emergency)
            .any(|status| !status.phase.terminal())
        {
            return Err(SupervisorError::Invalid(
                "configuration cannot replace unresolved mutation evidence".to_string(),
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "agent_registration_tests.rs"]
mod tests;
