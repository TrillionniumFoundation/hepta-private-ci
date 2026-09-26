//! Bounded backlog observations for host backpressure and SLO receipts.

use serde::Serialize;

use crate::AutomationError;
use crate::AutomationStore;
use crate::AutomationTaskState;

const BACKLOG_SCAN_LIMIT: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AutomationBacklogSnapshot {
    pub observed_at_ms: u64,
    pub scanned_tasks: usize,
    pub due_tasks: usize,
    pub oldest_due_age_ms: Option<u64>,
    pub pending_occurrences: usize,
    pub uncertain_dispatches: usize,
    pub oldest_uncertain_age_ms: Option<u64>,
    pub scan_truncated: bool,
    pub fairness_order: &'static str,
}

impl AutomationStore {
    /// Observe a bounded backlog without claiming work or contacting a provider.
    /// Equal-time fairness remains the durable owner ordering
    /// `(scheduled_for_ms, task_id, occurrence)`.
    pub async fn backlog_snapshot(
        &self,
        observed_at_ms: u64,
    ) -> Result<AutomationBacklogSnapshot, AutomationError> {
        let tasks = self.list_tasks(BACKLOG_SCAN_LIMIT).await?;
        let pending = self.pending_occurrence_work(BACKLOG_SCAN_LIMIT).await?;
        let uncertain = self.uncertain_dispatches(BACKLOG_SCAN_LIMIT).await?;

        let due_instants = tasks.iter().filter_map(|task| {
            (task.state == AutomationTaskState::Enabled)
                .then_some(task.next_run_at_ms)
                .flatten()
                .filter(|instant| *instant <= observed_at_ms)
        });
        let due_values = due_instants.collect::<Vec<_>>();
        let oldest_due_age_ms = due_values
            .iter()
            .min()
            .map(|instant| observed_at_ms.saturating_sub(*instant));
        let oldest_uncertain_age_ms = uncertain
            .iter()
            .map(|item| item.observed_at_ms)
            .min()
            .map(|instant| observed_at_ms.saturating_sub(instant));

        Ok(AutomationBacklogSnapshot {
            observed_at_ms,
            scanned_tasks: tasks.len(),
            due_tasks: due_values.len(),
            oldest_due_age_ms,
            pending_occurrences: pending.len(),
            uncertain_dispatches: uncertain.len(),
            oldest_uncertain_age_ms,
            scan_truncated: tasks.len() == BACKLOG_SCAN_LIMIT
                || pending.len() == BACKLOG_SCAN_LIMIT
                || uncertain.len() == BACKLOG_SCAN_LIMIT,
            fairness_order: "scheduled_for_ms,task_id,occurrence",
        })
    }
}
