use super::Session;

impl Session {
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and pending approval provenance must remain atomic"
    )]
    pub(super) async fn mark_explicit_exec_approval_cancelled(
        &self,
        approval_id: &str,
        supplied_turn_id: Option<&str>,
    ) {
        let active = self.active_turn.lock().await;
        if self.shutdown_started() || self.has_pending_task_terminalization() {
            return;
        }
        if let Some(active) = active.as_ref()
            && active.task_terminalization.is_none()
        {
            active
                .turn_state
                .lock()
                .await
                .mark_pending_exec_approval_cancelled(approval_id, supplied_turn_id);
        }
        // Both existing locks are released before the handler interrupts.
    }
}
