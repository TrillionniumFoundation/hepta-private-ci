use std::future::Future;
use std::pin::Pin;

use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixProtocolError;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::room_project_idempotency_key;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_store::InboxAdmissionDraft;
use codex_hepta_matrix_store::InboxDispatchRecord;
use codex_hepta_matrix_store::InboxDispatchState;
use codex_hepta_matrix_store::InboxQueuedDraft;
use codex_hepta_matrix_store::InboxRecord;
use codex_hepta_matrix_store::InboxState;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDisposition;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::RoomThreadBindingDraft;
use serde::Deserialize;
use tokio::sync::Semaphore;

use crate::MatrixAdmissionMode;
use crate::MatrixAppServerBridge;
use crate::MatrixAppServerTransport;
use crate::MatrixBridgeError;
use crate::MatrixSubmission;
use crate::MatrixSubmissionState;
use crate::RoomThreadBinding;

const MATRIX_ROOM_MESSAGE: &str = "m.room.message";
const MATRIX_TEXT_MESSAGE: &str = "m.text";
const DEFAULT_RECOVERY_LIMIT: usize = 1_024;

pub type MatrixRuntimeFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, MatrixBridgeError>> + Send + 'a>>;

/// Narrow seam between the durable runtime and Codex App Server admission.
pub trait MatrixRuntimeBridge: Send + Sync {
    fn ensure_room_thread<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        expected_thread_id: Option<&'a str>,
    ) -> MatrixRuntimeFuture<'a, RoomThreadBinding>;

    fn submit_matrix_event_on_binding<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        event_id: &'a MatrixEventId,
        input: Vec<UserInput>,
        binding: &'a RoomThreadBinding,
        admission_mode: MatrixAdmissionMode,
    ) -> MatrixRuntimeFuture<'a, MatrixSubmission>;
}

impl<T> MatrixRuntimeBridge for MatrixAppServerBridge<T>
where
    T: MatrixAppServerTransport,
{
    fn ensure_room_thread<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        expected_thread_id: Option<&'a str>,
    ) -> MatrixRuntimeFuture<'a, RoomThreadBinding> {
        Box::pin(async move {
            match expected_thread_id {
                Some(thread_id) => self.reconcile_room_thread(room_id, thread_id).await,
                None => self.ensure_room_thread(room_id).await,
            }
        })
    }

    fn submit_matrix_event_on_binding<'a>(
        &'a self,
        room_id: &'a MatrixRoomId,
        event_id: &'a MatrixEventId,
        input: Vec<UserInput>,
        binding: &'a RoomThreadBinding,
        admission_mode: MatrixAdmissionMode,
    ) -> MatrixRuntimeFuture<'a, MatrixSubmission> {
        Box::pin(async move {
            self.submit_matrix_event_on_binding(room_id, event_id, input, binding, admission_mode)
                .await
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MatrixDispatchOutcome {
    IgnoredUnsupported { event_id: MatrixEventId },
    Queued { dispatch: InboxDispatchRecord },
    Admitted { dispatch: InboxDispatchRecord },
    Completed { dispatch: InboxDispatchRecord },
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct MatrixRuntimeRecovery {
    pub outcomes: Vec<MatrixDispatchOutcome>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MatrixEventProjection {
    Ignored,
    Stored {
        kind: OutboxKind,
        disposition: OutboxDisposition,
    },
    TurnCompleted {
        dispatch: Box<InboxDispatchRecord>,
        disposition: OutboxDisposition,
    },
}

/// Restart-safe bridge from one Agent's durable Matrix inbox into one Agent's
/// Codex App Server queue, plus the minimal App Server-to-outbox projector.
pub struct MatrixRuntime<B> {
    store: MatrixDurableStore,
    bridge: B,
    operation: Semaphore,
    recovery_limit: usize,
}

impl<B> MatrixRuntime<B>
where
    B: MatrixRuntimeBridge,
{
    pub fn new(store: MatrixDurableStore, bridge: B) -> Self {
        Self {
            store,
            bridge,
            operation: Semaphore::new(1),
            recovery_limit: DEFAULT_RECOVERY_LIMIT,
        }
    }

    pub fn store(&self) -> &MatrixDurableStore {
        &self.store
    }

    pub fn bridge(&self) -> &B {
        &self.bridge
    }

    pub async fn process_event(
        &self,
        event_id: &MatrixEventId,
        now_ms: u64,
    ) -> Result<MatrixDispatchOutcome, MatrixRuntimeError> {
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixRuntimeError::Protocol("Matrix runtime operation gate closed".to_string())
        })?;
        let inbox = self
            .store
            .inbox(event_id)
            .await
            .store_operation("load inbox event")?
            .ok_or(MatrixRuntimeError::MissingInbox)?;
        self.process_inbox_locked(&inbox, now_ms).await
    }

    pub async fn recover_pending(
        &self,
        limit: usize,
        now_ms: u64,
    ) -> Result<MatrixRuntimeRecovery, MatrixRuntimeError> {
        if limit == 0 {
            return Err(MatrixRuntimeError::Invalid(
                "Matrix runtime recovery limit must be non-zero".to_string(),
            ));
        }
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixRuntimeError::Protocol("Matrix runtime operation gate closed".to_string())
        })?;
        self.recover_pending_locked(limit, now_ms).await
    }

    pub async fn project_app_server_event(
        &self,
        event: &AppServerEvent,
        now_ms: u64,
    ) -> Result<MatrixEventProjection, MatrixRuntimeError> {
        let _operation = self.operation.acquire().await.map_err(|_| {
            MatrixRuntimeError::Protocol("Matrix runtime operation gate closed".to_string())
        })?;
        let Some(projectable) = ProjectableEvent::from_app_server(event)? else {
            return Ok(MatrixEventProjection::Ignored);
        };

        // A turn event can race the local durable admission transition.  Core
        // has already persisted the user item before emitting turn activity,
        // so exact client-id reconciliation closes that window without a new
        // admission.
        self.recover_pending_locked(self.recovery_limit, now_ms)
            .await?;
        let Some(dispatch) = self
            .store
            .inbox_dispatch_for_turn(projectable.thread_id(), projectable.turn_id())
            .await
            .store_operation("find dispatch for projected turn")?
        else {
            return Ok(MatrixEventProjection::Ignored);
        };

        let disposition = self
            .enqueue_projection(&dispatch, &projectable, now_ms)
            .await?;
        if !projectable.is_terminal() {
            return Ok(MatrixEventProjection::Stored {
                kind: projectable.kind(),
                disposition,
            });
        }

        let admission = admission_from_dispatch(&dispatch, projectable.turn_id(), now_ms)?;
        let admitted = self
            .store
            .record_inbox_admitted(&admission)
            .await
            .store_operation("record projected turn admission")?;
        let completed_at_ms = now_ms.max(admitted.updated_at_ms);
        let completed = self
            .store
            .complete_inbox_dispatch(&admission, completed_at_ms)
            .await
            .store_operation("complete projected inbox dispatch")?;
        Ok(MatrixEventProjection::TurnCompleted {
            dispatch: Box::new(completed),
            disposition,
        })
    }

    async fn recover_pending_locked(
        &self,
        limit: usize,
        now_ms: u64,
    ) -> Result<MatrixRuntimeRecovery, MatrixRuntimeError> {
        let pending = self
            .store
            .pending_inbox(limit)
            .await
            .store_operation("list pending inbox events")?;
        let mut outcomes = Vec::with_capacity(pending.len());
        for inbox in pending {
            outcomes.push(self.process_inbox_locked(&inbox, now_ms).await?);
        }
        Ok(MatrixRuntimeRecovery { outcomes })
    }

    async fn process_inbox_locked(
        &self,
        inbox: &InboxRecord,
        now_ms: u64,
    ) -> Result<MatrixDispatchOutcome, MatrixRuntimeError> {
        if inbox.state == InboxState::Processed {
            return match self
                .store
                .inbox_dispatch(&inbox.event_id)
                .await
                .store_operation("load processed inbox dispatch")?
            {
                Some(dispatch) if dispatch.state == InboxDispatchState::Completed => {
                    Ok(MatrixDispatchOutcome::Completed { dispatch })
                }
                Some(_) => Err(MatrixRuntimeError::Protocol(
                    "processed Matrix inbox has a non-completed dispatch".to_string(),
                )),
                None => Ok(MatrixDispatchOutcome::IgnoredUnsupported {
                    event_id: inbox.event_id.clone(),
                }),
            };
        }

        let Some(input) = supported_text_input(inbox) else {
            self.store
                .mark_inbox_processed(&inbox.event_id, now_ms.max(inbox.received_at_ms))
                .await
                .store_operation("mark unsupported inbox event processed")?;
            return Ok(MatrixDispatchOutcome::IgnoredUnsupported {
                event_id: inbox.event_id.clone(),
            });
        };

        let at_ms = now_ms.max(inbox.received_at_ms);
        // The durable store binds the deterministic project idempotency key;
        // App Server separately returns its concrete project ID.
        let project_key = room_project_idempotency_key(self.store.owner_agent_id(), &inbox.room_id);
        let durable_binding = self
            .store
            .bind_room_thread(&RoomThreadBindingDraft {
                room_id: inbox.room_id.clone(),
                binding_revision: inbox.binding_revision,
                generation: inbox.generation,
                project_id: project_key.clone(),
                thread_id: None,
                changed_at_ms: at_ms,
            })
            .await
            .store_operation("bind deterministic room project")?;
        let dispatch = self
            .store
            .begin_inbox_dispatch(&inbox.event_id, at_ms)
            .await
            .store_operation("begin inbox dispatch")?;
        if dispatch.project_id != project_key {
            return Err(MatrixRuntimeError::Protocol(
                "durable dispatch project drifted from the exact Agent/room identity".to_string(),
            ));
        }

        let binding = self
            .bridge
            .ensure_room_thread(&inbox.room_id, durable_binding.thread_id.as_deref())
            .await?;
        if binding.project_id.is_empty() || binding.thread_id.is_empty() {
            return Err(MatrixRuntimeError::Protocol(
                "App Server bridge returned a non-exact room/thread binding".to_string(),
            ));
        }
        self.store
            .bind_room_thread(&RoomThreadBindingDraft {
                room_id: inbox.room_id.clone(),
                binding_revision: inbox.binding_revision,
                generation: inbox.generation,
                project_id: dispatch.project_id.clone(),
                thread_id: Some(binding.thread_id.clone()),
                changed_at_ms: at_ms.max(dispatch.updated_at_ms),
            })
            .await
            .store_operation("bind resolved App Server thread")?;

        let admission_mode = if dispatch.state == InboxDispatchState::Begun {
            MatrixAdmissionMode::AllowIfAbsent
        } else {
            MatrixAdmissionMode::ReconcileOnly
        };
        let submission = self
            .bridge
            .submit_matrix_event_on_binding(
                &inbox.room_id,
                &inbox.event_id,
                input,
                &binding,
                admission_mode,
            )
            .await?;
        if submission.binding != binding
            || submission.client_user_message_id != dispatch.client_user_message_id
        {
            return Err(MatrixRuntimeError::Protocol(
                "App Server submission identity drifted from durable dispatch".to_string(),
            ));
        }

        let transition_at_ms = at_ms.max(dispatch.updated_at_ms);
        match submission.state {
            MatrixSubmissionState::Queued {
                queued_submission_id,
            }
            | MatrixSubmissionState::ReconciledQueued {
                queued_submission_id,
            } => {
                let queued = self
                    .store
                    .record_inbox_queued(&InboxQueuedDraft {
                        event_id: inbox.event_id.clone(),
                        client_user_message_id: dispatch.client_user_message_id,
                        project_id: dispatch.project_id,
                        thread_id: binding.thread_id,
                        queued_submission_id,
                        queued_at_ms: transition_at_ms,
                    })
                    .await
                    .store_operation("record queued Core submission")?;
                Ok(MatrixDispatchOutcome::Queued { dispatch: queued })
            }
            MatrixSubmissionState::ReconciledTurn { turn_id } => {
                let admitted = self
                    .store
                    .record_inbox_admitted(&InboxAdmissionDraft {
                        event_id: inbox.event_id.clone(),
                        client_user_message_id: dispatch.client_user_message_id,
                        project_id: dispatch.project_id,
                        thread_id: binding.thread_id,
                        queued_submission_id: dispatch.queued_submission_id,
                        turn_id,
                        admitted_at_ms: transition_at_ms,
                    })
                    .await
                    .store_operation("record reconciled Core turn")?;
                Ok(MatrixDispatchOutcome::Admitted { dispatch: admitted })
            }
        }
    }

    async fn enqueue_projection(
        &self,
        dispatch: &InboxDispatchRecord,
        projectable: &ProjectableEvent,
        now_ms: u64,
    ) -> Result<OutboxDisposition, MatrixRuntimeError> {
        let logical_outbox_id = outbox_id(
            self.store.owner_agent_id(),
            &dispatch.room_id,
            projectable.thread_id(),
            projectable.turn_id(),
            projectable.item_id(),
            projectable.kind_name(),
        );
        let kind = projectable.kind();
        let payload = projectable.payload().as_bytes();
        let revision = match kind {
            OutboxKind::Final => match self
                .store
                .exact_outbox_revision(
                    &logical_outbox_id,
                    &dispatch.room_id,
                    kind,
                    payload,
                    dispatch.binding_revision,
                    dispatch.generation,
                )
                .await
                .store_operation("look up exact final outbox revision")?
            {
                Some(revision) => revision,
                None => self
                    .store
                    .next_outbox_revision(&logical_outbox_id)
                    .await
                    .store_operation("allocate final outbox revision")?,
            },
            OutboxKind::TextDelta => self
                .store
                .next_outbox_revision(&logical_outbox_id)
                .await
                .store_operation("allocate text-delta outbox revision")?,
            _ => 1,
        };
        let txn_id = transaction_id(&logical_outbox_id, revision)?;
        self.store
            .enqueue_outbox(&OutboxDraft {
                logical_outbox_id,
                revision,
                txn_id,
                room_id: dispatch.room_id.clone(),
                kind,
                payload: payload.to_vec(),
                binding_revision: dispatch.binding_revision,
                generation: dispatch.generation,
                created_at_ms: now_ms,
            })
            .await
            .store_operation("enqueue projected Matrix outbox message")
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TextMessageContent {
    msgtype: String,
    body: String,
    // Ingress already checked the configured mention gate. Preserve the SDK's
    // typed metadata here without forwarding it as agent input or authority.
    #[serde(default, rename = "m.mentions")]
    _mentions: TextMessageMentions,
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct TextMessageMentions {
    #[serde(default, rename = "user_ids")]
    _user_ids: Vec<MatrixUserId>,
    #[serde(default, rename = "room")]
    _room: bool,
}

fn supported_text_input(inbox: &InboxRecord) -> Option<Vec<UserInput>> {
    if inbox.event_type != MATRIX_ROOM_MESSAGE {
        return None;
    }
    let content: TextMessageContent = serde_json::from_slice(&inbox.payload).ok()?;
    if content.msgtype != MATRIX_TEXT_MESSAGE || content.body.trim().is_empty() {
        return None;
    }
    Some(vec![UserInput::Text {
        text: content.body,
        text_elements: Vec::new(),
    }])
}

enum ProjectableEvent {
    Delta {
        thread_id: String,
        turn_id: String,
        item_id: String,
        delta: String,
    },
    Final {
        thread_id: String,
        turn_id: String,
        item_id: String,
        text: String,
    },
    Terminal {
        thread_id: String,
        turn_id: String,
        status: &'static str,
    },
}

impl ProjectableEvent {
    fn from_app_server(event: &AppServerEvent) -> Result<Option<Self>, MatrixRuntimeError> {
        let notification = match event {
            AppServerEvent::ServerNotification(notification) => notification,
            AppServerEvent::Lagged { skipped } => {
                return Err(MatrixRuntimeError::Protocol(format!(
                    "App Server event stream skipped {skipped} events; snapshot/resync is required"
                )));
            }
            AppServerEvent::Disconnected { message } => {
                return Err(MatrixRuntimeError::Protocol(format!(
                    "App Server event stream disconnected before projection: {message}"
                )));
            }
            AppServerEvent::ServerRequest(_) => return Ok(None),
        };
        match notification.as_ref() {
            ServerNotification::AgentMessageDelta(delta) if !delta.delta.is_empty() => {
                Ok(Some(Self::Delta {
                    thread_id: delta.thread_id.clone(),
                    turn_id: delta.turn_id.clone(),
                    item_id: delta.item_id.clone(),
                    delta: delta.delta.clone(),
                }))
            }
            ServerNotification::ItemCompleted(completed) => {
                let ThreadItem::AgentMessage { id, text, .. } = &completed.item else {
                    return Ok(None);
                };
                if text.is_empty() {
                    return Ok(None);
                }
                Ok(Some(Self::Final {
                    thread_id: completed.thread_id.clone(),
                    turn_id: completed.turn_id.clone(),
                    item_id: id.clone(),
                    text: text.clone(),
                }))
            }
            ServerNotification::TurnCompleted(completed) => {
                let status = match completed.turn.status {
                    TurnStatus::Completed => "completed",
                    TurnStatus::Interrupted => "interrupted",
                    TurnStatus::Failed => "failed",
                    TurnStatus::InProgress => {
                        return Err(MatrixRuntimeError::Protocol(
                            "turn/completed carried an in-progress turn".to_string(),
                        ));
                    }
                };
                Ok(Some(Self::Terminal {
                    thread_id: completed.thread_id.clone(),
                    turn_id: completed.turn.id.clone(),
                    status,
                }))
            }
            _ => Ok(None),
        }
    }

    fn thread_id(&self) -> &str {
        match self {
            Self::Delta { thread_id, .. }
            | Self::Final { thread_id, .. }
            | Self::Terminal { thread_id, .. } => thread_id,
        }
    }

    fn turn_id(&self) -> &str {
        match self {
            Self::Delta { turn_id, .. }
            | Self::Final { turn_id, .. }
            | Self::Terminal { turn_id, .. } => turn_id,
        }
    }

    fn item_id(&self) -> &str {
        match self {
            Self::Delta { item_id, .. } | Self::Final { item_id, .. } => item_id,
            Self::Terminal { .. } => "turn-terminal",
        }
    }

    fn kind(&self) -> OutboxKind {
        match self {
            Self::Delta { .. } => OutboxKind::TextDelta,
            Self::Final { .. } => OutboxKind::Final,
            Self::Terminal { .. } => OutboxKind::Terminal,
        }
    }

    fn kind_name(&self) -> &'static str {
        match self {
            Self::Delta { .. } | Self::Final { .. } => "agent_message",
            Self::Terminal { .. } => "terminal",
        }
    }

    fn payload(&self) -> &str {
        match self {
            Self::Delta { delta, .. } => delta,
            Self::Final { text, .. } => text,
            Self::Terminal { status, .. } => status,
        }
    }

    fn is_terminal(&self) -> bool {
        matches!(self, Self::Terminal { .. })
    }
}

fn admission_from_dispatch(
    dispatch: &InboxDispatchRecord,
    turn_id: &str,
    now_ms: u64,
) -> Result<InboxAdmissionDraft, MatrixRuntimeError> {
    let thread_id = dispatch.thread_id.clone().ok_or_else(|| {
        MatrixRuntimeError::Protocol("turn event matched a dispatch without a thread".to_string())
    })?;
    if dispatch
        .turn_id
        .as_deref()
        .is_some_and(|existing| existing != turn_id)
    {
        return Err(MatrixRuntimeError::Protocol(
            "turn event disagrees with the durable dispatch turn".to_string(),
        ));
    }
    Ok(InboxAdmissionDraft {
        event_id: dispatch.event_id.clone(),
        client_user_message_id: dispatch.client_user_message_id.clone(),
        project_id: dispatch.project_id.clone(),
        thread_id,
        queued_submission_id: dispatch.queued_submission_id.clone(),
        turn_id: turn_id.to_string(),
        admitted_at_ms: now_ms.max(dispatch.updated_at_ms),
    })
}

#[derive(Debug, thiserror::Error)]
pub enum MatrixRuntimeError {
    #[error("invalid Matrix runtime request: {0}")]
    Invalid(String),
    #[error("Matrix runtime could not find the durable inbox event")]
    MissingInbox,
    #[error("Matrix runtime protocol violation: {0}")]
    Protocol(String),
    #[error(transparent)]
    Bridge(#[from] MatrixBridgeError),
    #[error(transparent)]
    Store(#[from] MatrixDurableError),
    #[error("Matrix durable store operation {operation} failed: {source}")]
    StoreOperation {
        operation: &'static str,
        source: MatrixDurableError,
    },
    #[error(transparent)]
    MatrixProtocol(#[from] MatrixProtocolError),
}

trait StoreResultExt<T> {
    fn store_operation(self, operation: &'static str) -> Result<T, MatrixRuntimeError>;
}

impl<T> StoreResultExt<T> for Result<T, MatrixDurableError> {
    fn store_operation(self, operation: &'static str) -> Result<T, MatrixRuntimeError> {
        self.map_err(|source| MatrixRuntimeError::StoreOperation { operation, source })
    }
}

#[cfg(test)]
mod tests;
