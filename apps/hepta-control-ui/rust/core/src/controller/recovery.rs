use super::Controller;
use crate::ledger::OperationState;

impl Controller {
    /// Select a bounded fair batch for the current authenticated principal.
    pub fn select_recovery(&mut self, now: u64) -> Vec<String> {
        self.scheduler.select(&self.ledger.pending_views(), now)
    }

    pub fn recovery_observed(&mut self, operation_id: &str, state: OperationState, now: u64) {
        self.scheduler.observed(operation_id, state, now);
    }

    pub fn recovery_failed(&mut self, operation_id: &str, now: u64) {
        self.scheduler.failed(operation_id, now);
    }

    pub fn recovery_batch_finished(&mut self, started: u64, now: u64) {
        self.scheduler.batch_finished(started, now);
    }
}
