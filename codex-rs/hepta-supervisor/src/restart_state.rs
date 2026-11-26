//! Restore the Matrix restart window before process adoption can charge it.
//! Main-process attempts and pending restarts belong to the canonical budget
//! port; the companion journal must never replace that independent state.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::restore_window;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;
use crate::restart_policy::restart_backoff;
use crate::runtime::AgentSlot;
use crate::runtime::deadline;

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
        let record = self.record(agent_id)?;
        let journal = RestartBudgetJournal::new(
            agent_id.clone(),
            release_id,
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: slot.matrix.restart_attempt,
                window_started_unix_millis: slot.matrix.restart_window_started_unix_millis,
            },
        )?;
        write_restart_journal(record.layout.run_root(), &journal)
    }

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
        let (attempts, started, wall, exhausted) =
            restore_window(&journal.matrix, now, unix_millis_now()?);
        let normalized = DurableRestartWindow {
            attempts,
            window_started_unix_millis: wall,
        };
        if normalized != journal.matrix {
            // Normalize expired windows or clock rollback before process effects.
            // The canonical codec retains the main restart record unchanged.
            let normalized_journal = RestartBudgetJournal::new(
                agent_id.clone(),
                journal.release_id,
                DurableRestartWindow::empty(),
                normalized,
            )?;
            write_restart_journal(record.layout.run_root(), &normalized_journal)?;
        }
        // A committed release may lag an in-flight target lease. Carrying its
        // charged window is conservative; a release-name mismatch cannot erase it.
        slot.matrix.restart_attempt = attempts;
        slot.matrix.restart_window_started_at = started;
        slot.matrix.restart_window_started_unix_millis = wall;
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = exhausted;
        slot.matrix.retry_at = if attempts > 0 && !exhausted {
            // The old journal has no next-eligible timestamp. Reapply the full
            // backoff so restarting supervisord cannot accelerate a retry.
            Some(deadline(now, restart_backoff(attempts))?)
        } else {
            None
        };
        slot.matrix.configured = slot
            .active_release
            .as_ref()
            .is_some_and(|release| release.matrixd_command().is_some());
        if exhausted {
            slot.matrix.degraded = true;
            slot.matrix.last_error = Some("Matrix restart budget exhausted during recovery".into());
        }
        Ok(())
    }
}
