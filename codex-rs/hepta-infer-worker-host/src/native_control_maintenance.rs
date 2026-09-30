//! Serial owner maintenance never turns an unacknowledged effect into a terminal.

use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::NativeHistoryMaintenanceReceipt;
use tokio::time::Instant;
use tokio::time::timeout_at;

use super::AppServerModelDriver;
use super::Result;
use crate::NativeCleanupBacklogMetrics;

/// Counts only exact owner acknowledgements and durable retirement performed
/// by this call. Failed or timed out aborts remain held for a later retry.
#[derive(Clone, Debug)]
pub struct NativeControlMaintenanceReceipt {
    pub aborts_attempted: usize,
    pub aborts_confirmed: usize,
    pub aborts_unresolved: usize,
    pub terminal_publications_attempted: usize,
    pub terminal_publications_acknowledged: usize,
    pub terminal_publications_unresolved: usize,
    pub history: Option<NativeHistoryMaintenanceReceipt>,
    pub cleanup: Option<NativeCleanupBacklogMetrics>,
}

impl AppServerModelDriver {
    /// Invoke at startup and while idle under the same serial control owner.
    /// Retried CAS requests contain the original durable nonce and proof; the
    /// cursor advances on failure so a disconnected owner cannot starve peers.
    /// Filesystem budgets are checked between bounded I/O units, not by
    /// abandoning an in-progress journal write or cleanup owner operation.
    pub async fn maintain_native_control(
        &mut self,
        control: &mut DurableInferenceControl,
        budget: Duration,
    ) -> Result<NativeControlMaintenanceReceipt> {
        if budget.is_zero() || budget > Duration::from_secs(5) {
            return Err("native owner maintenance requires a budget within five seconds".into());
        }
        let deadline = Instant::now() + budget;
        let abort_deadline = Instant::now() + budget / 2;
        let mut receipt = NativeControlMaintenanceReceipt {
            aborts_attempted: 0,
            aborts_confirmed: 0,
            aborts_unresolved: 0,
            terminal_publications_attempted: 0,
            terminal_publications_acknowledged: 0,
            terminal_publications_unresolved: 0,
            history: None,
            cleanup: None,
        };
        let mut visited = Vec::new();
        while receipt.aborts_attempted + receipt.terminal_publications_attempted < 8
            && Instant::now() < abort_deadline
        {
            let Some(record) =
                control.next_native_owner_reconciliation(&self.owner_reconciliation_cursor)
            else {
                break;
            };
            if visited.contains(&record.request.request_id) {
                break;
            }
            visited.push(record.request.request_id.clone());
            self.owner_reconciliation_cursor
                .clone_from(&record.request.request_id);
            if record.state == codex_hepta_infer_core::durable_control::native::NativeReservationState::AbortPending {
                receipt.aborts_attempted += 1;
                match timeout_at(abort_deadline, self.reconcile_pending_pre_effect_abort(control, &record)).await {
                    Ok(Ok(())) => receipt.aborts_confirmed += 1,
                    Ok(Err(_)) | Err(_) => receipt.aborts_unresolved += 1,
                }
            } else {
                receipt.terminal_publications_attempted += 1;
                match timeout_at(abort_deadline, self.publish_pending_intelligence_terminal(control, &record.request.request_id)).await {
                    Ok(Ok(())) => receipt.terminal_publications_acknowledged += 1,
                    Ok(Err(_)) | Err(_) => receipt.terminal_publications_unresolved += 1,
                }
            }
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if !remaining.is_zero() {
            receipt.cleanup = Some(
                self.maintain_native_cleanup(remaining.min(Duration::from_secs(1)))
                    .await?,
            );
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if !remaining.is_zero() {
            receipt.history = Some(control.maintain_native_history(1, remaining)?);
        }
        Ok(receipt)
    }
}

#[cfg(all(test, unix))]
#[path = "native_control_maintenance_tests.rs"]
mod tests;
