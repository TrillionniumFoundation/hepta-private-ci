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
use crate::runtime::AgentSlot;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn persist_matrix_restart_budget(
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
                    "agent {agent_id} has Matrix restart state without an active release"
                ))
            })?;
        self.persist_matrix_budget_for_release(agent_id, slot, release_id)
    }

    /// Restore the companion budget before process adoption can schedule a retry.
    /// Main-process claims have their own projection in the same durable journal;
    /// loading this projection must never overwrite those claims or their mirror.
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
            // A revoked/unselected release cannot spawn a companion. Retain its
            // durable history instead of erasing it because resolution failed.
            return Ok(());
        };
        if journal.release_id != release_id {
            // This is a fresh recovery slot for a different selected release.
            // Reset only the companion projection; preserve canonical main state.
            return self.persist_matrix_budget_for_release(agent_id, slot, release_id);
        }
        let (attempts, started, wall, exhausted) =
            restore_window(&journal.matrix, now, unix_millis_now()?);
        slot.matrix.restart_attempt = attempts;
        slot.matrix.restart_window_started_at = started;
        slot.matrix.restart_window_started_unix_millis = wall;
        // The old journal has no persisted retry deadline. Conservatively wait
        // one full backoff rather than allowing recovery to accelerate a retry.
        slot.matrix.retry_at = if attempts > 0 && !exhausted {
            Some(crate::runtime::deadline(
                now,
                crate::restart_policy::restart_delay(attempts),
            )?)
        } else {
            None
        };
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = exhausted;
        if exhausted {
            slot.matrix.degraded = true;
            slot.matrix.last_error =
                Some("Matrix restart budget exhausted during recovery".to_string());
        }
        let normalized = DurableRestartWindow {
            attempts,
            window_started_unix_millis: wall,
        };
        if normalized != journal.matrix {
            self.persist_matrix_budget_for_release(agent_id, slot, release_id)?;
        }
        Ok(())
    }

    fn persist_matrix_budget_for_release(
        &self,
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
        release_id: ReleaseId,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let journal = RestartBudgetJournal::new(
            agent_id.clone(),
            release_id,
            // Main attempts/pending intent belong exclusively to restart_budget.
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: slot.matrix.restart_attempt,
                window_started_unix_millis: slot.matrix.restart_window_started_unix_millis,
            },
        )?;
        write_restart_journal(record.layout.run_root(), &journal)
    }
}
