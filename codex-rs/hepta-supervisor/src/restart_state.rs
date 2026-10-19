use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::write_restart_journal;
use crate::runtime::AgentSlot;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn persist_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let release_id = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone())
            .ok_or_else(|| {
                SupervisorError::Invalid(format!(
                    "agent {agent_id} has restart state without an active release"
                ))
            })?;
        self.persist_restart_budget_for_release(agent_id, slot, release_id)
    }

    fn persist_restart_budget_for_release(
        &self,
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
        release_id: ReleaseId,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let journal = RestartBudgetJournal::new(
            agent_id.clone(),
            release_id,
            // Main-process attempts and pending intent are owned by the
            // canonical restart-budget port, not this Matrix projection.
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: slot.matrix.restart_attempt,
                window_started_unix_millis: slot.matrix.restart_window_started_unix_millis,
            },
        )?;
        write_restart_journal(record.layout.run_root(), &journal)
    }
}
