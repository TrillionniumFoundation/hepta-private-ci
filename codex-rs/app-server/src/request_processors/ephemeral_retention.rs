//! Explicit positive V1 acknowledgement of bounded, exact-session residency.
use super::*;
use codex_app_server_protocol::ThreadEphemeralRetainParams;
use codex_app_server_protocol::ThreadEphemeralRetainResponse;

impl ThreadRequestProcessor {
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "retention installation shares the existing exact unload fence"
    )]
    pub(crate) async fn thread_ephemeral_retain(
        &self,
        request_id: &ConnectionRequestId,
        params: ThreadEphemeralRetainParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        if params.protocol_version != 1
            || params.expected_session_id.is_empty()
            || params.expected_session_id.len() > 128
            || params.operation_id.is_empty()
            || params.operation_id.len() > 256
            || !params
                .operation_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
        {
            return Err(invalid_request("invalid ephemeral retention V1 binding"));
        }
        let thread_id = ThreadId::from_string(&params.thread_id)
            .map_err(|error| invalid_request(format!("invalid thread id: {error}")))?;
        let thread = self
            .thread_manager
            .get_thread(thread_id)
            .await
            .map_err(|_| invalid_request("ephemeral runtime is not loaded"))?;
        let config = thread.config_snapshot().await;
        let session_id = thread.session_configured().session_id.to_string();
        if !config.ephemeral
            || thread.rollout_path().is_some()
            || session_id != params.expected_session_id
        {
            return Err(invalid_request(
                "retention requires the exact ephemeral session without persistent history",
            ));
        }
        let closing = self.pending_thread_unloads.lock().await;
        if closing.contains(&thread_id) {
            return Err(invalid_request("ephemeral runtime is already closing"));
        }
        let current = self
            .thread_manager
            .get_thread(thread_id)
            .await
            .map_err(|_| invalid_request("ephemeral runtime is no longer loaded"))?;
        if !Arc::ptr_eq(&current, &thread) {
            return Err(invalid_request(
                "ephemeral runtime changed before retention",
            ));
        }
        let listener_state = self.thread_state_manager.thread_state(thread_id).await;
        if !listener_state.lock().await.listener_matches(&thread) {
            return Err(invalid_request(
                "ephemeral retention listener belongs to another runtime",
            ));
        }
        self.thread_state_manager
            .retain_ephemeral_runtime(
                thread_id,
                &thread,
                request_id.connection_id,
                params.operation_id.clone(),
            )
            .await
            .map_err(invalid_request)?;
        Ok(Some(
            ThreadEphemeralRetainResponse {
                protocol_version: 1,
                thread_id: thread_id.to_string(),
                session_id,
                operation_id: params.operation_id,
            }
            .into(),
        ))
    }
}
