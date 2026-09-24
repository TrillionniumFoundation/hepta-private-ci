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

    /// Restore only the companion projection. Main-process restart intent and
    /// attempt accounting remain exclusively owned by `restart_budget`.
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
            // A revoked or absent release never authorizes a fresh companion.
            // Keep its durable history rather than silently erasing the fence.
            return Ok(());
        };
        let window = if journal.release_id == release_id {
            &journal.matrix
        } else {
            &DurableRestartWindow::empty()
        };
        let (attempts, started, wall, exhausted) = restore_window(window, now, unix_millis_now()?);
        slot.matrix.restart_attempt = attempts;
        slot.matrix.restart_window_started_at = started;
        slot.matrix.restart_window_started_unix_millis = wall;
        slot.matrix.restart_after_exit = false;
        slot.matrix.restart_exhausted = exhausted;
        // The old journal has no exact retry deadline. Conservatively restart
        // its bounded delay rather than allowing recovery to bypass backoff.
        slot.matrix.retry_at = if attempts > 0 && !exhausted {
            let delay = crate::restart_policy::RESTART_BACKOFF_MIN
                .checked_mul(1_u32 << attempts.saturating_sub(1).min(7))
                .unwrap_or(crate::restart_policy::RESTART_BACKOFF_MAX)
                .min(crate::restart_policy::RESTART_BACKOFF_MAX);
            Some(crate::runtime::deadline(now, delay)?)
        } else {
            None
        };
        if exhausted {
            slot.matrix.degraded = true;
            slot.matrix.last_error = Some("restored Matrix restart budget exhausted".to_string());
        }
        let normalized = DurableRestartWindow {
            attempts,
            window_started_unix_millis: wall,
        };
        if journal.release_id != release_id || normalized != journal.matrix {
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
