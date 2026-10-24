//! Codex protocol adapter for an already authenticated, owner-selected thread.
//!
//! This adapter cannot start a thread or admit new input. AuthBus remains the
//! sole admission path. It retains the complete protocol receipts and events;
//! callers remain responsible for owner/generation checks and durable outcomes.

use std::sync::Arc;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;

use codex_app_server_client::AppServerRequestHandle;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadQueueDeleteParams;
use codex_app_server_protocol::ThreadQueueDeleteResponse;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::TurnInterruptParams;
use codex_app_server_protocol::TurnInterruptResponse;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::UserInput;

use super::REQUEST_TIMEOUT;
use super::TextSessionError;
use super::unavailable;

/// A request adapter bound to exactly one existing thread. The upstream handle
/// supports remote UDS and typed in-process transports without changing queue,
/// session or turn ownership. Constructing a handle does not create a runtime.
#[derive(Clone)]
pub(super) struct CodexTextBackend {
    handle: AppServerRequestHandle,
    thread_id: String,
    next_request_id: Arc<AtomicI64>,
}

impl CodexTextBackend {
    pub(super) fn new(handle: AppServerRequestHandle, thread_id: String) -> Self {
        Self {
            handle,
            thread_id,
            next_request_id: Arc::new(AtomicI64::new(1)),
        }
    }

    fn id(&self) -> RequestId {
        RequestId::Integer(self.next_request_id.fetch_add(1, Ordering::Relaxed))
    }

    async fn call<T: serde::de::DeserializeOwned>(
        &self,
        request: ClientRequest,
    ) -> Result<T, TextSessionError> {
        tokio::time::timeout(REQUEST_TIMEOUT, self.handle.request_typed(request))
            .await
            .map_err(unavailable)?
            .map_err(unavailable)
    }

    pub(super) async fn resume_existing(&self) -> Result<ThreadResumeResponse, TextSessionError> {
        self.call(ClientRequest::ThreadResume {
            request_id: self.id(),
            params: ThreadResumeParams {
                thread_id: self.thread_id.clone(),
                exclude_turns: true,
                ..Default::default()
            },
        })
        .await
    }

    /// Lookup only. A missing or cancelled original never permits admission.
    pub(super) async fn reconcile_original(
        &self,
        input: Vec<UserInput>,
        client_id: String,
        input_digest: String,
    ) -> Result<ThreadQueueReconcileResponse, TextSessionError> {
        self.call(ClientRequest::ThreadQueueReconcile {
            request_id: self.id(),
            params: ThreadQueueReconcileParams {
                thread_id: self.thread_id.clone(),
                input,
                client_user_message_id: client_id,
                expected_payload_sha256: input_digest,
                mode: ThreadQueueReconcileMode::ReconcileOnly,
            },
        })
        .await
    }

    pub(super) async fn delete_queued(
        &self,
        queued_submission_id: String,
    ) -> Result<ThreadQueueDeleteResponse, TextSessionError> {
        self.call(ClientRequest::ThreadQueueDelete {
            request_id: self.id(),
            params: ThreadQueueDeleteParams {
                thread_id: self.thread_id.clone(),
                queued_submission_id,
            },
        })
        .await
    }

    pub(super) async fn read_turn_page(
        &self,
        cursor: Option<String>,
    ) -> Result<ThreadTurnsListResponse, TextSessionError> {
        self.call(ClientRequest::ThreadTurnsList {
            request_id: self.id(),
            params: ThreadTurnsListParams {
                thread_id: self.thread_id.clone(),
                cursor,
                limit: Some(16),
                sort_direction: Some(SortDirection::Desc),
                items_view: Some(TurnItemsView::Full),
            },
        })
        .await
    }

    pub(super) async fn interrupt_turn(
        &self,
        turn_id: String,
    ) -> Result<TurnInterruptResponse, TextSessionError> {
        self.call(ClientRequest::TurnInterrupt {
            request_id: self.id(),
            params: TurnInterruptParams {
                thread_id: self.thread_id.clone(),
                turn_id,
            },
        })
        .await
    }
}

pub(super) fn notification_route(notification: &ServerNotification) -> Option<(&String, &String)> {
    match notification {
        ServerNotification::ItemStarted(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::ItemCompleted(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::AgentMessageDelta(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::CommandExecutionOutputDelta(value) => {
            Some((&value.thread_id, &value.turn_id))
        }
        ServerNotification::PlanDelta(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::TurnDiffUpdated(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::TurnPlanUpdated(value) => Some((&value.thread_id, &value.turn_id)),
        ServerNotification::TurnCompleted(value) => Some((&value.thread_id, &value.turn.id)),
        _ => None,
    }
}

pub(super) fn is_nonreplayable_delta(notification: &ServerNotification) -> bool {
    matches!(
        notification,
        ServerNotification::AgentMessageDelta(_)
            | ServerNotification::CommandExecutionOutputDelta(_)
            | ServerNotification::PlanDelta(_)
    )
}
