use std::fmt::Display;
use std::future::Future;
use std::num::NonZeroUsize;

use codex_protocol::ThreadId;
use codex_rollout::StateDbHandle;
use codex_state::QueueCapacityExceeded;
use codex_state::QueueCapacityLimit;
use codex_state::QueuedClientBindingConflict;
use codex_state::QueuedClientBindingFinalizeMode;
use codex_state::QueuedClientBindingFinalizeOutcome;
use codex_state::QueuedClientBindingFinalizeRequest;
use codex_state::QueuedClientBindingLease;
use codex_state::QueuedClientBindingReserveOutcome;
use codex_state::QueuedClientDispatchClaimOutcome;
use codex_state::QueuedClientDispatchLease;
use codex_state::QueuedClientDispatchLock;
use codex_state::QueuedClientExpiredDispatch;
use codex_state::QueuedUserSubmissionRecord;
use codex_state::SqliteQueueStore;

use crate::MAX_QUEUE_ITEMS;
use crate::ThreadStoreError;
use crate::ThreadStoreFuture;

/// Storage-neutral persistence for ordered, thread-scoped user messages.
pub trait QueueStore: Send + Sync {
    /// Return a stable revision that changes when another connection updates the queue.
    fn change_version(&self) -> ThreadStoreFuture<'_, i64>;

    /// Return changed, loaded thread IDs and their durable revisions after `revision`.
    fn changes_since<'a>(
        &'a self,
        revision: i64,
        thread_ids: &'a [ThreadId],
    ) -> ThreadStoreFuture<'a, Vec<(ThreadId, i64)>>;

    fn enqueue(
        &self,
        thread_id: ThreadId,
        payload: String,
    ) -> ThreadStoreFuture<'_, QueuedUserSubmissionRecord>;

    /// Compatibility enqueue guarded by an exact binding that may have been
    /// created by `thread/queue/reconcile` in another process.
    fn enqueue_guarded(
        &self,
        thread_id: ThreadId,
        payload: String,
        client_id: String,
        payload_sha256: String,
    ) -> ThreadStoreFuture<'_, QueuedUserSubmissionRecord> {
        let _ = (thread_id, payload, client_id, payload_sha256);
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_enqueue_guarded",
            })
        })
    }

    fn reserve_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, QueuedClientBindingReserveOutcome> {
        let _ = (thread_id, client_id, payload_sha256, payload);
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_binding_reserve",
            })
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn finalize_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
        lease: QueuedClientBindingLease,
        mode: QueuedClientBindingFinalizeMode,
        observed_turn_id: Option<String>,
    ) -> ThreadStoreFuture<'_, QueuedClientBindingFinalizeOutcome> {
        let _ = (
            thread_id,
            client_id,
            payload_sha256,
            payload,
            lease,
            mode,
            observed_turn_id,
        );
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_binding_finalize",
            })
        })
    }

    fn mark_client_binding_persisted(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        queued_item_id: String,
        turn_id: String,
    ) -> ThreadStoreFuture<'_, bool> {
        let _ = (
            thread_id,
            client_id,
            payload_sha256,
            queued_item_id,
            turn_id,
        );
        Box::pin(async { Ok(false) })
    }

    fn try_acquire_client_dispatch_lock(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
    ) -> Result<Option<QueuedClientDispatchLock>, ThreadStoreError> {
        let _ = (thread_id, client_id, payload_sha256);
        Err(ThreadStoreError::Unsupported {
            operation: "queue_client_dispatch_lock",
        })
    }

    fn claim_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        queued_item_id: String,
        owner_id: String,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        let _ = (
            process_lock,
            queued_item_id,
            owner_id,
            now_ms,
            lease_expires_at_ms,
        );
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_dispatch_claim",
            })
        })
    }

    fn authorize_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchLease> {
        let _ = (process_lock, lease, now_ms, lease_expires_at_ms);
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_dispatch_authorize",
            })
        })
    }

    fn recover_expired_client_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        expired: QueuedClientExpiredDispatch,
        new_owner_id: String,
        observed_turn_id: Option<String>,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        let _ = (
            process_lock,
            expired,
            new_owner_id,
            observed_turn_id,
            now_ms,
            lease_expires_at_ms,
        );
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_dispatch_recover",
            })
        })
    }

    fn complete_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: &'a QueuedClientDispatchLease,
        turn_id: String,
    ) -> ThreadStoreFuture<'a, ()> {
        let _ = (process_lock, lease, turn_id);
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_dispatch_complete",
            })
        })
    }

    fn release_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
    ) -> ThreadStoreFuture<'a, ()> {
        let _ = (process_lock, lease);
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "queue_client_dispatch_release",
            })
        })
    }

    fn list_page(
        &self,
        thread_id: ThreadId,
        offset: usize,
        limit: usize,
    ) -> ThreadStoreFuture<'_, Vec<QueuedUserSubmissionRecord>>;

    fn update(
        &self,
        thread_id: ThreadId,
        item_id: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, Option<QueuedUserSubmissionRecord>>;

    fn delete(&self, thread_id: ThreadId, item_id: String) -> ThreadStoreFuture<'_, bool>;

    /// Atomically replace queue order with every current item ID exactly once.
    ///
    /// Returns [`ThreadStoreError::InvalidRequest`] when `item_ids` is not a
    /// permutation of the complete queue.
    fn reorder(&self, thread_id: ThreadId, item_ids: Vec<String>) -> ThreadStoreFuture<'_, ()>;
}

/// Adapts the local state runtime to the shared queue-storage interface.
#[derive(Clone)]
pub struct LocalQueueStore {
    state_db: StateDbHandle,
    runtime_capacity: Option<NonZeroUsize>,
}

impl LocalQueueStore {
    /// Create the ordinary Codex adapter with only the historical per-thread
    /// capacity enforced by the storage layer.
    pub fn new(state_db: StateDbHandle) -> Self {
        Self {
            state_db,
            runtime_capacity: None,
        }
    }

    /// Bind this adapter to the capacity of its owning runtime.
    ///
    /// The capacity applies to all pending rows in this state database. The
    /// storage layer separately retains the built-in per-thread limit.
    pub fn with_capacity(state_db: StateDbHandle, capacity: NonZeroUsize) -> Self {
        Self {
            state_db,
            runtime_capacity: Some(capacity),
        }
    }

    fn queue(&self) -> &SqliteQueueStore {
        self.state_db.thread_queue()
    }
}

fn queue_future<'a, T, E>(
    future: impl Future<Output = Result<T, E>> + Send + 'a,
) -> ThreadStoreFuture<'a, T>
where
    T: Send + 'a,
    E: Display + Send + 'a,
{
    Box::pin(async move {
        future.await.map_err(|error| ThreadStoreError::Internal {
            message: format!("queue storage failed: {error}"),
        })
    })
}

impl QueueStore for LocalQueueStore {
    fn change_version(&self) -> ThreadStoreFuture<'_, i64> {
        queue_future(self.queue().change_version())
    }

    fn changes_since<'a>(
        &'a self,
        revision: i64,
        thread_ids: &'a [ThreadId],
    ) -> ThreadStoreFuture<'a, Vec<(ThreadId, i64)>> {
        queue_future(self.queue().changes_since(revision, thread_ids))
    }

    fn enqueue(
        &self,
        thread_id: ThreadId,
        payload: String,
    ) -> ThreadStoreFuture<'_, QueuedUserSubmissionRecord> {
        Box::pin(async move {
            let result = match self.runtime_capacity {
                Some(capacity) => {
                    self.queue()
                        .enqueue_with_capacity(thread_id, &payload, capacity.get())
                        .await
                }
                None => self.queue().enqueue(thread_id, &payload).await,
            };
            result.map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn enqueue_guarded(
        &self,
        thread_id: ThreadId,
        payload: String,
        client_id: String,
        payload_sha256: String,
    ) -> ThreadStoreFuture<'_, QueuedUserSubmissionRecord> {
        Box::pin(async move {
            self.queue()
                .enqueue_guarded(
                    thread_id,
                    &payload,
                    &client_id,
                    &payload_sha256,
                    self.runtime_capacity.map(NonZeroUsize::get),
                )
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn reserve_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, QueuedClientBindingReserveOutcome> {
        Box::pin(async move {
            self.queue()
                .reserve_client_binding(thread_id, &client_id, &payload_sha256, &payload)
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn finalize_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        payload: String,
        lease: QueuedClientBindingLease,
        mode: QueuedClientBindingFinalizeMode,
        observed_turn_id: Option<String>,
    ) -> ThreadStoreFuture<'_, QueuedClientBindingFinalizeOutcome> {
        Box::pin(async move {
            self.queue()
                .finalize_client_binding(QueuedClientBindingFinalizeRequest {
                    thread_id,
                    client_id,
                    payload_sha256,
                    payload_json: payload,
                    lease,
                    mode,
                    observed_turn_id,
                    runtime_capacity: self.runtime_capacity.map(NonZeroUsize::get),
                })
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn mark_client_binding_persisted(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
        queued_item_id: String,
        turn_id: String,
    ) -> ThreadStoreFuture<'_, bool> {
        Box::pin(async move {
            self.queue()
                .mark_client_binding_persisted(
                    thread_id,
                    &client_id,
                    &payload_sha256,
                    &queued_item_id,
                    &turn_id,
                )
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn try_acquire_client_dispatch_lock(
        &self,
        thread_id: ThreadId,
        client_id: String,
        payload_sha256: String,
    ) -> Result<Option<QueuedClientDispatchLock>, ThreadStoreError> {
        self.queue()
            .try_acquire_client_dispatch_lock(thread_id, &client_id, &payload_sha256)
            .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
    }

    fn claim_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        queued_item_id: String,
        owner_id: String,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        Box::pin(async move {
            self.queue()
                .claim_client_binding_dispatch(
                    process_lock,
                    &queued_item_id,
                    &owner_id,
                    now_ms,
                    lease_expires_at_ms,
                )
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn authorize_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchLease> {
        Box::pin(async move {
            self.queue()
                .authorize_client_binding_dispatch(
                    process_lock,
                    &lease,
                    now_ms,
                    lease_expires_at_ms,
                )
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn recover_expired_client_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        expired: QueuedClientExpiredDispatch,
        new_owner_id: String,
        observed_turn_id: Option<String>,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> ThreadStoreFuture<'a, QueuedClientDispatchClaimOutcome> {
        Box::pin(async move {
            self.queue()
                .recover_expired_client_dispatch(
                    process_lock,
                    &expired,
                    &new_owner_id,
                    observed_turn_id.as_deref(),
                    now_ms,
                    lease_expires_at_ms,
                )
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn complete_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: &'a QueuedClientDispatchLease,
        turn_id: String,
    ) -> ThreadStoreFuture<'a, ()> {
        Box::pin(async move {
            self.queue()
                .complete_client_binding_dispatch(process_lock, lease, &turn_id)
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn release_client_binding_dispatch<'a>(
        &'a self,
        process_lock: &'a QueuedClientDispatchLock,
        lease: QueuedClientDispatchLease,
    ) -> ThreadStoreFuture<'a, ()> {
        Box::pin(async move {
            self.queue()
                .release_client_binding_dispatch(process_lock, &lease)
                .await
                .map_err(|error| map_queue_write_error(error, self.runtime_capacity))
        })
    }

    fn list_page(
        &self,
        thread_id: ThreadId,
        offset: usize,
        limit: usize,
    ) -> ThreadStoreFuture<'_, Vec<QueuedUserSubmissionRecord>> {
        queue_future(self.queue().list_page(thread_id, offset, limit))
    }

    fn update(
        &self,
        thread_id: ThreadId,
        item_id: String,
        payload: String,
    ) -> ThreadStoreFuture<'_, Option<QueuedUserSubmissionRecord>> {
        queue_future(async move { self.queue().update(thread_id, &item_id, &payload).await })
    }

    fn delete(&self, thread_id: ThreadId, item_id: String) -> ThreadStoreFuture<'_, bool> {
        queue_future(async move { self.queue().delete(thread_id, &item_id).await })
    }

    fn reorder(&self, thread_id: ThreadId, item_ids: Vec<String>) -> ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            self.queue()
                .reorder(thread_id, &item_ids)
                .await
                .map_err(|error| match error.downcast_ref::<std::io::Error>() {
                    Some(error) if error.kind() == std::io::ErrorKind::InvalidInput => {
                        ThreadStoreError::InvalidRequest {
                            message: error.to_string(),
                        }
                    }
                    _ => ThreadStoreError::Internal {
                        message: format!("queue storage failed: {error}"),
                    },
                })
        })
    }
}

fn map_queue_write_error(
    error: anyhow::Error,
    runtime_capacity: Option<NonZeroUsize>,
) -> ThreadStoreError {
    if let Some(conflict) = error.downcast_ref::<QueuedClientBindingConflict>() {
        return ThreadStoreError::Conflict {
            message: conflict.message.clone(),
        };
    }
    if let Some(capacity_error) = error.downcast_ref::<QueueCapacityExceeded>() {
        return match capacity_error.limit {
            QueueCapacityLimit::Thread => ThreadStoreError::InvalidRequest {
                message: format!("queue cannot contain more than {MAX_QUEUE_ITEMS} submissions"),
            },
            QueueCapacityLimit::Runtime => match runtime_capacity {
                Some(capacity) => ThreadStoreError::InvalidRequest {
                    message: format!(
                        "runtime queue cannot contain more than {capacity} submission{}",
                        if capacity.get() == 1 { "" } else { "s" },
                    ),
                },
                None => ThreadStoreError::Internal {
                    message: format!(
                        "queue storage returned a runtime capacity error without a configured runtime capacity: {error}"
                    ),
                },
            },
        };
    }
    match error.downcast_ref::<sqlx::Error>() {
        Some(sqlx::Error::RowNotFound) => ThreadStoreError::InvalidRequest {
            message: format!("queue cannot contain more than {MAX_QUEUE_ITEMS} submissions"),
        },
        _ => ThreadStoreError::Internal {
            message: format!("queue storage failed: {error}"),
        },
    }
}
