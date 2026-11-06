use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::restore_window;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;
use crate::restart_policy::clear_restart_budget;
use crate::runtime::AgentSlot;

pub(crate) enum MatrixRestartRecovery {
    ResolvedAgentState,
    UnresolvedAgentState,
}

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

    pub(crate) fn restore_matrix_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
        recovery: MatrixRestartRecovery,
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
        let active_release = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone());

        let now_unix_millis = unix_millis_now()?;
        let (matrix_attempts, matrix_started, matrix_wall, matrix_exhausted) =
            restore_window(&journal.matrix, now, now_unix_millis);
        slot.matrix.restart_attempt = matrix_attempts;
        slot.matrix.restart_window_started_at = matrix_started;
        slot.matrix.restart_window_started_unix_millis = matrix_wall;
        slot.matrix.retry_at = None;
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = matrix_exhausted;

        if matches!(recovery, MatrixRestartRecovery::UnresolvedAgentState)
            && active_release.as_ref() != Some(&journal.release_id)
        {
            // An Agent recovery fault may leave only a stale registry release.
            // Keep the durable window and pause Matrix retries until recovery
            // resolves its association; uncertainty cannot replenish attempts.
            slot.matrix.restart_exhausted = true;
            return Ok(());
        }
        let Some(release_id) = active_release else {
            reset_slot_matrix_restart_budget(slot);
            return Ok(());
        };
        if journal.release_id != release_id {
            reset_slot_matrix_restart_budget(slot);
            return self.persist_restart_budget_for_release(agent_id, slot, release_id);
        }

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

fn reset_slot_matrix_restart_budget<P>(slot: &mut AgentSlot<P>) {
    clear_restart_budget(
        &mut slot.matrix.restart_attempt,
        &mut slot.matrix.restart_window_started_at,
    );
    slot.matrix.restart_window_started_unix_millis = None;
    slot.matrix.retry_at = None;
    slot.matrix.restart_after_exit = false;
    slot.matrix.restart_exhausted = false;
}
