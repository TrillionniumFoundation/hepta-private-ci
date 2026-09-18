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

    pub(crate) fn reset_restart_budget_for_release(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        release_id: ReleaseId,
    ) -> Result<(), SupervisorError> {
        reset_slot_restart_budget(slot);
        self.persist_restart_budget_for_release(agent_id, slot, release_id)
    }

    pub(crate) fn reset_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let release_id = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone())
            .ok_or_else(|| {
                SupervisorError::Invalid(format!(
                    "agent {agent_id} has no active release for restart reset"
                ))
            })?;
        self.reset_restart_budget_for_release(agent_id, slot, release_id)
    }

    pub(crate) fn restore_restart_budget(
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
            reset_slot_restart_budget(slot);
            return Ok(());
        };
        if journal.release_id != release_id {
            return self.reset_restart_budget_for_release(agent_id, slot, release_id);
        }

        let now_unix_millis = unix_millis_now()?;
        let (main_attempts, main_started, main_wall, main_exhausted) =
            restore_window(&journal.main, now, now_unix_millis);
        let (matrix_attempts, matrix_started, matrix_wall, matrix_exhausted) =
            restore_window(&journal.matrix, now, now_unix_millis);
        slot.restart_attempt = main_attempts;
        slot.restart_window_started_at = main_started;
        slot.restart_window_started_unix_millis = main_wall;
        slot.restart_retry_at = None;
        slot.restart_automatic = false;
        slot.restart_after_exit = false;
        slot.restart_exhausted = main_exhausted;
        slot.matrix.restart_attempt = matrix_attempts;
        slot.matrix.restart_window_started_at = matrix_started;
        slot.matrix.restart_window_started_unix_millis = matrix_wall;
        slot.matrix.retry_at = None;
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = matrix_exhausted;

        let normalized_main = DurableRestartWindow {
            attempts: main_attempts,
            window_started_unix_millis: main_wall,
        };
        let normalized_matrix = DurableRestartWindow {
            attempts: matrix_attempts,
            window_started_unix_millis: matrix_wall,
        };
        if normalized_main != journal.main || normalized_matrix != journal.matrix {
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
            DurableRestartWindow {
                attempts: slot.restart_attempt,
                window_started_unix_millis: slot.restart_window_started_unix_millis,
            },
            DurableRestartWindow {
                attempts: slot.matrix.restart_attempt,
                window_started_unix_millis: slot.matrix.restart_window_started_unix_millis,
            },
        )?;
        write_restart_journal(record.layout.run_root(), &journal)
    }
}

fn reset_slot_restart_budget<P>(slot: &mut AgentSlot<P>) {
    slot.restart_pending = false;
    clear_restart_budget(
        &mut slot.restart_attempt,
        &mut slot.restart_window_started_at,
    );
    slot.restart_window_started_unix_millis = None;
    slot.restart_retry_at = None;
    slot.restart_automatic = false;
    slot.restart_after_exit = false;
    slot.restart_exhausted = false;
    clear_restart_budget(
        &mut slot.matrix.restart_attempt,
        &mut slot.matrix.restart_window_started_at,
    );
    slot.matrix.restart_window_started_unix_millis = None;
    slot.matrix.retry_at = None;
    slot.matrix.restart_after_exit = false;
    slot.matrix.restart_exhausted = false;
}
