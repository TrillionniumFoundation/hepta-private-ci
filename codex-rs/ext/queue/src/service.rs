use std::collections::HashMap;
use std::collections::HashSet;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::sync::Weak;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_core::CodexThread;
use codex_core::StartIfIdleSubmission;
use codex_core::ThreadManager;
use codex_core::TurnInput;
use codex_core::TurnInputRequest;
use codex_extension_api::ExtensionEventSink;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ThreadIdleCause;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadResumeInput;
use codex_history::RolloutItem;
use codex_history::RolloutLine;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::items::TurnItem;
use codex_protocol::models::snapshot_local_user_input;
use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ThreadQueueChangedEvent;
use codex_protocol::protocol::TurnRecoveryCandidateState;
use codex_protocol::protocol::W3cTraceContext;
use codex_protocol::user_input::MAX_USER_INPUT_TEXT_CHARS;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_rollout::open_rollout_line_reader;
use codex_thread_store::MAX_QUEUE_ITEMS;
use codex_thread_store::QueueStore;
use codex_thread_store::QueuedClientBindingFinalizeMode;
use codex_thread_store::QueuedClientBindingFinalizeOutcome;
use codex_thread_store::QueuedClientBindingReserveOutcome;
use codex_thread_store::QueuedClientDispatchClaimOutcome;
use codex_thread_store::QueuedClientDispatchLease;
use codex_thread_store::QueuedClientDispatchLock;
use codex_thread_store::QueuedUserSubmissionRecord;
use codex_thread_store::ThreadStoreError;
use thiserror::Error;
use tokio::sync::Mutex;
use tokio::sync::OwnedMutexGuard;
use tokio::sync::broadcast::error::TryRecvError;
use uuid::Uuid;

const DISPATCH_LEASE_DURATION_MS: i64 = 30_000;
const UNCERTAIN_DISPATCH_POLL_MS: u64 = 20;

/// One user message waiting to start on its thread.
#[derive(Clone, Debug, PartialEq)]
pub struct QueuedItem {
    pub id: String,
    pub input: TurnInput,
}

/// Whether an exact reconciliation may create a row when neither the durable
/// queue nor the rollout contains the client-message identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QueueReconcileMode {
    AllowIfAbsent,
    ReconcileOnly,
}

#[derive(Clone, Debug, PartialEq)]
#[allow(clippy::large_enum_variant)]
pub enum QueueReconcileOutcome {
    Queued { item: QueuedItem, created: bool },
    Persisted { turn_id: String },
    Missing,
    Cancelled,
}

#[derive(Clone, Debug, PartialEq)]
pub struct QueueReconcileResponse {
    pub client_user_message_id: String,
    /// Authoritative digest recomputed from the normalized server-side input.
    pub payload_sha256: String,
    pub outcome: QueueReconcileOutcome,
}

#[derive(Debug, Error)]
pub enum QueueServiceError {
    #[error("queue storage failed: {0}")]
    Storage(#[from] ThreadStoreError),
    #[error("queued submission payload is invalid: {0}")]
    InvalidPayload(#[from] serde_json::Error),
    #[error("local queued attachment is invalid: {0}")]
    InvalidAttachment(#[from] std::io::Error),
    #[error("Core failed to submit queued user message: {0}")]
    CoreSubmissionError(#[from] CodexErr),
    #[error("only user input can be added to the user-message queue")]
    InvalidInput,
    #[error("thread/queue/reconcile accepts Matrix text input only")]
    ReconcileRequiresTextInput,
    #[error("exact client message `{client_id}` already has a live dispatch owner")]
    DispatchInProgress { client_id: String },
    #[error(
        "queued client id `{client_id}` is already bound to a different payload ({expected_sha256} != {actual_sha256})"
    )]
    ClientIdPayloadConflict {
        client_id: String,
        expected_sha256: String,
        actual_sha256: String,
    },
    #[error(
        "persisted client id `{client_id}` has only a legacy payload projection and cannot authorize an exactly-once join"
    )]
    LegacyClientIdBinding { client_id: String },
    #[error("persisted client id `{client_id}` is bound to multiple turns")]
    AmbiguousClientIdBinding { client_id: String },
    #[error(
        "queued user input exceeds the maximum length of {MAX_USER_INPUT_TEXT_CHARS} characters ({actual_chars} provided)"
    )]
    InputTooLarge { actual_chars: usize },
}

#[derive(Clone)]
pub struct QueuedItemService {
    queue: Arc<dyn QueueStore>,
    thread_manager: Weak<ThreadManager>,
    event_sink: Arc<dyn ExtensionEventSink>,
    dispatch_locks: Arc<StdMutex<HashMap<ThreadId, Weak<Mutex<()>>>>>,
    resumed_threads: Arc<StdMutex<HashSet<ThreadId>>>,
    dispatch_owner_id: String,
}

struct OwnedDispatchRequest {
    input: TurnInput,
    trace: Option<W3cTraceContext>,
    client_id: String,
    payload_sha256: String,
}

/// Process-local authority that must outlive every potentially-routed Core
/// admission attempt. Potentially panicking work runs in monitored child
/// tasks; this value stays in their owner task and is transferred to the
/// settlement guardian if a child unwinds.
struct OwnedDispatchAuthority {
    process_lock: QueuedClientDispatchLock,
    lease: QueuedClientDispatchLease,
}

impl QueuedItemService {
    pub fn new(
        queue: Arc<dyn QueueStore>,
        thread_manager: Weak<ThreadManager>,
        event_sink: Arc<dyn ExtensionEventSink>,
    ) -> Self {
        Self {
            queue,
            thread_manager,
            event_sink,
            dispatch_locks: Arc::new(StdMutex::new(HashMap::new())),
            resumed_threads: Arc::new(StdMutex::new(HashSet::new())),
            dispatch_owner_id: Uuid::now_v7().to_string(),
        }
    }

    // Check SQLite's inexpensive data version every 10 seconds, then use the
    // durable revision index to discover only changed threads. Independent
    // dispatch tasks keep a blocked or failed thread from starving other queues.
    pub(crate) async fn watch_external_messages(service: Weak<Self>) {
        let mut last_version = None;
        let mut last_revision = 0;
        let mut dispatches: HashMap<ThreadId, tokio::task::JoinHandle<()>> = HashMap::new();
        let mut interval = tokio::time::interval(Duration::from_secs(/*secs*/ 10));
        let mut manager_initialized = false;
        let mut thread_created = None;
        let mut newly_loaded_threads = HashSet::new();
        loop {
            interval.tick().await;
            let Some(service) = service.upgrade() else {
                return;
            };
            let Some(manager) = service.thread_manager.upgrade() else {
                if manager_initialized {
                    return;
                }
                drop(service);
                tokio::time::sleep(Duration::from_millis(/*millis*/ 1)).await;
                interval.reset_immediately();
                continue;
            };
            manager_initialized = true;
            let thread_created =
                thread_created.get_or_insert_with(|| manager.subscribe_thread_created());
            loop {
                match thread_created.try_recv() {
                    Ok(thread_id) => {
                        newly_loaded_threads.insert(thread_id);
                    }
                    Err(TryRecvError::Lagged(_)) => {
                        newly_loaded_threads.extend(manager.list_thread_ids().await);
                    }
                    Err(TryRecvError::Empty) => break,
                    Err(TryRecvError::Closed) => return,
                }
            }
            newly_loaded_threads.extend(
                service
                    .resumed_threads
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .drain(),
            );

            let version = match service.queue.change_version().await {
                Ok(version) => version,
                Err(error) => {
                    tracing::warn!(%error, "failed to check queue change version");
                    continue;
                }
            };
            let version_changed = last_version != Some(version);
            if !version_changed && newly_loaded_threads.is_empty() {
                continue;
            }

            let thread_ids = manager.list_thread_ids().await;
            let mut changes = Vec::new();
            let mut observed_revision = last_revision;
            if version_changed {
                match service
                    .queue
                    .changes_since(last_revision, &thread_ids)
                    .await
                {
                    Ok(changed_threads) => {
                        if let Some((_, revision)) = changed_threads.last() {
                            observed_revision = *revision;
                        }
                        changes.extend(changed_threads);
                    }
                    Err(error) => {
                        tracing::warn!(%error, "failed to discover changed thread queues");
                        continue;
                    }
                }
            }
            if !newly_loaded_threads.is_empty() {
                let created_threads = thread_ids
                    .iter()
                    .copied()
                    .filter(|thread_id| newly_loaded_threads.contains(thread_id))
                    .collect::<Vec<_>>();
                match service
                    .queue
                    .changes_since(/*revision*/ 0, &created_threads)
                    .await
                {
                    Ok(changed_threads) => changes.extend(changed_threads),
                    Err(error) => {
                        tracing::warn!(%error, "failed to discover newly loaded thread queues");
                        continue;
                    }
                }
            }
            last_version = Some(version);
            last_revision = observed_revision;
            newly_loaded_threads.clear();
            dispatches.retain(|_, dispatch| !dispatch.is_finished());

            let mut changed_threads = HashSet::new();
            for (thread_id, _) in changes {
                if !changed_threads.insert(thread_id) {
                    continue;
                }
                service.emit_changed(thread_id);
                if dispatches
                    .get(&thread_id)
                    .is_some_and(|dispatch| !dispatch.is_finished())
                {
                    continue;
                }
                let service = Arc::downgrade(&service);
                let dispatch = tokio::spawn(async move {
                    loop {
                        {
                            let Some(service) = service.upgrade() else {
                                return;
                            };
                            let Some(manager) = service.thread_manager.upgrade() else {
                                return;
                            };
                            let Ok(thread) = manager.get_thread(thread_id).await else {
                                return;
                            };
                            if matches!(
                                thread.agent_status().await,
                                AgentStatus::Running
                                    | AgentStatus::Interrupted
                                    | AgentStatus::Shutdown
                                    | AgentStatus::NotFound
                            ) {
                                return;
                            }
                            match service
                                .queue
                                .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
                                .await
                            {
                                Ok(items) if items.is_empty() => return,
                                Ok(_) => service.wake_if_loaded(thread_id).await,
                                Err(error) => {
                                    tracing::warn!(%thread_id, %error, "failed to check queued user input");
                                }
                            }
                        }
                        tokio::time::sleep(Duration::from_secs(/*secs*/ 10)).await;
                    }
                });
                dispatches.insert(thread_id, dispatch);
            }
        }
    }

    fn dispatch_lock(&self, thread_id: ThreadId) -> Arc<Mutex<()>> {
        let mut locks = self
            .dispatch_locks
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        locks.retain(|_, lock| lock.strong_count() != 0);
        if let Some(lock) = locks.get(&thread_id).and_then(Weak::upgrade) {
            return lock;
        }
        let lock = Arc::new(Mutex::new(()));
        locks.insert(thread_id, Arc::downgrade(&lock));
        lock
    }

    async fn dispatch_guard(&self, thread_id: ThreadId) -> OwnedMutexGuard<()> {
        self.dispatch_lock(thread_id).lock_owned().await
    }

    pub async fn enqueue(
        &self,
        thread_id: ThreadId,
        input: TurnInput,
    ) -> Result<QueuedItem, QueueServiceError> {
        let input = prepare_queued_user_input(input).await?;
        let client_id = queued_client_id(&input)?.to_string();
        let payload_sha256 = queued_payload_sha256(&input)?;
        let payload = serde_json::to_string(&input)?;
        let item = {
            let _dispatch_guard = self.dispatch_guard(thread_id).await;
            let item = queued_item_from_record(
                self.queue
                    .enqueue_guarded(thread_id, payload, client_id, payload_sha256)
                    .await?,
            )?;
            self.emit_changed(thread_id);
            item
        };
        self.wake_if_loaded(thread_id).await;
        Ok(item)
    }

    /// Atomically reconcile or admit one exact client-message binding.
    ///
    /// SQLite reservation is the cross-process serialization point. The exact
    /// rollout is scanned outside the writer lock, then a CAS finalization
    /// either records the persisted turn or creates/adopts one queue row.
    pub async fn reconcile(
        &self,
        thread_id: ThreadId,
        rollout_path: Option<PathBuf>,
        input: TurnInput,
        expected_payload_sha256: String,
        mode: QueueReconcileMode,
    ) -> Result<QueueReconcileResponse, QueueServiceError> {
        let TurnInput::UserInput { content, .. } = &input else {
            return Err(QueueServiceError::InvalidInput);
        };
        if content.is_empty()
            || !content
                .iter()
                .all(|item| matches!(item, UserInput::Text { .. }))
        {
            return Err(QueueServiceError::ReconcileRequiresTextInput);
        }
        let input = prepare_queued_user_input(input).await?;
        let client_id = queued_client_id(&input)?.to_string();
        let payload_sha256 = queued_payload_sha256(&input)?;
        ensure_payload_digest_matches(&client_id, &expected_payload_sha256, &payload_sha256)?;
        let payload = serde_json::to_string(&input)?;
        let response_client_id = client_id.clone();
        let response_payload_sha256 = payload_sha256.clone();
        let dispatch_guard = self.dispatch_guard(thread_id).await;

        let reservation = self
            .queue
            .reserve_client_binding(
                thread_id,
                client_id.clone(),
                payload_sha256.clone(),
                payload.clone(),
            )
            .await?;
        let outcome = match reservation {
            QueuedClientBindingReserveOutcome::Persisted { turn_id } => {
                QueueReconcileOutcome::Persisted { turn_id }
            }
            QueuedClientBindingReserveOutcome::Cancelled => {
                if let Some(turn_id) = persisted_turn_for_client_id_path(
                    rollout_path.as_deref(),
                    &client_id,
                    &payload_sha256,
                )
                .await?
                {
                    let bound = self
                        .queue
                        .mark_client_binding_persisted(
                            thread_id,
                            client_id,
                            payload_sha256,
                            String::new(),
                            turn_id.clone(),
                        )
                        .await?;
                    if !bound {
                        return Err(ThreadStoreError::Internal {
                            message:
                                "cancelled exact binding disappeared during rollout reconciliation"
                                    .to_string(),
                        }
                        .into());
                    }
                    self.emit_changed(thread_id);
                    QueueReconcileOutcome::Persisted { turn_id }
                } else {
                    QueueReconcileOutcome::Cancelled
                }
            }
            QueuedClientBindingReserveOutcome::Queued(record) => {
                if let Some(turn_id) = persisted_turn_for_client_id_path(
                    rollout_path.as_deref(),
                    &client_id,
                    &payload_sha256,
                )
                .await?
                {
                    let bound = self
                        .queue
                        .mark_client_binding_persisted(
                            thread_id,
                            client_id,
                            payload_sha256,
                            record.id,
                            turn_id.clone(),
                        )
                        .await?;
                    if !bound {
                        return Err(ThreadStoreError::Internal {
                            message: "exact queue binding disappeared during reconciliation"
                                .to_string(),
                        }
                        .into());
                    }
                    self.emit_changed(thread_id);
                    QueueReconcileOutcome::Persisted { turn_id }
                } else {
                    QueueReconcileOutcome::Queued {
                        item: queued_item_from_record(record)?,
                        created: false,
                    }
                }
            }
            QueuedClientBindingReserveOutcome::Dispatching(record) => {
                QueueReconcileOutcome::Queued {
                    item: queued_item_from_record(record)?,
                    created: false,
                }
            }
            QueuedClientBindingReserveOutcome::Reserved(lease) => {
                let observed_turn_id = persisted_turn_for_client_id_path(
                    rollout_path.as_deref(),
                    &client_id,
                    &payload_sha256,
                )
                .await?;
                let finalize_mode = match mode {
                    QueueReconcileMode::AllowIfAbsent => {
                        QueuedClientBindingFinalizeMode::AllowIfAbsent
                    }
                    QueueReconcileMode::ReconcileOnly => {
                        QueuedClientBindingFinalizeMode::ReconcileOnly
                    }
                };
                match self
                    .queue
                    .finalize_client_binding(
                        thread_id,
                        client_id,
                        payload_sha256,
                        payload,
                        lease,
                        finalize_mode,
                        observed_turn_id,
                    )
                    .await?
                {
                    QueuedClientBindingFinalizeOutcome::Queued { record, created } => {
                        self.emit_changed(thread_id);
                        QueueReconcileOutcome::Queued {
                            item: queued_item_from_record(record)?,
                            created,
                        }
                    }
                    QueuedClientBindingFinalizeOutcome::Persisted { turn_id } => {
                        // Finalization may have adopted and deleted a legacy
                        // queue row in the same transaction. Conservatively
                        // publish the durable queue revision for subscribers.
                        self.emit_changed(thread_id);
                        QueueReconcileOutcome::Persisted { turn_id }
                    }
                    QueuedClientBindingFinalizeOutcome::Missing => QueueReconcileOutcome::Missing,
                    QueuedClientBindingFinalizeOutcome::Cancelled => {
                        QueueReconcileOutcome::Cancelled
                    }
                }
            }
        };
        drop(dispatch_guard);
        if matches!(outcome, QueueReconcileOutcome::Queued { .. }) {
            self.wake_if_loaded(thread_id).await;
        }
        Ok(QueueReconcileResponse {
            client_user_message_id: response_client_id,
            payload_sha256: response_payload_sha256,
            outcome,
        })
    }

    pub async fn list(&self, thread_id: ThreadId) -> Result<Vec<QueuedItem>, QueueServiceError> {
        self.list_page(thread_id, /*offset*/ 0, MAX_QUEUE_ITEMS)
            .await
    }

    pub async fn list_page(
        &self,
        thread_id: ThreadId,
        offset: usize,
        limit: usize,
    ) -> Result<Vec<QueuedItem>, QueueServiceError> {
        self.queue
            .list_page(thread_id, offset, limit)
            .await?
            .into_iter()
            .map(queued_item_from_record)
            .collect()
    }

    pub async fn update(
        &self,
        thread_id: ThreadId,
        queued_item_id: String,
        mut input: TurnInput,
    ) -> Result<Option<QueuedItem>, QueueServiceError> {
        let _dispatch_guard = self.dispatch_guard(thread_id).await;
        if let TurnInput::UserInput { client_id, .. } = &mut input {
            *client_id = self
                .list(thread_id)
                .await?
                .into_iter()
                .find_map(|item| match item {
                    QueuedItem {
                        id,
                        input: TurnInput::UserInput { client_id, .. },
                    } if id == queued_item_id => client_id,
                    _ => None,
                });
        }
        let input = prepare_queued_user_input(input).await?;
        let payload = serde_json::to_string(&input)?;
        let item = self
            .queue
            .update(thread_id, queued_item_id, payload)
            .await?
            .map(queued_item_from_record)
            .transpose()?;
        if item.is_some() {
            self.emit_changed(thread_id);
        }
        Ok(item)
    }

    pub async fn delete(
        &self,
        thread_id: ThreadId,
        queued_item_id: String,
    ) -> Result<bool, QueueServiceError> {
        let _dispatch_guard = self.dispatch_guard(thread_id).await;
        self.delete_locked(thread_id, queued_item_id).await
    }

    async fn delete_locked(
        &self,
        thread_id: ThreadId,
        queued_item_id: String,
    ) -> Result<bool, QueueServiceError> {
        let deleted = self.queue.delete(thread_id, queued_item_id).await?;
        if deleted {
            self.emit_changed(thread_id);
        }
        Ok(deleted)
    }

    pub async fn reorder(
        &self,
        thread_id: ThreadId,
        ordered_ids: Vec<String>,
    ) -> Result<(), QueueServiceError> {
        let _dispatch_guard = self.dispatch_guard(thread_id).await;
        self.queue.reorder(thread_id, ordered_ids).await?;
        self.emit_changed(thread_id);
        Ok(())
    }

    /// Starts the selected queued message only when its thread is idle.
    pub async fn start(
        &self,
        thread: &CodexThread,
        queued_item_id: Option<String>,
        trace: Option<W3cTraceContext>,
    ) -> Result<StartIfIdleSubmission, QueueServiceError> {
        let thread_id = thread.session_configured().thread_id;
        let _dispatch_guard = self.dispatch_guard(thread_id).await;
        let item = self
            .list(thread_id)
            .await?
            .into_iter()
            .find(|item| queued_item_id.as_ref().is_none_or(|id| item.id == *id))
            .ok_or_else(|| ThreadStoreError::InvalidRequest {
                message: queued_item_id.as_ref().map_or_else(
                    || "queue is empty".to_string(),
                    |id| format!("queued submission not found: {id}"),
                ),
            })?;
        let queued_item_id = item.id.clone();
        let input @ TurnInput::UserInput { .. } = item.input else {
            return Err(QueueServiceError::InvalidInput);
        };
        let manager = self.thread_manager.upgrade().ok_or_else(|| {
            QueueServiceError::Storage(ThreadStoreError::Internal {
                message: "queue dispatch lost its loaded-thread manager".to_string(),
            })
        })?;
        let owned_thread = manager.get_thread(thread_id).await?;
        self.dispatch_one(owned_thread, queued_item_id, input, trace)
            .await
    }

    async fn dispatch_one(
        &self,
        thread: Arc<CodexThread>,
        queued_item_id: String,
        input: TurnInput,
        trace: Option<W3cTraceContext>,
    ) -> Result<StartIfIdleSubmission, QueueServiceError> {
        let thread_id = thread.session_configured().thread_id;
        let client_id = queued_client_id(&input)?.to_string();
        let payload_sha256 = queued_payload_sha256(&input)?;
        self.ensure_queue_payload_binding(thread_id, &queued_item_id, &client_id, &payload_sha256)
            .await?;

        let process_lock = self
            .queue
            .try_acquire_client_dispatch_lock(thread_id, client_id.clone(), payload_sha256.clone())?
            .ok_or_else(|| QueueServiceError::DispatchInProgress {
                client_id: client_id.clone(),
            })?;
        let (now_ms, lease_expires_at_ms) = dispatch_window()?;
        let claim = self
            .queue
            .claim_client_binding_dispatch(
                &process_lock,
                queued_item_id.clone(),
                self.dispatch_owner_id.clone(),
                now_ms,
                lease_expires_at_ms,
            )
            .await?;

        let lease = match claim {
            QueuedClientDispatchClaimOutcome::Unbound => {
                return self
                    .dispatch_unbound(
                        thread.as_ref(),
                        queued_item_id,
                        input,
                        trace,
                        &client_id,
                        &payload_sha256,
                    )
                    .await;
            }
            QueuedClientDispatchClaimOutcome::Acquired(lease) => {
                match persisted_turn_for_client_id(thread.as_ref(), &client_id, &payload_sha256)
                    .await
                {
                    Ok(Some(turn_id)) => {
                        self.complete_owned_dispatch(&process_lock, &lease, &turn_id)
                            .await?;
                        return Ok(StartIfIdleSubmission::Started { turn_id });
                    }
                    Ok(None) => lease,
                    Err(error) => {
                        self.queue
                            .release_client_binding_dispatch(&process_lock, lease)
                            .await?;
                        return Err(error);
                    }
                }
            }
            QueuedClientDispatchClaimOutcome::Expired(expired) => {
                // The OS lock is positive owner-death/release evidence. Only
                // after acquiring it do we inspect the exact rollout. Expiry
                // by itself never grants a resubmission.
                let observed_turn_id =
                    persisted_turn_for_client_id(thread.as_ref(), &client_id, &payload_sha256)
                        .await?;
                let (now_ms, lease_expires_at_ms) = dispatch_window()?;
                match self
                    .queue
                    .recover_expired_client_dispatch(
                        &process_lock,
                        expired,
                        self.dispatch_owner_id.clone(),
                        observed_turn_id,
                        now_ms,
                        lease_expires_at_ms,
                    )
                    .await?
                {
                    QueuedClientDispatchClaimOutcome::Acquired(lease) => lease,
                    QueuedClientDispatchClaimOutcome::Persisted { turn_id } => {
                        self.emit_changed(thread_id);
                        return Ok(StartIfIdleSubmission::Started { turn_id });
                    }
                    outcome => {
                        return Err(unexpected_dispatch_outcome(
                            &client_id,
                            "expired recovery",
                            outcome,
                        ));
                    }
                }
            }
            QueuedClientDispatchClaimOutcome::Persisted { turn_id } => {
                return Ok(StartIfIdleSubmission::Started { turn_id });
            }
            QueuedClientDispatchClaimOutcome::InFlight { .. } => {
                return Err(QueueServiceError::DispatchInProgress { client_id });
            }
            QueuedClientDispatchClaimOutcome::Cancelled => {
                return Err(ThreadStoreError::Conflict {
                    message: format!(
                        "exact client message `{client_id}` was cancelled before dispatch"
                    ),
                }
                .into());
            }
            QueuedClientDispatchClaimOutcome::Missing => {
                return Err(ThreadStoreError::InvalidRequest {
                    message: format!("queued submission not found: {queued_item_id}"),
                }
                .into());
            }
        };

        // Re-CAS immediately before the Core call. The process lock remains
        // held through persisted admission and SQLite completion, so another
        // process cannot turn lease expiry into a concurrent submit.
        let (now_ms, lease_expires_at_ms) = dispatch_window()?;
        let lease = self
            .queue
            .authorize_client_binding_dispatch(&process_lock, lease, now_ms, lease_expires_at_ms)
            .await?;
        // From this point forward, the exact authority is owned by a detached
        // service task. Dropping or aborting the caller only drops its
        // JoinHandle; it cannot drop the process lock or pending Core
        // admission after Core has accepted the turn.
        let service = self.clone();
        let dispatch = tokio::spawn(async move {
            service
                .run_owned_dispatch(
                    thread,
                    process_lock,
                    lease,
                    OwnedDispatchRequest {
                        input,
                        trace,
                        client_id,
                        payload_sha256,
                    },
                )
                .await
        });
        dispatch.await.map_err(|error| {
            QueueServiceError::Storage(ThreadStoreError::Internal {
                message: format!("owned exact queue dispatch task failed: {error}"),
            })
        })?
    }

    async fn run_owned_dispatch(
        &self,
        thread: Arc<CodexThread>,
        process_lock: QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
        request: OwnedDispatchRequest,
    ) -> Result<StartIfIdleSubmission, QueueServiceError> {
        let OwnedDispatchRequest {
            input,
            trace,
            client_id,
            payload_sha256,
        } = request;
        // Keep the exact authority in this owner task while Core admission
        // runs in a monitored child. A panic in Core may happen after the
        // message was routed to a detached session task, so the JoinError is
        // ambiguous and must never release the process fence.
        let admission_thread = Arc::clone(&thread);
        let admission = tokio::spawn(async move {
            admission_thread
                .start_turn_if_idle_and_wait_for_persisted_admission(
                    TurnInputRequest::new(input).with_trace(trace),
                )
                .await
        })
        .await;
        let submission = match admission {
            Ok(Ok(submission)) => submission,
            Ok(Err(error)) => {
                self.spawn_uncertain_owned_dispatch(
                    thread,
                    OwnedDispatchAuthority {
                        process_lock,
                        lease,
                    },
                    client_id,
                    payload_sha256,
                );
                return Err(CodexErr::from(error).into());
            }
            Err(error) => {
                self.spawn_uncertain_owned_dispatch(
                    thread,
                    OwnedDispatchAuthority {
                        process_lock,
                        lease,
                    },
                    client_id,
                    payload_sha256,
                );
                return Err(QueueServiceError::Storage(ThreadStoreError::Internal {
                    message: format!("owned exact Core admission task failed ambiguously: {error}"),
                }));
            }
        };
        match &submission {
            StartIfIdleSubmission::Started { turn_id } => {
                // Completion is also monitored because an adapter panic after
                // durable Core admission must not unwind through and drop the
                // authority. The owner retains its Arc while the child only
                // borrows the lock and lease.
                let authority = Arc::new(OwnedDispatchAuthority {
                    process_lock,
                    lease,
                });
                let completion_service = self.clone();
                let completion_authority = Arc::clone(&authority);
                let completion_turn_id = turn_id.clone();
                let completion = tokio::spawn(async move {
                    completion_service
                        .complete_owned_dispatch(
                            &completion_authority.process_lock,
                            &completion_authority.lease,
                            &completion_turn_id,
                        )
                        .await
                })
                .await;
                match completion {
                    Ok(Ok(())) => {}
                    // Core already returned a durable turn id, so a typed DB
                    // completion error can safely fall back to the existing
                    // owner-death + exact-rollout recovery path. Unlike a
                    // panic, it is not evidence that control flow escaped the
                    // adapter at an unknown point.
                    Ok(Err(error)) => return Err(error),
                    Err(error) => {
                        self.spawn_shared_uncertain_owned_dispatch(
                            thread,
                            authority,
                            client_id,
                            payload_sha256,
                        );
                        return Err(QueueServiceError::Storage(ThreadStoreError::Internal {
                            message: format!(
                                "owned exact dispatch completion task failed ambiguously: {error}"
                            ),
                        }));
                    }
                }
            }
            StartIfIdleSubmission::NotSubmitted { .. } => {
                self.queue
                    .release_client_binding_dispatch(&process_lock, lease)
                    .await?;
            }
        }
        Ok(submission)
    }

    fn spawn_uncertain_owned_dispatch(
        &self,
        thread: Arc<CodexThread>,
        authority: OwnedDispatchAuthority,
        client_id: String,
        payload_sha256: String,
    ) {
        self.spawn_shared_uncertain_owned_dispatch(
            thread,
            Arc::new(authority),
            client_id,
            payload_sha256,
        );
    }

    fn spawn_shared_uncertain_owned_dispatch(
        &self,
        thread: Arc<CodexThread>,
        authority: Arc<OwnedDispatchAuthority>,
        client_id: String,
        payload_sha256: String,
    ) {
        let service = self.clone();
        tokio::spawn(async move {
            if let Err(settlement_error) = service
                .settle_uncertain_owned_dispatch(thread, authority, client_id, payload_sha256)
                .await
            {
                tracing::warn!(
                    %settlement_error,
                    "failed to settle uncertain exact queue dispatch"
                );
            }
        });
    }

    async fn settle_uncertain_owned_dispatch(
        &self,
        thread: Arc<CodexThread>,
        authority: Arc<OwnedDispatchAuthority>,
        client_id: String,
        payload_sha256: String,
    ) -> Result<(), QueueServiceError> {
        loop {
            // The guardian retains one Arc while each scan/completion probe
            // runs in a monitored child. A second panic in an adapter or
            // rollout reader therefore cannot unwind the guardian and release
            // the original authority.
            let probe_service = self.clone();
            let probe_thread = Arc::clone(&thread);
            let probe_authority = Arc::clone(&authority);
            let probe_client_id = client_id.clone();
            let probe_payload_sha256 = payload_sha256.clone();
            let probe = tokio::spawn(async move {
                let Some(turn_id) = persisted_turn_for_client_id(
                    probe_thread.as_ref(),
                    &probe_client_id,
                    &probe_payload_sha256,
                )
                .await?
                else {
                    return Ok::<bool, QueueServiceError>(false);
                };
                probe_service
                    .complete_owned_dispatch(
                        &probe_authority.process_lock,
                        &probe_authority.lease,
                        &turn_id,
                    )
                    .await?;
                Ok(true)
            })
            .await;
            match probe {
                Ok(Ok(true)) => return Ok(()),
                Ok(Ok(false)) => {}
                Ok(Err(error)) => {
                    tracing::warn!(
                        %client_id,
                        %error,
                        "failed to settle uncertain exact queue dispatch; retaining the process fence"
                    );
                }
                Err(error) => {
                    tracing::warn!(
                        %client_id,
                        %error,
                        "uncertain exact queue dispatch settlement probe panicked; retaining the process fence"
                    );
                }
            }
            // Agent lifecycle status is not a persistence barrier: terminal
            // status is published before the final rollout flush, and failed
            // recorder items may be retried later. Once Core returned an
            // ambiguous error after routing, retain the kernel owner fence
            // until the exact durable join succeeds or this runtime exits.
            tokio::time::sleep(Duration::from_millis(UNCERTAIN_DISPATCH_POLL_MS)).await;
        }
    }

    async fn dispatch_unbound(
        &self,
        thread: &CodexThread,
        queued_item_id: String,
        input: TurnInput,
        trace: Option<W3cTraceContext>,
        client_id: &str,
        payload_sha256: &str,
    ) -> Result<StartIfIdleSubmission, QueueServiceError> {
        let thread_id = thread.session_configured().thread_id;
        if let Some(turn_id) =
            persisted_turn_for_unbound_client_id(thread, client_id, payload_sha256).await?
        {
            self.finish_persisted_queue_item(
                thread_id,
                queued_item_id,
                client_id,
                payload_sha256,
                &turn_id,
            )
            .await?;
            return Ok(StartIfIdleSubmission::Started { turn_id });
        }
        let submission = thread
            .start_turn_if_idle_and_wait_for_persisted_admission(
                TurnInputRequest::new(input).with_trace(trace),
            )
            .await
            .map_err(CodexErr::from)?;
        if let StartIfIdleSubmission::Started { turn_id } = &submission {
            self.finish_persisted_queue_item(
                thread_id,
                queued_item_id,
                client_id,
                payload_sha256,
                turn_id,
            )
            .await?;
        }
        Ok(submission)
    }

    async fn complete_owned_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        lease: &QueuedClientDispatchLease,
        turn_id: &str,
    ) -> Result<(), QueueServiceError> {
        let thread_id = lease.thread_id();
        self.queue
            .complete_client_binding_dispatch(process_lock, lease, turn_id.to_string())
            .await?;
        self.emit_changed(thread_id);
        Ok(())
    }

    async fn dispatch_if_idle(&self, thread_id: ThreadId) -> Result<(), QueueServiceError> {
        let Some(manager) = self.thread_manager.upgrade() else {
            return Ok(());
        };
        let Ok(thread) = manager.get_thread(thread_id).await else {
            return Ok(());
        };

        loop {
            let Some(record) = self
                .queue
                .list_page(thread_id, /*offset*/ 0, /*limit*/ 1)
                .await?
                .into_iter()
                .next()
            else {
                return Ok(());
            };
            let queued_item_id = record.id.clone();

            let input = match serde_json::from_str::<TurnInput>(&record.payload) {
                Ok(input) => input,
                Err(error) => {
                    tracing::warn!(%queued_item_id, %error, "discarding invalid queued item");
                    self.delete_locked(thread_id, queued_item_id).await?;
                    continue;
                }
            };
            if !matches!(input, TurnInput::UserInput { .. }) {
                tracing::warn!(%queued_item_id, "discarding non-user queued input");
                self.delete_locked(thread_id, queued_item_id).await?;
                continue;
            }

            match self
                .dispatch_one(
                    thread.clone(),
                    queued_item_id.clone(),
                    input,
                    /*trace*/ None,
                )
                .await
            {
                Ok(StartIfIdleSubmission::Started { turn_id }) => {
                    tracing::info!(
                        %thread_id,
                        %queued_item_id,
                        %turn_id,
                        "dispatched or reconciled queued user input"
                    );
                    if matches!(
                        thread.agent_status().await,
                        AgentStatus::Running
                            | AgentStatus::Interrupted
                            | AgentStatus::Shutdown
                            | AgentStatus::NotFound
                    ) {
                        return Ok(());
                    }
                    continue;
                }
                Ok(StartIfIdleSubmission::NotSubmitted { reason }) => {
                    tracing::warn!(
                        %thread_id,
                        %queued_item_id,
                        ?reason,
                        "core could not start queued user input"
                    );
                    return Ok(());
                }
                Err(QueueServiceError::DispatchInProgress { .. }) => return Ok(()),
                Err(error) => {
                    tracing::warn!(
                        %thread_id,
                        %queued_item_id,
                        %error,
                        "core could not start queued user input"
                    );
                    return Ok(());
                }
            }
        }
    }

    async fn wake_if_loaded(&self, thread_id: ThreadId) {
        let Some(manager) = self.thread_manager.upgrade() else {
            return;
        };
        if let Ok(thread) = manager.get_thread(thread_id).await
            && !matches!(thread.agent_status().await, AgentStatus::Interrupted)
        {
            thread
                .emit_thread_idle_lifecycle_if_idle(ThreadIdleCause::Completed)
                .await;
        }
    }

    /// Reject a client id that is concurrently queued with different content.
    ///
    /// The rollout join below protects the crash boundary after Core admission.
    /// This preflight protects the earlier boundary where two durable queue rows
    /// already disagree before either one is submitted to Core.
    async fn ensure_queue_payload_binding(
        &self,
        thread_id: ThreadId,
        selected_item_id: &str,
        client_id: &str,
        expected_sha256: &str,
    ) -> Result<(), QueueServiceError> {
        for record in self
            .queue
            .list_page(thread_id, /*offset*/ 0, MAX_QUEUE_ITEMS)
            .await?
        {
            if record.id == selected_item_id {
                continue;
            }
            let Ok(input) = serde_json::from_str::<TurnInput>(&record.payload) else {
                // An unreadable row has no trustworthy client identity. It is
                // handled when it reaches the head and must not be interpreted
                // as evidence for an exactly-once join.
                continue;
            };
            let Ok(other_client_id) = queued_client_id(&input) else {
                continue;
            };
            if other_client_id != client_id {
                continue;
            }
            let actual_sha256 = queued_payload_sha256(&input)?;
            ensure_payload_digest_matches(client_id, expected_sha256, actual_sha256.as_str())?;
        }
        Ok(())
    }

    async fn finish_persisted_queue_item(
        &self,
        thread_id: ThreadId,
        queued_item_id: String,
        client_id: &str,
        payload_sha256: &str,
        turn_id: &str,
    ) -> Result<(), QueueServiceError> {
        if self
            .queue
            .mark_client_binding_persisted(
                thread_id,
                client_id.to_string(),
                payload_sha256.to_string(),
                queued_item_id.clone(),
                turn_id.to_string(),
            )
            .await?
        {
            self.emit_changed(thread_id);
            return Ok(());
        }
        self.delete_locked(thread_id, queued_item_id).await?;
        Ok(())
    }

    fn emit_changed(&self, thread_id: ThreadId) {
        self.event_sink.emit(Event {
            id: Uuid::now_v7().to_string(),
            msg: EventMsg::ThreadQueueChanged(ThreadQueueChangedEvent { thread_id }),
        });
    }
}

fn dispatch_window() -> Result<(i64, i64), QueueServiceError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| ThreadStoreError::Internal {
            message: format!("system clock cannot authorize queue dispatch: {error}"),
        })?;
    let now_ms =
        i64::try_from(elapsed.as_millis()).map_err(|error| ThreadStoreError::Internal {
            message: format!("system clock cannot fit queue dispatch timestamp: {error}"),
        })?;
    let lease_expires_at_ms = now_ms
        .checked_add(DISPATCH_LEASE_DURATION_MS)
        .ok_or_else(|| ThreadStoreError::Internal {
            message: "queue dispatch lease timestamp overflowed".to_string(),
        })?;
    Ok((now_ms, lease_expires_at_ms))
}

fn unexpected_dispatch_outcome(
    client_id: &str,
    operation: &str,
    outcome: QueuedClientDispatchClaimOutcome,
) -> QueueServiceError {
    ThreadStoreError::Internal {
        message: format!(
            "client message id `{client_id}` returned unexpected {operation} outcome: {outcome:?}"
        ),
    }
    .into()
}

async fn prepare_queued_user_input(mut input: TurnInput) -> Result<TurnInput, QueueServiceError> {
    let TurnInput::UserInput { content, client_id } = &mut input else {
        return Err(QueueServiceError::InvalidInput);
    };
    if content.is_empty() {
        return Err(QueueServiceError::InvalidInput);
    }
    let actual_chars: usize = content
        .iter()
        .filter_map(|item| match item {
            UserInput::Text { text, .. } => Some(text.chars().count()),
            _ => None,
        })
        .sum();
    if actual_chars > MAX_USER_INPUT_TEXT_CHARS {
        return Err(QueueServiceError::InputTooLarge { actual_chars });
    }
    client_id.get_or_insert_with(|| Uuid::now_v7().to_string());
    if !content.iter().any(|item| {
        matches!(
            item,
            UserInput::LocalImage { .. } | UserInput::LocalAudio { .. }
        )
    }) {
        return Ok(input);
    }

    tokio::task::spawn_blocking(move || {
        let mut input = input;
        if let TurnInput::UserInput { content, .. } = &mut input {
            for item in content {
                snapshot_local_user_input(item)?;
            }
        }
        Ok::<TurnInput, std::io::Error>(input)
    })
    .await
    .map_err(|error| QueueServiceError::InvalidAttachment(std::io::Error::other(error)))?
    .map_err(QueueServiceError::InvalidAttachment)
}

impl<C> ThreadLifecycleContributor<C> for QueuedItemService
where
    C: Send + Sync + 'static,
{
    fn on_thread_resume<'a>(&'a self, input: ThreadResumeInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) {
                self.resumed_threads
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .insert(thread_id);
            }
        })
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if input.cause == ThreadIdleCause::Interrupted {
                return;
            }
            let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) else {
                tracing::warn!(
                    level_id = input.thread_store.level_id(),
                    "queue extension received an invalid thread id"
                );
                return;
            };
            let _guard = self.dispatch_guard(thread_id).await;
            if let Err(error) = self.dispatch_if_idle(thread_id).await {
                tracing::warn!(%thread_id, %error, "failed to dispatch queued user input");
            }
        })
    }
}

fn queued_item_from_record(
    record: QueuedUserSubmissionRecord,
) -> Result<QueuedItem, QueueServiceError> {
    Ok(QueuedItem {
        id: record.id,
        input: serde_json::from_str::<TurnInput>(&record.payload)?,
    })
}

fn queued_client_id(input: &TurnInput) -> Result<&str, QueueServiceError> {
    let TurnInput::UserInput {
        client_id: Some(client_id),
        ..
    } = input
    else {
        return Err(QueueServiceError::InvalidInput);
    };
    if client_id.is_empty() {
        return Err(QueueServiceError::InvalidInput);
    }
    Ok(client_id)
}

fn queued_payload_sha256(input: &TurnInput) -> Result<String, QueueServiceError> {
    let TurnInput::UserInput { content, .. } = input else {
        return Err(QueueServiceError::InvalidInput);
    };
    user_input_payload_sha256(content).map_err(QueueServiceError::InvalidPayload)
}

fn ensure_payload_digest_matches(
    client_id: &str,
    expected_sha256: &str,
    actual_sha256: &str,
) -> Result<(), QueueServiceError> {
    if expected_sha256 == actual_sha256 {
        return Ok(());
    }
    Err(QueueServiceError::ClientIdPayloadConflict {
        client_id: client_id.to_string(),
        expected_sha256: expected_sha256.to_string(),
        actual_sha256: actual_sha256.to_string(),
    })
}

/// Returns the first durable turn that already contains this client message.
///
/// Queue deletion and rollout persistence are separate stores. A process can
/// therefore die after the rollout flush and before deleting the queue row.
/// The durable user-message client id is the recovery join: once observed,
/// dispatch removes the stale queue row without ever submitting it again.
async fn persisted_turn_for_client_id(
    thread: &CodexThread,
    client_id: &str,
    expected_sha256: &str,
) -> Result<Option<String>, QueueServiceError> {
    // Local threads are materialized lazily. Before the first accepted user
    // message the configured rollout path is intentionally absent, so there
    // cannot yet be a durable client-id match to reconcile.
    persisted_turn_for_client_id_path(thread.rollout_path().as_deref(), client_id, expected_sha256)
        .await
}

async fn persisted_turn_for_client_id_path(
    rollout_path: Option<&Path>,
    client_id: &str,
    expected_sha256: &str,
) -> Result<Option<String>, QueueServiceError> {
    persisted_turn_for_client_id_path_with_mode(
        rollout_path,
        client_id,
        expected_sha256,
        PersistedClientJoinMode::Exact,
    )
    .await
}

/// Compatibility queue/add does not claim exact dispatch authority. Legacy
/// rollouts therefore may use their turn-delimited UserMessage projection as
/// a best-effort crash join, but only when its canonical payload digest is
/// present and unique. Exact reconcile/dispatch always uses the stricter path
/// above and requires an explicit ItemStarted/ItemCompleted turn identity.
async fn persisted_turn_for_unbound_client_id(
    thread: &CodexThread,
    client_id: &str,
    expected_sha256: &str,
) -> Result<Option<String>, QueueServiceError> {
    persisted_turn_for_client_id_path_with_mode(
        thread.rollout_path().as_deref(),
        client_id,
        expected_sha256,
        PersistedClientJoinMode::LegacyCompatibility,
    )
    .await
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PersistedClientJoinMode {
    Exact,
    LegacyCompatibility,
}

async fn persisted_turn_for_client_id_path_with_mode(
    rollout_path: Option<&Path>,
    client_id: &str,
    expected_sha256: &str,
    mode: PersistedClientJoinMode,
) -> Result<Option<String>, QueueServiceError> {
    let Some(path) = rollout_path else {
        return Ok(None);
    };
    let mut reader = match open_rollout_line_reader(path).await {
        Ok(reader) => reader,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(queue_rollout_error(path, "open", error)),
    };
    let mut current_turn_id = None;
    // Recovery reuses the interrupted logical turn id.  Only a strict,
    // durable Unready -> replay-applied binding hand-off may authorize its
    // second TurnStarted boundary.  Keep the consumed marker separate from
    // the binding so an orphan or mismatched binding can never manufacture
    // recovery authority from the binding alone.
    let mut pending_recovery_unready = None;
    let mut recovery_restart_turn_id = None;
    let mut found = None;
    let mut legacy_turn_ids = HashSet::new();
    let mut legacy_without_digest = false;
    while let Some(line) = reader
        .next_line()
        .await
        .map_err(|error| queue_rollout_error(path, "read", error))?
    {
        if line.trim().is_empty() {
            continue;
        }
        let record = serde_json::from_str::<RolloutLine>(&line).map_err(|error| {
            QueueServiceError::Storage(ThreadStoreError::Internal {
                message: format!(
                    "failed to decode rollout `{}` during queue reconciliation: {error}",
                    path.display()
                ),
            })
        })?;
        scan_persisted_client_line(
            record.item,
            client_id,
            expected_sha256,
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
            &mut found,
            &mut legacy_turn_ids,
            &mut legacy_without_digest,
        )?;
    }
    if let Some(turn_id) = recovery_restart_turn_id {
        return Err(malformed_rollout_turn_boundary(format!(
            "recovery hand-off for turn `{turn_id}` was not followed by a turn start"
        )));
    }
    if legacy_turn_ids
        .iter()
        .any(|turn_id| found.as_deref() != Some(turn_id.as_str()))
    {
        if mode == PersistedClientJoinMode::LegacyCompatibility
            && found.is_none()
            && legacy_turn_ids.len() == 1
            && !legacy_without_digest
        {
            return Ok(legacy_turn_ids.into_iter().next());
        }
        return Err(QueueServiceError::LegacyClientIdBinding {
            client_id: client_id.to_string(),
        });
    }
    Ok(found)
}

#[expect(
    clippy::too_many_arguments,
    reason = "replay scanning keeps each mutable state component explicit"
)]
fn scan_persisted_client_line(
    item: RolloutItem,
    client_id: &str,
    expected_sha256: &str,
    current_turn_id: &mut Option<String>,
    pending_recovery_unready: &mut Option<(String, u64)>,
    recovery_restart_turn_id: &mut Option<String>,
    found: &mut Option<String>,
    legacy_turn_ids: &mut HashSet<String>,
    legacy_without_digest: &mut bool,
) -> Result<(), QueueServiceError> {
    // Once a replay hand-off has been durably applied, only warnings may
    // appear before the lifecycle's replacement TurnStarted.  In particular,
    // do not let response/history items or a second binding slip between the
    // binding and the restart boundary.
    if let Some(recovery_turn_id) = recovery_restart_turn_id.as_deref() {
        match item {
            RolloutItem::EventMsg(EventMsg::Warning(_)) => return Ok(()),
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                if event.turn_id != recovery_turn_id {
                    return Err(malformed_rollout_turn_boundary(format!(
                        "recovery hand-off for turn `{recovery_turn_id}` was followed by turn `{}`",
                        event.turn_id
                    )));
                }
                if let Some(active_turn_id) = current_turn_id.as_deref()
                    && active_turn_id != recovery_turn_id
                {
                    return Err(malformed_rollout_turn_boundary(format!(
                        "recovery hand-off for turn `{recovery_turn_id}` encountered active turn `{active_turn_id}`"
                    )));
                }
                *current_turn_id = Some(recovery_turn_id.to_string());
                *recovery_restart_turn_id = None;
                return Ok(());
            }
            _ => {
                return Err(malformed_rollout_turn_boundary(format!(
                    "recovery hand-off for turn `{recovery_turn_id}` was followed by a non-warning item before turn restart"
                )));
            }
        }
    }

    // An Unready marker remains eligible only across warnings and the
    // matching replay-applied binding.  Any ordinary history/lifecycle item
    // consumes that provisional state; a later binding is then an orphan and
    // is rejected below rather than being treated as authority.
    let preserves_pending_recovery = match &item {
        RolloutItem::EventMsg(EventMsg::Warning(_))
        | RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(_)) => true,
        RolloutItem::TurnRecoveryRequestBinding(binding) => {
            binding.replay_applied_from_generation.is_some()
        }
        _ => false,
    };
    if !preserves_pending_recovery {
        *pending_recovery_unready = None;
    }

    match item {
        RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
            if let Some(active_turn_id) = current_turn_id.as_deref() {
                return Err(malformed_rollout_turn_boundary(format!(
                    "turn `{}` started while turn `{active_turn_id}` was still active",
                    event.turn_id
                )));
            }
            *current_turn_id = Some(event.turn_id);
        }
        RolloutItem::TurnRecoveryRequestBinding(binding)
            if binding.replay_applied_from_generation.is_some() =>
        {
            let Some((pending_turn_id, pending_generation)) = pending_recovery_unready.take()
            else {
                return Err(malformed_rollout_turn_boundary(format!(
                    "replay-applied recovery binding for turn `{}` had no matching consumed Unready marker",
                    binding.turn_id
                )));
            };
            let Some(source_generation) = binding.replay_applied_from_generation else {
                unreachable!("binding arm is guarded by replay-applied generation");
            };
            if pending_turn_id != binding.turn_id
                || pending_generation != binding.generation
                || source_generation.checked_add(1) != Some(binding.generation)
                || binding.fingerprint_sha256.is_empty()
                || binding.history_boundary.is_none()
                || binding.replay.is_none()
            {
                return Err(malformed_rollout_turn_boundary(format!(
                    "replay-applied recovery binding for turn `{}` did not match its consumed Unready provenance",
                    binding.turn_id
                )));
            }
            if current_turn_id
                .as_deref()
                .is_some_and(|active_turn_id| active_turn_id != binding.turn_id)
            {
                return Err(malformed_rollout_turn_boundary(format!(
                    "replay-applied recovery binding for turn `{}` encountered a different active turn",
                    binding.turn_id
                )));
            }
            *recovery_restart_turn_id = Some(binding.turn_id);
        }
        RolloutItem::TurnRecoveryRequestBinding(_) => {
            // A non-replay binding is provenance for a candidate, not a
            // consumed recovery hand-off. It cannot preserve an Unready
            // marker or authorize a repeated lifecycle start.
            *pending_recovery_unready = None;
        }
        RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker)) => {
            if marker.state == TurnRecoveryCandidateState::Unready {
                if pending_recovery_unready.is_some() {
                    return Err(malformed_rollout_turn_boundary(format!(
                        "turn `{}` emitted a second Unready recovery marker before its first was consumed",
                        marker.turn_id
                    )));
                }
                if current_turn_id
                    .as_deref()
                    .is_some_and(|active_turn_id| active_turn_id != marker.turn_id)
                {
                    return Err(malformed_rollout_turn_boundary(format!(
                        "Unready recovery marker for turn `{}` crossed active turn `{}`",
                        marker.turn_id,
                        current_turn_id.as_deref().unwrap_or_default()
                    )));
                }
                *pending_recovery_unready = Some((marker.turn_id, marker.generation));
            } else {
                *pending_recovery_unready = None;
            }
        }
        RolloutItem::TurnContext(context) => {
            if let Some(turn_id) = context.turn_id {
                ensure_explicit_rollout_turn(current_turn_id.as_deref(), &turn_id, "turn context")?;
                *current_turn_id = Some(turn_id);
            }
        }
        RolloutItem::EventMsg(EventMsg::ItemStarted(event)) => {
            ensure_explicit_rollout_turn(
                current_turn_id.as_deref(),
                &event.turn_id,
                "item-started event",
            )?;
            scan_exact_user_message_item(
                event.turn_id,
                event.item,
                client_id,
                expected_sha256,
                found,
            )?;
        }
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) => {
            ensure_explicit_rollout_turn(
                current_turn_id.as_deref(),
                &event.turn_id,
                "item-completed event",
            )?;
            scan_exact_user_message_item(
                event.turn_id,
                event.item,
                client_id,
                expected_sha256,
                found,
            )?;
        }
        RolloutItem::EventMsg(EventMsg::UserMessage(event))
            if event.client_id.as_deref() == Some(client_id) =>
        {
            let Some(turn_id) = current_turn_id.clone() else {
                return Err(ThreadStoreError::Internal {
                    message: format!(
                        "persisted user message {client_id} has no owning turn identity"
                    ),
                }
                .into());
            };
            match event.payload_sha256 {
                Some(actual_sha256) => {
                    ensure_payload_digest_matches(client_id, expected_sha256, &actual_sha256)?;
                }
                None => *legacy_without_digest = true,
            }
            // This legacy projection has no explicit turn id of its own. It
            // may corroborate an exact ItemStarted/ItemCompleted binding for
            // the same turn, but can never authorize dispatch recovery alone.
            legacy_turn_ids.insert(turn_id);
        }
        RolloutItem::EventMsg(EventMsg::TurnComplete(event)) => {
            ensure_explicit_rollout_turn(
                current_turn_id.as_deref(),
                &event.turn_id,
                "turn-complete event",
            )?;
            *current_turn_id = None;
        }
        RolloutItem::EventMsg(EventMsg::TurnAborted(event)) => {
            let Some(turn_id) = event.turn_id else {
                return Err(malformed_rollout_turn_boundary(
                    "turn-aborted event omitted its turn identity".to_string(),
                ));
            };
            ensure_explicit_rollout_turn(
                current_turn_id.as_deref(),
                &turn_id,
                "turn-aborted event",
            )?;
            if current_turn_id.is_none() {
                return Err(malformed_rollout_turn_boundary(format!(
                    "turn-aborted event names turn `{turn_id}` without an active turn"
                )));
            }
            *current_turn_id = None;
        }
        _ => {}
    }
    Ok(())
}

fn ensure_explicit_rollout_turn(
    current_turn_id: Option<&str>,
    explicit_turn_id: &str,
    item_kind: &str,
) -> Result<(), QueueServiceError> {
    if let Some(current_turn_id) = current_turn_id
        && current_turn_id != explicit_turn_id
    {
        return Err(malformed_rollout_turn_boundary(format!(
            "{item_kind} names turn `{explicit_turn_id}` while turn `{current_turn_id}` is active"
        )));
    }
    if current_turn_id.is_none() && item_kind == "turn-complete event" {
        return Err(malformed_rollout_turn_boundary(format!(
            "{item_kind} names turn `{explicit_turn_id}` without an active turn"
        )));
    }
    Ok(())
}

fn malformed_rollout_turn_boundary(message: String) -> QueueServiceError {
    QueueServiceError::Storage(ThreadStoreError::Internal {
        message: format!(
            "malformed rollout turn boundary during exact queue reconciliation: {message}"
        ),
    })
}

fn scan_exact_user_message_item(
    turn_id: String,
    item: TurnItem,
    client_id: &str,
    expected_sha256: &str,
    found: &mut Option<String>,
) -> Result<(), QueueServiceError> {
    let TurnItem::UserMessage(item) = item else {
        return Ok(());
    };
    if item.client_id.as_deref() != Some(client_id) {
        return Ok(());
    }
    let actual_sha256 = queued_payload_sha256(&TurnInput::UserInput {
        content: item.content,
        client_id: item.client_id,
    })?;
    ensure_payload_digest_matches(client_id, expected_sha256, &actual_sha256)?;
    record_persisted_client_turn(client_id, turn_id, found)
}

fn record_persisted_client_turn(
    client_id: &str,
    turn_id: String,
    found: &mut Option<String>,
) -> Result<(), QueueServiceError> {
    if found.as_deref().is_some_and(|found| found != turn_id) {
        return Err(QueueServiceError::AmbiguousClientIdBinding {
            client_id: client_id.to_string(),
        });
    }
    found.get_or_insert(turn_id);
    Ok(())
}

fn queue_rollout_error(
    path: &std::path::Path,
    operation: &str,
    error: std::io::Error,
) -> QueueServiceError {
    ThreadStoreError::Internal {
        message: format!(
            "failed to {operation} rollout `{}` during queue reconciliation: {error}",
            path.display()
        ),
    }
    .into()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;
    use codex_history::TurnRecoveryEnvironmentSelection;
    use codex_history::TurnRecoveryHistoryBoundary;
    use codex_history::TurnRecoveryReplayV1;
    use codex_history::TurnRecoveryRequestBinding;
    use codex_history::TurnRecoveryStartState;
    use codex_protocol::protocol::TurnCompleteEvent;
    use codex_protocol::protocol::TurnRecoveryCandidateEvent;
    use codex_protocol::protocol::TurnRecoveryCandidateState;
    use codex_protocol::protocol::TurnStartedEvent;

    fn recovery_binding_record(turn_id: &str) -> TurnRecoveryRequestBinding {
        TurnRecoveryRequestBinding {
            turn_id: turn_id.to_string(),
            generation: 8,
            fingerprint_sha256: "fingerprint".to_string(),
            history_boundary: Some(TurnRecoveryHistoryBoundary {
                item_count: 1,
                prefix_sha256: "prefix".to_string(),
            }),
            replay: Some(TurnRecoveryReplayV1 {
                history_boundary: TurnRecoveryHistoryBoundary {
                    item_count: 1,
                    prefix_sha256: "prefix".to_string(),
                },
                turn_context_sha256: "context".to_string(),
                start: TurnRecoveryStartState {
                    final_output_json_schema: None,
                    parent_turn_id: None,
                    root_turn_id: Some(turn_id.to_string()),
                    responses_metadata_extra: BTreeMap::new(),
                },
                environments: vec![TurnRecoveryEnvironmentSelection {
                    environment_id: "environment".to_string(),
                    cwd: "/tmp".to_string(),
                    workspace_roots: vec!["/tmp".to_string()],
                }],
            }),
            replay_applied_from_generation: Some(7),
        }
    }

    fn recovery_binding(turn_id: &str) -> RolloutItem {
        RolloutItem::TurnRecoveryRequestBinding(recovery_binding_record(turn_id))
    }

    fn recovery_unready(turn_id: &str) -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(
            TurnRecoveryCandidateEvent {
                turn_id: turn_id.to_string(),
                generation: 8,
                state: TurnRecoveryCandidateState::Unready,
            },
        ))
    }

    fn warning() -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::Warning(codex_protocol::protocol::WarningEvent {
            message: "warning".to_string(),
        }))
    }

    fn turn_started(turn_id: &str) -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
            turn_id: turn_id.to_string(),
            trace_id: None,
            started_at: None,
            model_context_window: None,
            collaboration_mode_kind: Default::default(),
        }))
    }

    fn turn_completed(turn_id: &str) -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::TurnComplete(TurnCompleteEvent {
            turn_id: turn_id.to_string(),
            last_agent_message: None,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
            time_to_first_token_ms: None,
        }))
    }

    fn scan(
        item: RolloutItem,
        current_turn_id: &mut Option<String>,
        pending_recovery_unready: &mut Option<(String, u64)>,
        recovery_restart_turn_id: &mut Option<String>,
    ) -> Result<(), QueueServiceError> {
        let mut found = None;
        let mut legacy_turn_ids = HashSet::new();
        let mut legacy_without_digest = false;
        scan_persisted_client_line(
            item,
            "client",
            "digest",
            current_turn_id,
            pending_recovery_unready,
            recovery_restart_turn_id,
            &mut found,
            &mut legacy_turn_ids,
            &mut legacy_without_digest,
        )
    }

    #[test]
    fn replay_applied_binding_allows_same_turn_recovery_boundary() {
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        scan(
            recovery_unready("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect("matching Unready marker should be accepted");
        scan(
            warning(),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect("warnings may precede replay binding");
        scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect("replay-applied binding should extend the active turn");
        scan(
            turn_started("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect("same-id recovery start should be accepted");
        scan(
            turn_completed("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect("recovered turn should close normally");
        assert!(current_turn_id.is_none());
        assert!(recovery_restart_turn_id.is_none());
    }

    #[test]
    fn duplicate_turn_start_without_recovery_binding_fails_closed() {
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        let error = scan(
            turn_started("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect_err("unbound duplicate turn start must fail closed");
        assert!(error.to_string().contains("still active"));
    }

    #[test]
    fn orphan_or_mismatched_replay_binding_fails_closed() {
        let cases = [
            ("orphan", None, recovery_binding("turn-1")),
            (
                "wrong turn",
                Some(("other".to_string(), 8)),
                recovery_binding("turn-1"),
            ),
            (
                "wrong generation",
                Some(("turn-1".to_string(), 9)),
                recovery_binding("turn-1"),
            ),
        ];
        for (name, pending, binding) in cases {
            let mut current_turn_id = Some("turn-1".to_string());
            let mut pending_recovery_unready = pending;
            let mut recovery_restart_turn_id = None;
            let error = scan(
                binding,
                &mut current_turn_id,
                &mut pending_recovery_unready,
                &mut recovery_restart_turn_id,
            )
            .expect_err(name);
            assert!(
                error.to_string().contains("recovery binding"),
                "case: {name}"
            );
            assert!(recovery_restart_turn_id.is_none(), "case: {name}");
        }

        let mut invalid = recovery_binding_record("turn-1");
        invalid.replay = None;
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = Some(("turn-1".to_string(), 8));
        let mut recovery_restart_turn_id = None;
        let error = scan(
            RolloutItem::TurnRecoveryRequestBinding(invalid),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect_err("missing replay must fail closed");
        assert!(error.to_string().contains("provenance"));
        assert!(recovery_restart_turn_id.is_none());
    }

    #[test]
    fn recovery_binding_allows_only_warning_until_matching_restart() {
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        scan(
            recovery_unready("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();

        let error = scan(
            warning(),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        );
        assert!(error.is_ok());
        let error = scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect_err("duplicate replay binding must not be accepted");
        assert!(error.to_string().contains("non-warning item"));
    }

    #[test]
    fn recovery_binding_rejects_history_and_wrong_restart_id() {
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        scan(
            recovery_unready("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        let error = scan(
            turn_started("different-turn"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect_err("different restart id must fail closed");
        assert!(error.to_string().contains("followed by turn"));

        // Rebuild the state and ensure a non-warning history item cannot be
        // inserted between the binding and its lifecycle restart.
        let mut current_turn_id = Some("turn-1".to_string());
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        scan(
            recovery_unready("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        let error = scan(
            turn_completed("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .expect_err("history/lifecycle item before restart must fail closed");
        assert!(error.to_string().contains("non-warning item"));
    }

    #[test]
    fn controlled_interrupt_can_recover_from_idle_state() {
        let mut current_turn_id = None;
        let mut pending_recovery_unready = None;
        let mut recovery_restart_turn_id = None;
        scan(
            recovery_unready("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        scan(
            recovery_binding("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        scan(
            turn_started("turn-1"),
            &mut current_turn_id,
            &mut pending_recovery_unready,
            &mut recovery_restart_turn_id,
        )
        .unwrap();
        assert_eq!(current_turn_id.as_deref(), Some("turn-1"));
        assert!(recovery_restart_turn_id.is_none());
    }
}
