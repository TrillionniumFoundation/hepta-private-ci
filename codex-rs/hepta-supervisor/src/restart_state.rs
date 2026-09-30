//! Restore the companion budget before process adoption can charge it again.
//! The canonical main-process budget is independent; its projection must never
//! be copied from the legacy companion journal into the live Agent slot.

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
use crate::restart_policy::RESTART_BACKOFF_MAX;
use crate::restart_policy::RESTART_BACKOFF_MIN;
use crate::runtime::AgentSlot;
use crate::runtime::MatrixCompanionSlot;

/// Validated, normalized durable state staged before any adoption side effect.
/// Applying this snapshot uses the caller's monotonic clock and cannot fail.
pub(crate) struct MatrixRestartRecovery {
    window: DurableRestartWindow,
    observed_unix_millis: u64,
}

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn prepare_matrix_restart_recovery(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let Some(journal) = read_restart_journal(record.layout.owner_run_root())? else {
            return Ok(());
        };
        if journal.agent_id != *agent_id {
            return Err(SupervisorError::CorruptLease(format!(
                "restart budget journal belongs to {} instead of {agent_id}",
                journal.agent_id
            )));
        }
        let observed_unix_millis = unix_millis_now()?;
        let (attempts, _, wall, _) =
            restore_window(&journal.matrix, Instant::now(), observed_unix_millis);
        let window = DurableRestartWindow {
            attempts,
            window_started_unix_millis: wall,
        };
        if window != journal.matrix {
            // Normalize a clock rollback durably before adopting a process.
            // A second daemon restart must not reopen the old, smaller budget.
            let normalized = RestartBudgetJournal::new(
                agent_id.clone(),
                journal.release_id,
                DurableRestartWindow::empty(),
                window.clone(),
            )?;
            write_restart_journal(record.layout.owner_run_root(), &normalized)?;
        }
        // Do not clear charges solely because the committed release differs.
        // Exact lease adoption may still recover an in-flight target release.
        // Carrying the remaining window is conservative; erasing it is not.
        slot.matrix.recovery_budget = Some(MatrixRestartRecovery {
            window,
            observed_unix_millis,
        });
        Ok(())
    }

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
        write_restart_journal(record.layout.owner_run_root(), &journal)
    }
}

impl<P> MatrixCompanionSlot<P> {
    pub(crate) fn apply_restart_recovery(&mut self, now: Instant) {
        let Some(recovery) = self.recovery_budget.take() else {
            return;
        };
        let (attempts, started, wall, exhausted) =
            restore_window(&recovery.window, now, recovery.observed_unix_millis);
        self.restart_attempt = attempts;
        self.restart_window_started_at = started;
        self.restart_window_started_unix_millis = wall;
        self.restart_after_exit = false;
        self.restart_exhausted = exhausted;
        // This journal has no durable next-eligible timestamp. Reapply the full
        // backoff instead of allowing a daemon restart to accelerate a retry.
        self.retry_at = None;
        if attempts > 0 && !exhausted {
            let shift = attempts.saturating_sub(1).min(7);
            let delay = RESTART_BACKOFF_MIN
                .checked_mul(1_u32 << shift)
                .unwrap_or(RESTART_BACKOFF_MAX)
                .min(RESTART_BACKOFF_MAX);
            self.retry_at = now.checked_add(delay);
            self.restart_exhausted = self.retry_at.is_none();
        }
        if self.restart_exhausted {
            self.degraded = true;
            self.last_error = Some("Matrix restart budget exhausted during recovery".to_string());
        }
    }
}

#[cfg(test)]
#[path = "restart_state_tests.rs"]
mod tests;
