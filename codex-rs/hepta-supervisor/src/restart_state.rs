use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::matrix::reset_matrix_restart_budget;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::restore_window;
use crate::restart_journal::unix_millis_now;
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

    /// Hydrate only the companion window; the canonical main restart port
    /// owns main-process attempts and pending intent independently.
    pub(crate) fn restore_matrix_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(journal) = read_restart_journal(record.layout.run_root())? else {
            return Ok(());
        };
        if journal.agent_id != *agent_id {
            return Err(SupervisorError::CorruptLease(format!(
                "restart budget journal belongs to {} instead of {agent_id}",
                journal.agent_id
            )));
        }
        let Some(release_id) = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone())
        else {
            reset_matrix_restart_budget(slot);
            return Ok(());
        };
        if journal.release_id != release_id {
            reset_matrix_restart_budget(slot);
            return self.persist_restart_budget_for_release(agent_id, slot, release_id);
        }

        let now_unix_millis = unix_millis_now()?;
        let (matrix_attempts, matrix_started, matrix_wall, matrix_exhausted) =
            restore_window(&journal.matrix, now, now_unix_millis);
        slot.matrix.restart_attempt = matrix_attempts;
        slot.matrix.restart_window_started_at = matrix_started;
        slot.matrix.restart_window_started_unix_millis = matrix_wall;
        slot.matrix.retry_at = None;
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = matrix_exhausted;

        let normalized_matrix = DurableRestartWindow {
            attempts: matrix_attempts,
            window_started_unix_millis: matrix_wall,
        };
        if normalized_matrix != journal.matrix {
            self.persist_restart_budget_for_release(agent_id, slot, release_id)?;
        }
        Ok(())
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
