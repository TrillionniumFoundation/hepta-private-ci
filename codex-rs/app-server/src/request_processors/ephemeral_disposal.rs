//! Explicit live-runtime disposal; ordinary unsubscribe retains its idle cache.
//! The per-thread RPC queue serializes this operation against turn/start. The
//! existing pending-unload lock also fences listener attachment and resume.
use super::*;
use codex_app_server_protocol::ThreadEphemeralDisposalParams;

impl ThreadRequestProcessor {
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "disposal fences subscriptions with the existing pending-unload lock"
    )]
    pub(super) async fn dispose_ephemeral(
        &self,
        thread_id: ThreadId,
        connection_id: ConnectionId,
        disposal: ThreadEphemeralDisposalParams,
    ) -> Result<ThreadUnsubscribeResponse, JSONRPCErrorError> {
        if disposal.expected_session_id.is_empty() || disposal.expected_session_id.len() > 128 {
            return Err(invalid_request("expected ephemeral session is required"));
        }
        let Ok(thread) = self.thread_manager.get_thread(thread_id).await else {
            return Ok(ThreadUnsubscribeResponse {
                status: ThreadUnsubscribeStatus::NotLoaded,
            });
        };
        let config = thread.config_snapshot().await;
        if !config.ephemeral
            || thread.rollout_path().is_some()
            || thread.session_configured().session_id.to_string() != disposal.expected_session_id
        {
            return Err(invalid_request(
                "disposal requires the exact ephemeral session without persistent history",
            ));
        }
        if matches!(thread.agent_status().await, AgentStatus::Running) {
            return Err(invalid_request(
                "active ephemeral session cannot be disposed",
            ));
        }
        {
            let mut closing = self.pending_thread_unloads.lock().await;
            if self
                .thread_state_manager
                .subscribed_connection_ids(thread_id)
                .await
                .iter()
                .any(|subscriber| *subscriber != connection_id)
            {
                return Err(invalid_request(
                    "ephemeral session has another subscriber; disposal refused",
                ));
            }
            closing.insert(thread_id);
            self.thread_state_manager
                .unsubscribe_connection_from_thread(thread_id, connection_id)
                .await;
        }
        // Retain the same registered Arc and closing fence on failure/cancellation.
        // shutdown_and_wait waits for Core's shared session-loop termination;
        // a later exact-session retry can finish it without starting a new turn.
        match wait_for_thread_shutdown(&thread).await {
            ThreadShutdownResult::SubmitFailed => {
                return Err(internal_error("ephemeral shutdown submission failed"));
            }
            ThreadShutdownResult::TimedOut => {
                return Err(internal_error("ephemeral shutdown is still pending"));
            }
            ThreadShutdownResult::Complete => {}
        }
        if self
            .thread_manager
            .remove_thread_if_matches(&thread_id, &thread)
            .await
            .is_none()
        {
            // Another teardown may have removed this same session. A live
            // replacement is never removed or reported as our disposed runtime.
            if self.thread_manager.get_thread(thread_id).await.is_ok() {
                return Err(invalid_request("ephemeral runtime changed during disposal"));
            }
        }
        self.finalize_thread_teardown(thread_id).await;
        self.outgoing
            .send_server_notification(ServerNotification::ThreadClosed(ThreadClosedNotification {
                thread_id: thread_id.to_string(),
            }))
            .await;
        Ok(ThreadUnsubscribeResponse {
            status: ThreadUnsubscribeStatus::EphemeralDisposed,
        })
    }
}
