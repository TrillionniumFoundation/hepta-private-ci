use super::*;
use crate::MAX_QUEUE_ITEMS;
use crate::QueuedClientBindingConflict;
use crate::QueuedClientBindingFinalizeMode;
use crate::QueuedClientBindingFinalizeOutcome;
use crate::QueuedClientBindingFinalizeRequest;
use crate::QueuedClientBindingLease;
use crate::QueuedClientBindingReserveOutcome;
use crate::QueuedClientBindingState;
use crate::QueuedClientDispatchClaimOutcome;
use crate::QueuedClientDispatchLease;
use crate::QueuedClientExpiredDispatch;
use crate::QueuedUserSubmissionRecord;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Connection;
use std::collections::HashSet;
use std::fs;
use std::fs::File;
#[cfg(not(unix))]
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex as StdMutex;
use std::sync::OnceLock;
use tokio::sync::Mutex;
use uuid::Uuid;

#[cfg(unix)]
use std::ffi::CString;
#[cfg(unix)]
use std::os::fd::AsRawFd;
#[cfg(unix)]
use std::os::fd::FromRawFd;
#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;

#[cfg(unix)]
const DISPATCH_LOCK_DIRECTORY_MODE: u32 = 0o700;
#[cfg(unix)]
const DISPATCH_LOCK_FILE_MODE: u32 = 0o600;

fn validate_thread_deletion_operation_rows(
    root_thread_id: ThreadId,
    rows: &[(String, i64, String)],
) -> anyhow::Result<Vec<String>> {
    let Some((first_member, first_ordinal, operation_id)) = rows.first() else {
        return Ok(Vec::new());
    };
    if first_member != &root_thread_id.to_string() || *first_ordinal != 0 {
        return Err(anyhow::anyhow!(
            "hard-delete operation journal for root {root_thread_id} does not begin with root ordinal zero"
        ));
    }
    for (expected_ordinal, (_, member_ordinal, member_operation_id)) in rows.iter().enumerate() {
        if *member_ordinal != i64::try_from(expected_ordinal)? {
            return Err(anyhow::anyhow!(
                "hard-delete operation journal for root {root_thread_id} has a non-contiguous member ordinal"
            ));
        }
        if member_operation_id != operation_id {
            return Err(anyhow::anyhow!(
                "hard-delete operation journal for root {root_thread_id} contains multiple operation identities"
            ));
        }
    }
    Ok(rows
        .iter()
        .map(|(member_thread_id, _, _)| member_thread_id.clone())
        .collect())
}

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
struct DispatchLockIdentity {
    device: i64,
    inode: i64,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct DispatchRegistryKey {
    directory: DispatchLockIdentity,
    file_name: String,
}

static ACTIVE_DISPATCH_LOCKS: OnceLock<StdMutex<HashSet<DispatchRegistryKey>>> = OnceLock::new();

/// Open directory authority retained for the full StateRuntime lifetime. On
/// Unix every per-binding file is opened relative to this fd, so a parent
/// symlink retarget or path replacement cannot redirect a live runtime.
#[derive(Debug)]
pub(crate) struct DispatchLockDirectory {
    path: PathBuf,
    identity: DispatchLockIdentity,
    #[cfg(unix)]
    _home_directory: File,
    #[cfg(unix)]
    directory: File,
}

/// Process-held proof that no live same-host owner is dispatching this exact
/// client-message binding. The kernel releases the file lock on process death;
/// the process registry also fences independent QueueService instances because
/// some file-lock implementations coalesce locks within one process.
#[derive(Debug)]
pub struct QueuedClientDispatchLock {
    thread_id: ThreadId,
    client_id: String,
    payload_sha256: String,
    registry_key: DispatchRegistryKey,
    lock_identity: DispatchLockIdentity,
    lock_nonce: String,
    file: Option<File>,
}

impl Drop for QueuedClientDispatchLock {
    fn drop(&mut self) {
        drop(self.file.take());
        ACTIVE_DISPATCH_LOCKS
            .get_or_init(|| StdMutex::new(HashSet::new()))
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(&self.registry_key);
    }
}

/// Capacity boundary that rejected a durable queue insert.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QueueCapacityLimit {
    Runtime,
    Thread,
}

/// Typed rejection returned only after the capacity check held the SQLite
/// writer lock, so callers can distinguish compatibility-facing thread limits
/// from embedding-runtime limits without parsing SQLite errors.
#[derive(Debug)]
pub struct QueueCapacityExceeded {
    pub limit: QueueCapacityLimit,
}

impl std::fmt::Display for QueueCapacityExceeded {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.limit {
            QueueCapacityLimit::Runtime => formatter.write_str("runtime queue capacity reached"),
            QueueCapacityLimit::Thread => formatter.write_str("thread queue capacity reached"),
        }
    }
}

impl std::error::Error for QueueCapacityExceeded {}

/// SQLite-backed persistence for durable, thread-scoped user messages.
#[derive(Clone)]
pub struct SqliteQueueStore {
    pool: Arc<SqlitePool>,
    change_version_connection: Arc<Mutex<Option<SqliteConnection>>>,
    dispatch_lock_directory: Arc<DispatchLockDirectory>,
}

impl SqliteQueueStore {
    pub(crate) fn new(
        pool: Arc<SqlitePool>,
        dispatch_lock_directory: DispatchLockDirectory,
    ) -> Self {
        Self {
            pool,
            change_version_connection: Arc::new(Mutex::new(None)),
            dispatch_lock_directory: Arc::new(dispatch_lock_directory),
        }
    }

    /// Try to acquire the crash-released same-host lock for one exact binding.
    /// Returning `None` is positive evidence that a live local owner still
    /// holds the binding; callers must not use SQLite lease expiry to bypass it.
    pub fn try_acquire_client_dispatch_lock(
        &self,
        thread_id: ThreadId,
        client_id: &str,
        payload_sha256: &str,
    ) -> anyhow::Result<Option<QueuedClientDispatchLock>> {
        validate_binding_identity(client_id, payload_sha256)?;
        let file_name = dispatch_lock_file_name(thread_id, client_id, payload_sha256);
        let registry_key = DispatchRegistryKey {
            directory: self.dispatch_lock_directory.identity,
            file_name: file_name.clone(),
        };
        {
            let mut active = ACTIVE_DISPATCH_LOCKS
                .get_or_init(|| StdMutex::new(HashSet::new()))
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if !active.insert(registry_key.clone()) {
                return Ok(None);
            }
        }

        let (file, lock_identity) = match open_secure_dispatch_lock(
            self.dispatch_lock_directory.as_ref(),
            std::ffi::OsStr::new(&file_name),
        ) {
            Ok(opened) => opened,
            Err(error) => {
                release_process_dispatch_reservation(&registry_key);
                return Err(error.into());
            }
        };
        match file.try_lock() {
            Ok(()) => Ok(Some(QueuedClientDispatchLock {
                thread_id,
                client_id: client_id.to_string(),
                payload_sha256: payload_sha256.to_string(),
                registry_key,
                lock_identity,
                lock_nonce: Uuid::now_v7().to_string(),
                file: Some(file),
            })),
            Err(std::fs::TryLockError::WouldBlock) => {
                release_process_dispatch_reservation(&registry_key);
                Ok(None)
            }
            Err(std::fs::TryLockError::Error(error)) => {
                release_process_dispatch_reservation(&registry_key);
                Err(anyhow::anyhow!(
                    "failed to acquire exact queue dispatch lock `{}`: {error}",
                    self.dispatch_lock_directory.path.join(file_name).display()
                ))
            }
        }
    }

    /// Bind this queue database to the exact directory inode used for kernel
    /// owner-death fencing. A replaced or independently resolved lock root is
    /// never adopted by an existing durable ledger.
    pub(crate) async fn bind_dispatch_lock_root(&self) -> anyhow::Result<()> {
        let identity = self.dispatch_lock_directory.identity;
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let existing = sqlx::query_as::<_, (i64, i64)>(
            "SELECT device, inode FROM queue_dispatch_lock_root WHERE singleton = 1",
        )
        .fetch_optional(transaction.as_mut())
        .await?;
        match existing {
            Some((device, inode)) if device == identity.device && inode == identity.inode => {}
            Some((device, inode)) => {
                return Err(binding_conflict(format!(
                    "queue dispatch lock root changed (expected {device}:{inode}, opened {}:{})",
                    identity.device, identity.inode
                )));
            }
            None => {
                sqlx::query(
                    "INSERT INTO queue_dispatch_lock_root (singleton, device, inode) VALUES (1, ?, ?)",
                )
                .bind(identity.device)
                .bind(identity.inode)
                .execute(transaction.as_mut())
                .await?;
            }
        }
        transaction.commit().await?;
        Ok(())
    }

    pub(crate) async fn close(&self) {
        let connection = self.change_version_connection.lock().await.take();
        if let Some(connection) = connection
            && let Err(error) = connection.close().await
        {
            tracing::warn!(%error, "failed to close queue change-version connection");
        }
        self.pool.close().await;
    }

    /// Observe queue-database commits through one stable SQLite connection.
    pub async fn change_version(&self) -> anyhow::Result<i64> {
        let mut connection = Arc::clone(&self.change_version_connection)
            .lock_owned()
            .await;
        if connection.is_none() {
            *connection = Some(self.pool.acquire().await?.detach());
        }
        let Some(connection) = connection.as_mut() else {
            unreachable!("queue change-version connection was initialized");
        };
        Ok(sqlx::query_scalar("PRAGMA data_version")
            .fetch_one(connection)
            .await?)
    }

    /// Return changed revisions only for the supplied loaded thread IDs.
    pub async fn changes_since(
        &self,
        revision: i64,
        thread_ids: &[ThreadId],
    ) -> anyhow::Result<Vec<(ThreadId, i64)>> {
        if thread_ids.is_empty() {
            return Ok(Vec::new());
        }

        let mut query = QueryBuilder::<Sqlite>::new(
            "SELECT thread_id, revision FROM queued_thread_revisions WHERE revision > ",
        );
        query.push_bind(revision).push(" AND thread_id IN (");
        let mut separated = query.separated(", ");
        for thread_id in thread_ids {
            separated.push_bind(thread_id.to_string());
        }
        separated.push_unseparated(") ORDER BY revision");
        let rows = query
            .build_query_as::<(String, i64)>()
            .fetch_all(self.pool.as_ref())
            .await?;
        rows.into_iter()
            .map(|(thread_id, revision)| Ok((ThreadId::try_from(thread_id)?, revision)))
            .collect()
    }

    /// Enqueue with the historical ordinary-Codex limit of
    /// [`MAX_QUEUE_ITEMS`] independently for each thread.
    pub async fn enqueue(
        &self,
        thread_id: ThreadId,
        payload_json: &str,
    ) -> anyhow::Result<QueuedUserSubmissionRecord> {
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        reject_raw_enqueue_for_existing_binding(
            transaction.as_mut(),
            &thread_id_string,
            payload_json,
        )
        .await?;
        enforce_capacity(
            transaction.as_mut(),
            &thread_id_string,
            /*runtime_capacity*/ None,
        )
        .await?;
        let record = insert_queued_record(
            transaction.as_mut(),
            thread_id,
            payload_json,
            &Uuid::now_v7().to_string(),
        )
        .await?;
        transaction.commit().await?;
        Ok(record)
    }

    /// Enqueue one item while atomically enforcing both the database-wide
    /// runtime capacity and the retained per-thread limit.
    ///
    /// The queue database is rooted in one Codex home. Hepta gives every
    /// workspace Agent its own Codex home, so the database-wide limit is also
    /// the per-Agent limit. `BEGIN IMMEDIATE` acquires the SQLite writer lock
    /// before either count is observed; competing processes cannot both admit
    /// against the same stale capacity snapshot.
    pub async fn enqueue_with_capacity(
        &self,
        thread_id: ThreadId,
        payload_json: &str,
        capacity: usize,
    ) -> anyhow::Result<QueuedUserSubmissionRecord> {
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        reject_raw_enqueue_for_existing_binding(
            transaction.as_mut(),
            &thread_id_string,
            payload_json,
        )
        .await?;
        enforce_capacity(transaction.as_mut(), &thread_id_string, Some(capacity)).await?;
        let record = insert_queued_record(
            transaction.as_mut(),
            thread_id,
            payload_json,
            &Uuid::now_v7().to_string(),
        )
        .await?;
        transaction.commit().await?;
        Ok(record)
    }

    /// Enqueue an ordinary queue request while honoring any exact admission
    /// binding already reserved for the same client-message id. This keeps the
    /// compatibility `queue/add` path from racing around `queue/reconcile`.
    pub async fn enqueue_guarded(
        &self,
        thread_id: ThreadId,
        payload_json: &str,
        client_id: &str,
        payload_sha256: &str,
        runtime_capacity: Option<usize>,
    ) -> anyhow::Result<QueuedUserSubmissionRecord> {
        validate_binding_identity(client_id, payload_sha256)?;
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        if let Some(binding) =
            load_binding(transaction.as_mut(), &thread_id_string, client_id).await?
        {
            ensure_binding_digest(client_id, payload_sha256, &binding.payload_sha256)?;
            let outcome = match binding.state {
                QueuedClientBindingState::Queued => {
                    let item_id = binding.queued_item_id.ok_or_else(|| {
                        anyhow::anyhow!("queued client binding is missing its queue row identity")
                    })?;
                    load_queued_record(transaction.as_mut(), &thread_id_string, &item_id)
                        .await?
                        .ok_or_else(|| {
                            anyhow::anyhow!(
                                "queued client binding `{client_id}` references a missing queue row"
                            )
                        })?
                }
                QueuedClientBindingState::Reserved => {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` has an admission reservation in progress"
                    )));
                }
                QueuedClientBindingState::Dispatching => {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` has a dispatch in progress"
                    )));
                }
                QueuedClientBindingState::Persisted => {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` is already persisted"
                    )));
                }
                QueuedClientBindingState::Cancelled => {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` was cancelled and cannot be re-enqueued"
                    )));
                }
            };
            transaction.commit().await?;
            return Ok(outcome);
        }

        enforce_capacity(transaction.as_mut(), &thread_id_string, runtime_capacity).await?;
        let record = insert_queued_record(
            transaction.as_mut(),
            thread_id,
            payload_json,
            &Uuid::now_v7().to_string(),
        )
        .await?;
        transaction.commit().await?;
        Ok(record)
    }

    /// Atomically reserve one `(thread, client id, digest)` identity before any
    /// rollout scan. Existing queue rows are inspected under the same SQLite
    /// writer transaction, so a conflicting row is rejected before a new row
    /// can be admitted and a same-payload compatibility row is adopted.
    pub async fn reserve_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: &str,
        payload_sha256: &str,
        payload_json: &str,
    ) -> anyhow::Result<QueuedClientBindingReserveOutcome> {
        validate_binding_identity(client_id, payload_sha256)?;
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        if let Some(binding) =
            load_binding(transaction.as_mut(), &thread_id_string, client_id).await?
        {
            ensure_binding_digest(client_id, payload_sha256, &binding.payload_sha256)?;
            let outcome =
                reserve_outcome_from_binding(transaction.as_mut(), thread_id, client_id, binding)
                    .await?;
            transaction.commit().await?;
            return Ok(outcome);
        }

        let rows: Vec<(String, String)> = sqlx::query_as(
            "SELECT id, payload_json FROM queued_items
             WHERE thread_id = ? ORDER BY queue_order",
        )
        .bind(&thread_id_string)
        .fetch_all(transaction.as_mut())
        .await?;
        let mut adopted_item_id = None;
        let mut duplicate_item_ids = Vec::new();
        for (item_id, existing_payload) in rows {
            if queued_payload_client_id(&existing_payload).as_deref() != Some(client_id) {
                continue;
            }
            if existing_payload != payload_json {
                return Err(binding_conflict(format!(
                    "client message id `{client_id}` is already queued with a different payload"
                )));
            }
            if adopted_item_id.is_none() {
                adopted_item_id = Some(item_id);
            } else {
                duplicate_item_ids.push(item_id);
            }
        }
        for item_id in duplicate_item_ids {
            sqlx::query("DELETE FROM queued_items WHERE thread_id = ? AND id = ?")
                .bind(&thread_id_string)
                .bind(item_id)
                .execute(transaction.as_mut())
                .await?;
        }

        let queued_item_id = adopted_item_id.unwrap_or_else(|| Uuid::now_v7().to_string());
        let reservation_id = Uuid::now_v7().to_string();
        let now_ms = datetime_to_epoch_millis(Utc::now());
        sqlx::query(
            "INSERT INTO queued_client_bindings (
                thread_id, client_user_message_id, payload_sha256, state,
                queued_item_id, turn_id, reservation_id, revision,
                created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, 'reserved', ?, NULL, ?, 1, ?, ?)",
        )
        .bind(&thread_id_string)
        .bind(client_id)
        .bind(payload_sha256)
        .bind(&queued_item_id)
        .bind(&reservation_id)
        .bind(now_ms)
        .bind(now_ms)
        .execute(transaction.as_mut())
        .await?;
        transaction.commit().await?;
        Ok(QueuedClientBindingReserveOutcome::Reserved(
            QueuedClientBindingLease {
                reservation_id,
                revision: 1,
                queued_item_id,
            },
        ))
    }

    /// Atomically fence a queued exact binding for one dispatch owner. The
    /// process lock is mandatory: SQLite expiry is recovery metadata, not proof
    /// that the previous owner is dead.
    pub async fn claim_client_binding_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        queued_item_id: &str,
        owner_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> anyhow::Result<QueuedClientDispatchClaimOutcome> {
        ensure_dispatch_lock_identity(
            process_lock,
            process_lock.thread_id,
            &process_lock.client_id,
            &process_lock.payload_sha256,
        )?;
        validate_dispatch_window(owner_id, now_ms, lease_expires_at_ms)?;
        let thread_id = process_lock.thread_id;
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let Some(binding) = load_binding(
            transaction.as_mut(),
            &thread_id_string,
            &process_lock.client_id,
        )
        .await?
        else {
            let outcome =
                if load_queued_record(transaction.as_mut(), &thread_id_string, queued_item_id)
                    .await?
                    .is_some()
                {
                    QueuedClientDispatchClaimOutcome::Unbound
                } else {
                    QueuedClientDispatchClaimOutcome::Missing
                };
            transaction.commit().await?;
            return Ok(outcome);
        };
        ensure_binding_digest(
            &process_lock.client_id,
            &process_lock.payload_sha256,
            &binding.payload_sha256,
        )?;
        match binding.state {
            QueuedClientBindingState::Queued => {
                ensure_binding_lock_identity(&binding, process_lock, /*may_initialize*/ true)?;
                if binding.queued_item_id.as_deref() != Some(queued_item_id) {
                    return Err(binding_conflict(format!(
                        "client message id `{}` is bound to another queue row",
                        process_lock.client_id
                    )));
                }
                if load_queued_record(transaction.as_mut(), &thread_id_string, queued_item_id)
                    .await?
                    .is_none()
                {
                    return Err(binding_conflict(format!(
                        "client message id `{}` references a missing queue row",
                        process_lock.client_id
                    )));
                }
                let revision = binding.revision + 1;
                let changed = sqlx::query(
                    "UPDATE queued_client_bindings
                     SET state = 'dispatching', dispatch_owner_id = ?,
                         dispatch_lease_expires_at_ms = ?, dispatch_lock_device = ?,
                         dispatch_lock_inode = ?, revision = ?, updated_at_ms = ?
                     WHERE thread_id = ? AND client_user_message_id = ?
                       AND payload_sha256 = ? AND queued_item_id = ?
                       AND state = 'queued' AND revision = ?",
                )
                .bind(owner_id)
                .bind(lease_expires_at_ms)
                .bind(process_lock.lock_identity.device)
                .bind(process_lock.lock_identity.inode)
                .bind(revision)
                .bind(datetime_to_epoch_millis(Utc::now()))
                .bind(&thread_id_string)
                .bind(&process_lock.client_id)
                .bind(&process_lock.payload_sha256)
                .bind(queued_item_id)
                .bind(binding.revision)
                .execute(transaction.as_mut())
                .await?
                .rows_affected();
                if changed != 1 {
                    return Err(binding_conflict(format!(
                        "client message id `{}` changed before dispatch claim",
                        process_lock.client_id
                    )));
                }
                transaction.commit().await?;
                Ok(QueuedClientDispatchClaimOutcome::Acquired(dispatch_lease(
                    process_lock,
                    queued_item_id,
                    owner_id,
                    revision,
                    lease_expires_at_ms,
                )))
            }
            QueuedClientBindingState::Dispatching => {
                ensure_binding_lock_identity(
                    &binding,
                    process_lock,
                    /*may_initialize*/ false,
                )?;
                if binding.queued_item_id.as_deref() != Some(queued_item_id) {
                    return Err(binding_conflict(format!(
                        "client message id `{}` dispatch references another queue row",
                        process_lock.client_id
                    )));
                }
                let dispatch_owner_id = binding.dispatch_owner_id.ok_or_else(|| {
                    anyhow::anyhow!("dispatching client binding is missing its owner")
                })?;
                let dispatch_lease_expires_at_ms =
                    binding.dispatch_lease_expires_at_ms.ok_or_else(|| {
                        anyhow::anyhow!("dispatching client binding is missing its lease expiry")
                    })?;
                transaction.commit().await?;
                if dispatch_lease_expires_at_ms > now_ms {
                    return Ok(QueuedClientDispatchClaimOutcome::InFlight {
                        owner_id: dispatch_owner_id,
                        revision: binding.revision,
                        lease_expires_at_ms: dispatch_lease_expires_at_ms,
                    });
                }
                Ok(QueuedClientDispatchClaimOutcome::Expired(
                    QueuedClientExpiredDispatch {
                        thread_id,
                        client_id: process_lock.client_id.clone(),
                        payload_sha256: process_lock.payload_sha256.clone(),
                        queued_item_id: queued_item_id.to_string(),
                        previous_owner_id: dispatch_owner_id,
                        revision: binding.revision,
                        lease_expires_at_ms: dispatch_lease_expires_at_ms,
                        lock_nonce: process_lock.lock_nonce.clone(),
                        lock_device: process_lock.lock_identity.device,
                        lock_inode: process_lock.lock_identity.inode,
                    },
                ))
            }
            QueuedClientBindingState::Persisted => {
                let turn_id = binding.turn_id.ok_or_else(|| {
                    anyhow::anyhow!("persisted client binding is missing its turn identity")
                })?;
                transaction.commit().await?;
                Ok(QueuedClientDispatchClaimOutcome::Persisted { turn_id })
            }
            QueuedClientBindingState::Cancelled => {
                transaction.commit().await?;
                Ok(QueuedClientDispatchClaimOutcome::Cancelled)
            }
            QueuedClientBindingState::Reserved => Err(binding_conflict(format!(
                "client message id `{}` is still reserved and cannot dispatch",
                process_lock.client_id
            ))),
        }
    }

    /// Renew and re-CAS the exact owner immediately before Core submission.
    pub async fn authorize_client_binding_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        lease: &QueuedClientDispatchLease,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> anyhow::Result<QueuedClientDispatchLease> {
        ensure_dispatch_lease_lock(process_lock, lease)?;
        validate_dispatch_window(&lease.owner_id, now_ms, lease_expires_at_ms)?;
        let thread_id_string = lease.thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let revision = lease.revision + 1;
        let changed = sqlx::query(
            "UPDATE queued_client_bindings
             SET dispatch_lease_expires_at_ms = ?, revision = ?, updated_at_ms = ?
             WHERE thread_id = ? AND client_user_message_id = ?
               AND payload_sha256 = ? AND queued_item_id = ?
               AND state = 'dispatching' AND dispatch_owner_id = ?
               AND dispatch_lock_device = ? AND dispatch_lock_inode = ?
               AND revision = ? AND dispatch_lease_expires_at_ms > ?",
        )
        .bind(lease_expires_at_ms)
        .bind(revision)
        .bind(datetime_to_epoch_millis(Utc::now()))
        .bind(&thread_id_string)
        .bind(&lease.client_id)
        .bind(&lease.payload_sha256)
        .bind(&lease.queued_item_id)
        .bind(&lease.owner_id)
        .bind(lease.lock_device)
        .bind(lease.lock_inode)
        .bind(lease.revision)
        .bind(now_ms)
        .execute(transaction.as_mut())
        .await?
        .rows_affected();
        if changed != 1 {
            return Err(binding_conflict(format!(
                "client message id `{}` dispatch owner or revision changed before submit",
                lease.client_id
            )));
        }
        transaction.commit().await?;
        Ok(QueuedClientDispatchLease {
            thread_id: lease.thread_id,
            client_id: lease.client_id.clone(),
            payload_sha256: lease.payload_sha256.clone(),
            queued_item_id: lease.queued_item_id.clone(),
            owner_id: lease.owner_id.clone(),
            revision,
            lease_expires_at_ms,
            lock_nonce: lease.lock_nonce.clone(),
            lock_device: lease.lock_device,
            lock_inode: lease.lock_inode,
        })
    }

    /// Recover an expired dispatch only after the exact rollout was scanned.
    /// The process lock proves the previous local owner released or died. A
    /// matching persisted turn closes the row; absence grants a newly fenced
    /// attempt to the caller.
    pub async fn recover_expired_client_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        expired: &QueuedClientExpiredDispatch,
        new_owner_id: &str,
        observed_turn_id: Option<&str>,
        now_ms: i64,
        lease_expires_at_ms: i64,
    ) -> anyhow::Result<QueuedClientDispatchClaimOutcome> {
        ensure_expired_dispatch_lock(process_lock, expired)?;
        validate_dispatch_window(new_owner_id, now_ms, lease_expires_at_ms)?;
        if expired.lease_expires_at_ms > now_ms {
            return Err(binding_conflict(format!(
                "client message id `{}` dispatch lease has not expired",
                expired.client_id
            )));
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(
            transaction.as_mut(),
            &expired.thread_id.to_string(),
        )
        .await?;
        if let Some(turn_id) = observed_turn_id {
            validate_turn_id(turn_id)?;
            let changed = transition_dispatch_binding_to_persisted(
                transaction.as_mut(),
                expired,
                turn_id,
                now_ms,
            )
            .await?;
            if !changed {
                return Err(binding_conflict(format!(
                    "client message id `{}` expired dispatch changed during recovery",
                    expired.client_id
                )));
            }
            delete_exact_dispatch_row(
                transaction.as_mut(),
                &expired.thread_id.to_string(),
                &expired.queued_item_id,
                &expired.client_id,
            )
            .await?;
            transaction.commit().await?;
            return Ok(QueuedClientDispatchClaimOutcome::Persisted {
                turn_id: turn_id.to_string(),
            });
        }

        let revision = expired.revision + 1;
        let changed = sqlx::query(
            "UPDATE queued_client_bindings
             SET dispatch_owner_id = ?, dispatch_lease_expires_at_ms = ?,
                 revision = ?, updated_at_ms = ?
             WHERE thread_id = ? AND client_user_message_id = ?
               AND payload_sha256 = ? AND queued_item_id = ?
               AND state = 'dispatching' AND dispatch_owner_id = ?
               AND dispatch_lock_device = ? AND dispatch_lock_inode = ?
               AND revision = ? AND dispatch_lease_expires_at_ms <= ?",
        )
        .bind(new_owner_id)
        .bind(lease_expires_at_ms)
        .bind(revision)
        .bind(datetime_to_epoch_millis(Utc::now()))
        .bind(expired.thread_id.to_string())
        .bind(&expired.client_id)
        .bind(&expired.payload_sha256)
        .bind(&expired.queued_item_id)
        .bind(&expired.previous_owner_id)
        .bind(expired.lock_device)
        .bind(expired.lock_inode)
        .bind(expired.revision)
        .bind(now_ms)
        .execute(transaction.as_mut())
        .await?
        .rows_affected();
        if changed != 1 {
            return Err(binding_conflict(format!(
                "client message id `{}` expired dispatch changed before takeover",
                expired.client_id
            )));
        }
        transaction.commit().await?;
        Ok(QueuedClientDispatchClaimOutcome::Acquired(dispatch_lease(
            process_lock,
            &expired.queued_item_id,
            new_owner_id,
            revision,
            lease_expires_at_ms,
        )))
    }

    /// Commit Core's persisted admission and queue deletion in one owner-CAS
    /// transaction. A stale owner can neither complete nor delete the row.
    pub async fn complete_client_binding_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        lease: &QueuedClientDispatchLease,
        turn_id: &str,
    ) -> anyhow::Result<()> {
        ensure_dispatch_lease_lock(process_lock, lease)?;
        validate_turn_id(turn_id)?;
        let thread_id_string = lease.thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let changed =
            transition_dispatch_lease_to_persisted(transaction.as_mut(), lease, turn_id).await?;
        if !changed {
            return Err(binding_conflict(format!(
                "client message id `{}` dispatch owner or revision changed before completion",
                lease.client_id
            )));
        }
        delete_exact_dispatch_row(
            transaction.as_mut(),
            &thread_id_string,
            &lease.queued_item_id,
            &lease.client_id,
        )
        .await?;
        transaction.commit().await?;
        Ok(())
    }

    /// Return an unsubmitted owner attempt to `queued`. This is also fenced by
    /// owner and revision so an old owner cannot release a successor's attempt.
    pub async fn release_client_binding_dispatch(
        &self,
        process_lock: &QueuedClientDispatchLock,
        lease: &QueuedClientDispatchLease,
    ) -> anyhow::Result<()> {
        ensure_dispatch_lease_lock(process_lock, lease)?;
        let thread_id_string = lease.thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let changed = sqlx::query(
            "UPDATE queued_client_bindings
             SET state = 'queued', dispatch_owner_id = NULL,
                 dispatch_lease_expires_at_ms = NULL,
                 revision = revision + 1, updated_at_ms = ?
             WHERE thread_id = ? AND client_user_message_id = ?
               AND payload_sha256 = ? AND queued_item_id = ?
               AND state = 'dispatching' AND dispatch_owner_id = ?
               AND dispatch_lock_device = ? AND dispatch_lock_inode = ? AND revision = ?",
        )
        .bind(datetime_to_epoch_millis(Utc::now()))
        .bind(&thread_id_string)
        .bind(&lease.client_id)
        .bind(&lease.payload_sha256)
        .bind(&lease.queued_item_id)
        .bind(&lease.owner_id)
        .bind(lease.lock_device)
        .bind(lease.lock_inode)
        .bind(lease.revision)
        .execute(transaction.as_mut())
        .await?
        .rows_affected();
        if changed != 1 {
            return Err(binding_conflict(format!(
                "client message id `{}` dispatch owner or revision changed before release",
                lease.client_id
            )));
        }
        transaction.commit().await?;
        Ok(())
    }

    /// Finish a reservation after the caller has scanned the exact rollout.
    /// The queue insert and binding transition share one SQLite transaction.
    pub async fn finalize_client_binding(
        &self,
        request: QueuedClientBindingFinalizeRequest,
    ) -> anyhow::Result<QueuedClientBindingFinalizeOutcome> {
        let QueuedClientBindingFinalizeRequest {
            thread_id,
            client_id,
            payload_sha256,
            payload_json,
            lease,
            mode,
            observed_turn_id,
            runtime_capacity,
        } = request;
        validate_binding_identity(&client_id, &payload_sha256)?;
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let Some(binding) =
            load_binding(transaction.as_mut(), &thread_id_string, &client_id).await?
        else {
            transaction.commit().await?;
            return Ok(QueuedClientBindingFinalizeOutcome::Missing);
        };
        ensure_binding_digest(&client_id, &payload_sha256, &binding.payload_sha256)?;
        if binding.state == QueuedClientBindingState::Dispatching {
            return Err(binding_conflict(format!(
                "client message id `{client_id}` is owned by an active dispatch"
            )));
        }

        if let Some(turn_id) = observed_turn_id.as_deref() {
            if turn_id.is_empty() {
                return Err(binding_conflict(
                    "persisted turn identity cannot be empty".to_string(),
                ));
            }
            if binding.state == QueuedClientBindingState::Persisted {
                if binding.turn_id.as_deref() != Some(turn_id) {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` is already bound to another turn"
                    )));
                }
                transaction.commit().await?;
                return Ok(QueuedClientBindingFinalizeOutcome::Persisted {
                    turn_id: turn_id.to_string(),
                });
            }
            if let Some(queued_item_id) = binding.queued_item_id.as_deref() {
                sqlx::query("DELETE FROM queued_items WHERE thread_id = ? AND id = ?")
                    .bind(&thread_id_string)
                    .bind(queued_item_id)
                    .execute(transaction.as_mut())
                    .await?;
            }
            transition_binding_to_persisted(
                transaction.as_mut(),
                &thread_id_string,
                &client_id,
                &payload_sha256,
                turn_id,
            )
            .await?;
            transaction.commit().await?;
            return Ok(QueuedClientBindingFinalizeOutcome::Persisted {
                turn_id: turn_id.to_string(),
            });
        }

        match binding.state {
            QueuedClientBindingState::Queued => {
                let item_id = binding.queued_item_id.ok_or_else(|| {
                    anyhow::anyhow!("queued client binding is missing its queue row identity")
                })?;
                let record = load_queued_record(transaction.as_mut(), &thread_id_string, &item_id)
                    .await?
                    .ok_or_else(|| {
                        anyhow::anyhow!("queued client binding references a missing row")
                    })?;
                transaction.commit().await?;
                return Ok(QueuedClientBindingFinalizeOutcome::Queued {
                    record,
                    created: false,
                });
            }
            QueuedClientBindingState::Persisted => {
                let turn_id = binding.turn_id.ok_or_else(|| {
                    anyhow::anyhow!("persisted client binding is missing its turn identity")
                })?;
                transaction.commit().await?;
                return Ok(QueuedClientBindingFinalizeOutcome::Persisted { turn_id });
            }
            QueuedClientBindingState::Cancelled => {
                transaction.commit().await?;
                return Ok(QueuedClientBindingFinalizeOutcome::Cancelled);
            }
            QueuedClientBindingState::Dispatching => unreachable!("checked above"),
            QueuedClientBindingState::Reserved => {}
        }

        if binding.reservation_id != lease.reservation_id
            || binding.revision != lease.revision
            || binding.queued_item_id.as_deref() != Some(lease.queued_item_id.as_str())
        {
            return Err(binding_conflict(format!(
                "client message id `{client_id}` reservation changed before finalization"
            )));
        }

        if let Some(record) = load_queued_record(
            transaction.as_mut(),
            &thread_id_string,
            &lease.queued_item_id,
        )
        .await?
        {
            sqlx::query(
                "UPDATE queued_client_bindings
                 SET state = 'queued', revision = revision + 1, updated_at_ms = ?
                 WHERE thread_id = ? AND client_user_message_id = ?",
            )
            .bind(datetime_to_epoch_millis(Utc::now()))
            .bind(&thread_id_string)
            .bind(&client_id)
            .execute(transaction.as_mut())
            .await?;
            transaction.commit().await?;
            return Ok(QueuedClientBindingFinalizeOutcome::Queued {
                record,
                created: false,
            });
        }

        if mode == QueuedClientBindingFinalizeMode::ReconcileOnly {
            sqlx::query(
                "DELETE FROM queued_client_bindings
                 WHERE thread_id = ? AND client_user_message_id = ?
                   AND state = 'reserved' AND reservation_id = ? AND revision = ?",
            )
            .bind(&thread_id_string)
            .bind(&client_id)
            .bind(&lease.reservation_id)
            .bind(lease.revision)
            .execute(transaction.as_mut())
            .await?;
            transaction.commit().await?;
            return Ok(QueuedClientBindingFinalizeOutcome::Missing);
        }

        enforce_capacity(transaction.as_mut(), &thread_id_string, runtime_capacity).await?;
        let record = insert_queued_record(
            transaction.as_mut(),
            thread_id,
            &payload_json,
            &lease.queued_item_id,
        )
        .await?;
        sqlx::query(
            "UPDATE queued_client_bindings
             SET state = 'queued', revision = revision + 1, updated_at_ms = ?
             WHERE thread_id = ? AND client_user_message_id = ?
               AND state = 'reserved' AND reservation_id = ? AND revision = ?",
        )
        .bind(datetime_to_epoch_millis(Utc::now()))
        .bind(&thread_id_string)
        .bind(&client_id)
        .bind(&lease.reservation_id)
        .bind(lease.revision)
        .execute(transaction.as_mut())
        .await?;
        transaction.commit().await?;
        Ok(QueuedClientBindingFinalizeOutcome::Queued {
            record,
            created: true,
        })
    }

    /// Atomically make Core's persisted turn the durable authority and remove
    /// the corresponding queue row. This closes the normal dispatch boundary;
    /// a crash before this call is recovered by a subsequent rollout scan.
    pub async fn mark_client_binding_persisted(
        &self,
        thread_id: ThreadId,
        client_id: &str,
        payload_sha256: &str,
        queued_item_id: &str,
        turn_id: &str,
    ) -> anyhow::Result<bool> {
        validate_binding_identity(client_id, payload_sha256)?;
        if turn_id.is_empty() {
            return Err(binding_conflict(
                "persisted turn identity cannot be empty".to_string(),
            ));
        }
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let Some(binding) =
            load_binding(transaction.as_mut(), &thread_id_string, client_id).await?
        else {
            transaction.commit().await?;
            return Ok(false);
        };
        ensure_binding_digest(client_id, payload_sha256, &binding.payload_sha256)?;
        match binding.state {
            QueuedClientBindingState::Persisted => {
                if binding.turn_id.as_deref() != Some(turn_id) {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` is already bound to another turn"
                    )));
                }
                transaction.commit().await?;
                return Ok(true);
            }
            // Exact rollout persistence is stronger recovery evidence than a
            // queue tombstone. This can occur only when cancellation races a
            // Core admission that already crossed its durable boundary.
            QueuedClientBindingState::Cancelled => {}
            QueuedClientBindingState::Dispatching => {
                return Err(binding_conflict(format!(
                    "client message id `{client_id}` is owned by an active dispatch"
                )));
            }
            QueuedClientBindingState::Reserved | QueuedClientBindingState::Queued => {
                if binding.queued_item_id.as_deref() != Some(queued_item_id) {
                    return Err(binding_conflict(format!(
                        "client message id `{client_id}` is bound to another queue row"
                    )));
                }
            }
        }
        sqlx::query("DELETE FROM queued_items WHERE thread_id = ? AND id = ?")
            .bind(&thread_id_string)
            .bind(queued_item_id)
            .execute(transaction.as_mut())
            .await?;
        transition_binding_to_persisted(
            transaction.as_mut(),
            &thread_id_string,
            client_id,
            payload_sha256,
            turn_id,
        )
        .await?;
        transaction.commit().await?;
        Ok(true)
    }

    pub async fn list_page(
        &self,
        thread_id: ThreadId,
        offset: usize,
        limit: usize,
    ) -> anyhow::Result<Vec<QueuedUserSubmissionRecord>> {
        let rows = sqlx::query(
            "SELECT id, thread_id, payload_json
             FROM queued_items
             WHERE thread_id = ?
             ORDER BY queue_order LIMIT ? OFFSET ?",
        )
        .bind(thread_id.to_string())
        .bind(i64::try_from(limit)?)
        .bind(i64::try_from(offset)?)
        .fetch_all(self.pool.as_ref())
        .await?;
        rows.iter()
            .map(QueuedUserSubmissionRecord::try_from_row)
            .collect()
    }

    pub async fn update(
        &self,
        thread_id: ThreadId,
        item_id: &str,
        payload_json: &str,
    ) -> anyhow::Result<Option<QueuedUserSubmissionRecord>> {
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let exact_binding = sqlx::query_scalar::<_, String>(
            "SELECT client_user_message_id FROM queued_client_bindings
             WHERE thread_id = ? AND queued_item_id = ?",
        )
        .bind(&thread_id_string)
        .bind(item_id)
        .fetch_optional(transaction.as_mut())
        .await?;
        if let Some(client_id) = exact_binding {
            return Err(binding_conflict(format!(
                "queued submission `{item_id}` is sealed by exact client message id `{client_id}`"
            )));
        }
        reject_raw_enqueue_for_existing_binding(
            transaction.as_mut(),
            &thread_id_string,
            payload_json,
        )
        .await?;
        let row = sqlx::query(
            "UPDATE queued_items
             SET payload_json = ?, updated_at_ms = ?
             WHERE thread_id = ? AND id = ?
             RETURNING id, thread_id, payload_json",
        )
        .bind(payload_json)
        .bind(datetime_to_epoch_millis(Utc::now()))
        .bind(&thread_id_string)
        .bind(item_id)
        .fetch_optional(transaction.as_mut())
        .await?;
        let record = row
            .as_ref()
            .map(QueuedUserSubmissionRecord::try_from_row)
            .transpose()?;
        transaction.commit().await?;
        Ok(record)
    }

    pub async fn delete(&self, thread_id: ThreadId, item_id: &str) -> anyhow::Result<bool> {
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let binding = sqlx::query_as::<_, (String, String)>(
            "SELECT client_user_message_id, state FROM queued_client_bindings
             WHERE thread_id = ? AND queued_item_id = ?",
        )
        .bind(&thread_id_string)
        .bind(item_id)
        .fetch_optional(transaction.as_mut())
        .await?;
        if let Some((client_id, state)) = binding.as_ref()
            && QueuedClientBindingState::parse(state)? == QueuedClientBindingState::Dispatching
        {
            return Err(binding_conflict(format!(
                "client message id `{client_id}` is being submitted and cannot be cancelled"
            )));
        }
        let deleted = sqlx::query("DELETE FROM queued_items WHERE thread_id = ? AND id = ?")
            .bind(&thread_id_string)
            .bind(item_id)
            .execute(transaction.as_mut())
            .await?
            .rows_affected()
            > 0;
        if deleted && let Some((client_id, _)) = binding {
            sqlx::query(
                "UPDATE queued_client_bindings
                 SET state = 'cancelled', queued_item_id = NULL, turn_id = NULL,
                     dispatch_owner_id = NULL, dispatch_lease_expires_at_ms = NULL,
                     dispatch_lock_device = NULL, dispatch_lock_inode = NULL,
                     revision = revision + 1, updated_at_ms = ?
                 WHERE thread_id = ? AND client_user_message_id = ?",
            )
            .bind(datetime_to_epoch_millis(Utc::now()))
            .bind(&thread_id_string)
            .bind(client_id)
            .execute(transaction.as_mut())
            .await?;
        }
        transaction.commit().await?;
        Ok(deleted)
    }

    pub async fn reorder(&self, thread_id: ThreadId, ordered_ids: &[String]) -> anyhow::Result<()> {
        let thread_id_string = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        ensure_thread_queue_not_deletion_fenced(transaction.as_mut(), &thread_id_string).await?;
        let rows: Vec<(String, i64)> = sqlx::query_as(
            "SELECT id, queue_order FROM queued_items
             WHERE thread_id = ? ORDER BY queue_order",
        )
        .bind(&thread_id_string)
        .fetch_all(transaction.as_mut())
        .await?;
        let mut expected_ids = rows.iter().map(|(id, _)| id.clone()).collect::<Vec<_>>();
        let mut requested_ids = ordered_ids.to_vec();
        expected_ids.sort();
        requested_ids.sort();
        if expected_ids != requested_ids {
            transaction.rollback().await?;
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "queue reorder must include every queued submission exactly once",
            )
            .into());
        }
        let now_ms = datetime_to_epoch_millis(Utc::now());
        let max_queue_order = rows.last().map_or(-1, |(_, queue_order)| *queue_order);
        for (index, item_id) in ordered_ids.iter().enumerate() {
            sqlx::query(
                "UPDATE queued_items SET queue_order = ?, updated_at_ms = ?
                 WHERE thread_id = ? AND id = ?",
            )
            .bind(max_queue_order + i64::try_from(index)? + 1)
            .bind(now_ms)
            .bind(&thread_id_string)
            .bind(item_id)
            .execute(transaction.as_mut())
            .await?;
        }
        transaction.commit().await?;
        Ok(())
    }

    /// Atomically seal a whole spawned subtree against every future queue
    /// mutation. The tombstones are permanent: if a later thread-store delete
    /// fails, retry remains possible but queue work can never resurrect across
    /// the partially completed cross-store delete.
    pub async fn seal_thread_queues_for_deletion(
        &self,
        thread_ids: &[ThreadId],
    ) -> anyhow::Result<()> {
        let Some(&root_thread_id) = thread_ids.first() else {
            return Ok(());
        };
        self.seal_thread_subtree_for_deletion(root_thread_id, thread_ids)
            .await
    }

    /// Atomically journal and seal one exact hard-delete closure.
    ///
    /// Retrying the same root with a different ordered member set fails closed. Members already
    /// sealed by another operation retain their original tombstone identity while still joining
    /// this operation journal, so overlap cannot make fresh-process recovery omit a descendant.
    pub async fn seal_thread_subtree_for_deletion(
        &self,
        root_thread_id: ThreadId,
        thread_ids: &[ThreadId],
    ) -> anyhow::Result<()> {
        if thread_ids.first() != Some(&root_thread_id) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "thread deletion closure must begin with its root thread id",
            )
            .into());
        }

        let mut unique_thread_ids = HashSet::new();
        let thread_id_strings = thread_ids
            .iter()
            .map(ThreadId::to_string)
            .filter(|thread_id| unique_thread_ids.insert(thread_id.clone()))
            .collect::<Vec<_>>();
        let deletion_id = Uuid::now_v7().to_string();
        let created_at_ms = datetime_to_epoch_millis(Utc::now());
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;

        let root_thread_id_string = root_thread_id.to_string();
        let existing_rows = sqlx::query_as::<_, (String, i64, String)>(
            "SELECT member_thread_id, member_ordinal, operation_id
             FROM queued_thread_deletion_operation_members
             WHERE root_thread_id = ?
             ORDER BY member_ordinal ASC",
        )
        .bind(&root_thread_id_string)
        .fetch_all(transaction.as_mut())
        .await?;
        let existing_members =
            validate_thread_deletion_operation_rows(root_thread_id, &existing_rows)?;
        if existing_members.is_empty() {
            for (member_ordinal, member_thread_id) in thread_id_strings.iter().enumerate() {
                sqlx::query(
                    "INSERT INTO queued_thread_deletion_operation_members
                        (root_thread_id, member_thread_id, member_ordinal, operation_id, created_at_ms)
                     VALUES (?, ?, ?, ?, ?)",
                )
                .bind(&root_thread_id_string)
                .bind(member_thread_id)
                .bind(i64::try_from(member_ordinal)?)
                .bind(&deletion_id)
                .bind(created_at_ms)
                .execute(transaction.as_mut())
                .await?;
            }
        } else if existing_members != thread_id_strings {
            transaction.rollback().await?;
            return Err(binding_conflict(format!(
                "thread {root_thread_id} hard-delete closure conflicts with its durable operation journal"
            )));
        }

        // The writer transaction is the linearization boundary with dispatch
        // claim. If claim won first, deletion fails without sealing any member
        // of the subtree. If this seal wins, the triggers and current-writer
        // preflights reject every later claim/admission.
        for thread_id in &thread_id_strings {
            if let Some(client_id) = sqlx::query_scalar::<_, String>(
                "SELECT client_user_message_id FROM queued_client_bindings
                 WHERE thread_id = ? AND state = 'dispatching' LIMIT 1",
            )
            .bind(thread_id)
            .fetch_optional(transaction.as_mut())
            .await?
            {
                return Err(binding_conflict(format!(
                    "thread {thread_id} has an active exact queue dispatch for client message id `{client_id}`"
                )));
            }
        }

        for thread_id in &thread_id_strings {
            sqlx::query(
                "INSERT OR IGNORE INTO queued_thread_deletion_fences
                    (thread_id, deletion_id, created_at_ms)
                 VALUES (?, ?, ?)",
            )
            .bind(thread_id)
            .bind(&deletion_id)
            .bind(created_at_ms)
            .execute(transaction.as_mut())
            .await?;
        }

        for thread_id in &thread_id_strings {
            sqlx::query("DELETE FROM queued_items WHERE thread_id = ?")
                .bind(thread_id)
                .execute(transaction.as_mut())
                .await?;
            sqlx::query("DELETE FROM queued_client_bindings WHERE thread_id = ?")
                .bind(thread_id)
                .execute(transaction.as_mut())
                .await?;
        }
        transaction.commit().await?;
        Ok(())
    }

    /// Recover the exact ordered closure for a previously sealed hard-delete operation.
    ///
    /// Journal presence is the only durable state transition. Both an incomplete operation and a
    /// completed operation replay the same idempotent cross-store deletes; no second completion
    /// marker can become ambiguous with the external thread store.
    pub async fn thread_deletion_operation_members(
        &self,
        root_thread_id: ThreadId,
    ) -> anyhow::Result<Option<Vec<ThreadId>>> {
        let rows = sqlx::query_as::<_, (String, i64, String)>(
            "SELECT member_thread_id, member_ordinal, operation_id
             FROM queued_thread_deletion_operation_members
             WHERE root_thread_id = ?
             ORDER BY member_ordinal ASC",
        )
        .bind(root_thread_id.to_string())
        .fetch_all(self.pool.as_ref())
        .await?;
        let member_ids = validate_thread_deletion_operation_rows(root_thread_id, &rows)?;
        if member_ids.is_empty() {
            return Ok(None);
        }
        let members = member_ids
            .into_iter()
            .map(|member_id| {
                ThreadId::from_string(&member_id).map_err(|error| {
                    anyhow::anyhow!(
                        "invalid thread id `{member_id}` in hard-delete operation journal: {error}"
                    )
                })
            })
            .collect::<anyhow::Result<Vec<_>>>()?;
        if members.first() != Some(&root_thread_id) {
            return Err(anyhow::anyhow!(
                "hard-delete operation journal for root {root_thread_id} does not begin with its root"
            ));
        }
        Ok(Some(members))
    }

    /// Whether hard deletion has permanently sealed this thread's queue.
    ///
    /// App Server consults this durable fence before cold resume so a
    /// cross-store delete that fails after queue sealing cannot resurrect a
    /// partially deleted thread.
    pub async fn thread_queue_is_sealed_for_deletion(
        &self,
        thread_id: ThreadId,
    ) -> anyhow::Result<bool> {
        Ok(sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM queued_thread_deletion_fences WHERE thread_id = ?",
        )
        .bind(thread_id.to_string())
        .fetch_one(self.pool.as_ref())
        .await?
            == 1)
    }

    pub(crate) async fn delete_thread_queue(&self, thread_id: ThreadId) -> anyhow::Result<bool> {
        let thread_id = thread_id.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let sealed = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM queued_thread_deletion_fences WHERE thread_id = ?",
        )
        .bind(&thread_id)
        .fetch_one(transaction.as_mut())
        .await?
            == 1;
        if !sealed {
            return Err(binding_conflict(format!(
                "thread {thread_id} queue must be sealed before deletion"
            )));
        }
        if let Some(client_id) = sqlx::query_scalar::<_, String>(
            "SELECT client_user_message_id FROM queued_client_bindings
             WHERE thread_id = ? AND state = 'dispatching' LIMIT 1",
        )
        .bind(&thread_id)
        .fetch_optional(transaction.as_mut())
        .await?
        {
            return Err(binding_conflict(format!(
                "thread {thread_id} has an active exact queue dispatch for client message id `{client_id}`"
            )));
        }
        let queued_rows = sqlx::query("DELETE FROM queued_items WHERE thread_id = ?")
            .bind(&thread_id)
            .execute(transaction.as_mut())
            .await?
            .rows_affected();
        let binding_rows = sqlx::query("DELETE FROM queued_client_bindings WHERE thread_id = ?")
            .bind(&thread_id)
            .execute(transaction.as_mut())
            .await?
            .rows_affected();
        transaction.commit().await?;
        Ok(queued_rows > 0 || binding_rows > 0)
    }
}

#[derive(Debug)]
struct BindingRow {
    payload_sha256: String,
    state: QueuedClientBindingState,
    queued_item_id: Option<String>,
    turn_id: Option<String>,
    reservation_id: String,
    dispatch_owner_id: Option<String>,
    dispatch_lease_expires_at_ms: Option<i64>,
    dispatch_lock_device: Option<i64>,
    dispatch_lock_inode: Option<i64>,
    revision: i64,
}

async fn load_binding(
    connection: &mut SqliteConnection,
    thread_id: &str,
    client_id: &str,
) -> anyhow::Result<Option<BindingRow>> {
    let row = sqlx::query(
        "SELECT payload_sha256, state, queued_item_id, turn_id, reservation_id,
                dispatch_owner_id, dispatch_lease_expires_at_ms,
                dispatch_lock_device, dispatch_lock_inode, revision
         FROM queued_client_bindings
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(thread_id)
    .bind(client_id)
    .fetch_optional(connection)
    .await?;
    row.map(|row| {
        Ok(BindingRow {
            payload_sha256: row.try_get("payload_sha256")?,
            state: QueuedClientBindingState::parse(row.try_get::<String, _>("state")?.as_str())?,
            queued_item_id: row.try_get("queued_item_id")?,
            turn_id: row.try_get("turn_id")?,
            reservation_id: row.try_get("reservation_id")?,
            dispatch_owner_id: row.try_get("dispatch_owner_id")?,
            dispatch_lease_expires_at_ms: row.try_get("dispatch_lease_expires_at_ms")?,
            dispatch_lock_device: row.try_get("dispatch_lock_device")?,
            dispatch_lock_inode: row.try_get("dispatch_lock_inode")?,
            revision: row.try_get("revision")?,
        })
    })
    .transpose()
}

async fn ensure_thread_queue_not_deletion_fenced(
    connection: &mut SqliteConnection,
    thread_id: &str,
) -> anyhow::Result<()> {
    let fenced = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM queued_thread_deletion_fences WHERE thread_id = ?",
    )
    .bind(thread_id)
    .fetch_one(connection)
    .await?
        == 1;
    if fenced {
        return Err(binding_conflict(format!(
            "thread {thread_id} queue is sealed for deletion"
        )));
    }
    Ok(())
}

async fn reserve_outcome_from_binding(
    connection: &mut SqliteConnection,
    thread_id: ThreadId,
    client_id: &str,
    binding: BindingRow,
) -> anyhow::Result<QueuedClientBindingReserveOutcome> {
    match binding.state {
        QueuedClientBindingState::Reserved => {
            let queued_item_id = binding.queued_item_id.ok_or_else(|| {
                anyhow::anyhow!("reserved client binding is missing its queue row identity")
            })?;
            Ok(QueuedClientBindingReserveOutcome::Reserved(
                QueuedClientBindingLease {
                    reservation_id: binding.reservation_id,
                    revision: binding.revision,
                    queued_item_id,
                },
            ))
        }
        QueuedClientBindingState::Queued => {
            let queued_item_id = binding.queued_item_id.ok_or_else(|| {
                anyhow::anyhow!("queued client binding is missing its queue row identity")
            })?;
            let record = load_queued_record(connection, &thread_id.to_string(), &queued_item_id)
                .await?
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "queued client binding `{client_id}` references a missing queue row"
                    )
                })?;
            Ok(QueuedClientBindingReserveOutcome::Queued(record))
        }
        QueuedClientBindingState::Dispatching => {
            let queued_item_id = binding.queued_item_id.ok_or_else(|| {
                anyhow::anyhow!("dispatching client binding is missing its queue row identity")
            })?;
            let record = load_queued_record(connection, &thread_id.to_string(), &queued_item_id)
                .await?
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "dispatching client binding `{client_id}` references a missing queue row"
                    )
                })?;
            Ok(QueuedClientBindingReserveOutcome::Dispatching(record))
        }
        QueuedClientBindingState::Persisted => Ok(QueuedClientBindingReserveOutcome::Persisted {
            turn_id: binding.turn_id.ok_or_else(|| {
                anyhow::anyhow!("persisted client binding is missing its turn identity")
            })?,
        }),
        QueuedClientBindingState::Cancelled => Ok(QueuedClientBindingReserveOutcome::Cancelled),
    }
}

async fn load_queued_record(
    connection: &mut SqliteConnection,
    thread_id: &str,
    item_id: &str,
) -> anyhow::Result<Option<QueuedUserSubmissionRecord>> {
    let row = sqlx::query(
        "SELECT id, thread_id, payload_json FROM queued_items
         WHERE thread_id = ? AND id = ?",
    )
    .bind(thread_id)
    .bind(item_id)
    .fetch_optional(connection)
    .await?;
    row.as_ref()
        .map(QueuedUserSubmissionRecord::try_from_row)
        .transpose()
}

async fn insert_queued_record(
    connection: &mut SqliteConnection,
    thread_id: ThreadId,
    payload_json: &str,
    item_id: &str,
) -> anyhow::Result<QueuedUserSubmissionRecord> {
    let now_ms = datetime_to_epoch_millis(Utc::now());
    let row = sqlx::query(
        "INSERT INTO queued_items (
            id, thread_id, payload_json, queue_order, created_at_ms, updated_at_ms
         ) VALUES (
            ?, ?, ?,
            COALESCE((SELECT MAX(queue_order) FROM queued_items WHERE thread_id = ?), -1) + 1,
            ?, ?
         )
         RETURNING id, thread_id, payload_json",
    )
    .bind(item_id)
    .bind(thread_id.to_string())
    .bind(payload_json)
    .bind(thread_id.to_string())
    .bind(now_ms)
    .bind(now_ms)
    .fetch_one(connection)
    .await?;
    QueuedUserSubmissionRecord::try_from_row(&row)
}

async fn enforce_capacity(
    connection: &mut SqliteConnection,
    thread_id: &str,
    runtime_capacity: Option<usize>,
) -> anyhow::Result<()> {
    let thread_items =
        sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM queued_items WHERE thread_id = ?")
            .bind(thread_id)
            .fetch_one(&mut *connection)
            .await?;
    if thread_items >= i64::try_from(MAX_QUEUE_ITEMS)? {
        return Err(QueueCapacityExceeded {
            limit: QueueCapacityLimit::Thread,
        }
        .into());
    }
    if let Some(capacity) = runtime_capacity {
        let total_items = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM queued_items")
            .fetch_one(connection)
            .await?;
        if total_items >= i64::try_from(capacity)? {
            return Err(QueueCapacityExceeded {
                limit: QueueCapacityLimit::Runtime,
            }
            .into());
        }
    }
    Ok(())
}

async fn transition_binding_to_persisted(
    connection: &mut SqliteConnection,
    thread_id: &str,
    client_id: &str,
    payload_sha256: &str,
    turn_id: &str,
) -> anyhow::Result<()> {
    let changed = sqlx::query(
        "UPDATE queued_client_bindings
         SET state = 'persisted', queued_item_id = NULL, turn_id = ?,
             dispatch_owner_id = NULL, dispatch_lease_expires_at_ms = NULL,
             dispatch_lock_device = NULL, dispatch_lock_inode = NULL,
             revision = revision + 1, updated_at_ms = ?
         WHERE thread_id = ? AND client_user_message_id = ? AND payload_sha256 = ?",
    )
    .bind(turn_id)
    .bind(datetime_to_epoch_millis(Utc::now()))
    .bind(thread_id)
    .bind(client_id)
    .bind(payload_sha256)
    .execute(connection)
    .await?
    .rows_affected();
    if changed != 1 {
        return Err(binding_conflict(format!(
            "client message id `{client_id}` binding changed before persistence"
        )));
    }
    Ok(())
}

fn queued_payload_client_id(payload_json: &str) -> Option<String> {
    let value = serde_json::from_str::<serde_json::Value>(payload_json).ok()?;
    value
        .get("UserInput")?
        .get("client_id")?
        .as_str()
        .map(str::to_string)
}

async fn reject_raw_enqueue_for_existing_binding(
    connection: &mut SqliteConnection,
    thread_id: &str,
    payload_json: &str,
) -> anyhow::Result<()> {
    let Some(client_id) = queued_payload_client_id(payload_json) else {
        return Ok(());
    };
    let binding_exists = sqlx::query_scalar::<_, i64>(
        "SELECT 1 FROM queued_client_bindings
         WHERE thread_id = ? AND client_user_message_id = ?",
    )
    .bind(thread_id)
    .bind(&client_id)
    .fetch_optional(connection)
    .await?
    .is_some();
    if binding_exists {
        return Err(binding_conflict(format!(
            "raw enqueue cannot bypass exact client message binding `{client_id}`"
        )));
    }
    Ok(())
}

fn validate_binding_identity(client_id: &str, payload_sha256: &str) -> anyhow::Result<()> {
    if client_id.is_empty() {
        return Err(binding_conflict(
            "client message identity cannot be empty".to_string(),
        ));
    }
    if payload_sha256.len() != 64
        || !payload_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(binding_conflict(
            "payload digest must be a lowercase SHA-256 hex string".to_string(),
        ));
    }
    Ok(())
}

fn ensure_binding_digest(client_id: &str, expected: &str, actual: &str) -> anyhow::Result<()> {
    if expected == actual {
        return Ok(());
    }
    Err(binding_conflict(format!(
        "client message id `{client_id}` is already bound to payload digest `{actual}`"
    )))
}

fn binding_conflict(message: String) -> anyhow::Error {
    QueuedClientBindingConflict { message }.into()
}

fn validate_dispatch_window(
    owner_id: &str,
    now_ms: i64,
    lease_expires_at_ms: i64,
) -> anyhow::Result<()> {
    if owner_id.is_empty() || owner_id.len() > 256 {
        return Err(binding_conflict(
            "dispatch owner identity must contain 1 to 256 bytes".to_string(),
        ));
    }
    if lease_expires_at_ms <= now_ms {
        return Err(binding_conflict(
            "dispatch lease must expire after its authorization time".to_string(),
        ));
    }
    Ok(())
}

fn validate_turn_id(turn_id: &str) -> anyhow::Result<()> {
    if turn_id.is_empty() {
        return Err(binding_conflict(
            "persisted turn identity cannot be empty".to_string(),
        ));
    }
    Ok(())
}

fn ensure_dispatch_lock_identity(
    process_lock: &QueuedClientDispatchLock,
    thread_id: ThreadId,
    client_id: &str,
    payload_sha256: &str,
) -> anyhow::Result<()> {
    if process_lock.thread_id == thread_id
        && process_lock.client_id == client_id
        && process_lock.payload_sha256 == payload_sha256
        && process_lock.file.is_some()
    {
        return Ok(());
    }
    Err(binding_conflict(format!(
        "client message id `{client_id}` does not match the held dispatch process lock"
    )))
}

fn ensure_dispatch_lease_lock(
    process_lock: &QueuedClientDispatchLock,
    lease: &QueuedClientDispatchLease,
) -> anyhow::Result<()> {
    ensure_dispatch_lock_identity(
        process_lock,
        lease.thread_id,
        &lease.client_id,
        &lease.payload_sha256,
    )?;
    if process_lock.lock_nonce != lease.lock_nonce
        || process_lock.lock_identity.device != lease.lock_device
        || process_lock.lock_identity.inode != lease.lock_inode
    {
        return Err(binding_conflict(format!(
            "client message id `{}` dispatch lease belongs to another process lock acquisition",
            lease.client_id
        )));
    }
    Ok(())
}

fn ensure_expired_dispatch_lock(
    process_lock: &QueuedClientDispatchLock,
    expired: &QueuedClientExpiredDispatch,
) -> anyhow::Result<()> {
    ensure_dispatch_lock_identity(
        process_lock,
        expired.thread_id,
        &expired.client_id,
        &expired.payload_sha256,
    )?;
    if process_lock.lock_nonce != expired.lock_nonce
        || process_lock.lock_identity.device != expired.lock_device
        || process_lock.lock_identity.inode != expired.lock_inode
    {
        return Err(binding_conflict(format!(
            "client message id `{}` expired dispatch belongs to another process lock acquisition",
            expired.client_id
        )));
    }
    Ok(())
}

fn ensure_binding_lock_identity(
    binding: &BindingRow,
    process_lock: &QueuedClientDispatchLock,
    may_initialize: bool,
) -> anyhow::Result<()> {
    match (binding.dispatch_lock_device, binding.dispatch_lock_inode) {
        (None, None) if may_initialize => Ok(()),
        (Some(device), Some(inode))
            if device == process_lock.lock_identity.device
                && inode == process_lock.lock_identity.inode =>
        {
            Ok(())
        }
        (expected_device, expected_inode) => Err(binding_conflict(format!(
            "client message id `{}` dispatch lock inode changed (expected {expected_device:?}:{expected_inode:?}, opened {}:{})",
            process_lock.client_id,
            process_lock.lock_identity.device,
            process_lock.lock_identity.inode,
        ))),
    }
}

fn dispatch_lease(
    process_lock: &QueuedClientDispatchLock,
    queued_item_id: &str,
    owner_id: &str,
    revision: i64,
    lease_expires_at_ms: i64,
) -> QueuedClientDispatchLease {
    QueuedClientDispatchLease {
        thread_id: process_lock.thread_id,
        client_id: process_lock.client_id.clone(),
        payload_sha256: process_lock.payload_sha256.clone(),
        queued_item_id: queued_item_id.to_string(),
        owner_id: owner_id.to_string(),
        revision,
        lease_expires_at_ms,
        lock_nonce: process_lock.lock_nonce.clone(),
        lock_device: process_lock.lock_identity.device,
        lock_inode: process_lock.lock_identity.inode,
    }
}

async fn transition_dispatch_lease_to_persisted(
    connection: &mut SqliteConnection,
    lease: &QueuedClientDispatchLease,
    turn_id: &str,
) -> anyhow::Result<bool> {
    Ok(sqlx::query(
        "UPDATE queued_client_bindings
         SET state = 'persisted', queued_item_id = NULL, turn_id = ?,
             dispatch_owner_id = NULL, dispatch_lease_expires_at_ms = NULL,
             dispatch_lock_device = NULL, dispatch_lock_inode = NULL,
             revision = revision + 1, updated_at_ms = ?
         WHERE thread_id = ? AND client_user_message_id = ?
           AND payload_sha256 = ? AND queued_item_id = ?
           AND state = 'dispatching' AND dispatch_owner_id = ?
           AND dispatch_lock_device = ? AND dispatch_lock_inode = ? AND revision = ?",
    )
    .bind(turn_id)
    .bind(datetime_to_epoch_millis(Utc::now()))
    .bind(lease.thread_id.to_string())
    .bind(&lease.client_id)
    .bind(&lease.payload_sha256)
    .bind(&lease.queued_item_id)
    .bind(&lease.owner_id)
    .bind(lease.lock_device)
    .bind(lease.lock_inode)
    .bind(lease.revision)
    .execute(connection)
    .await?
    .rows_affected()
        == 1)
}

async fn transition_dispatch_binding_to_persisted(
    connection: &mut SqliteConnection,
    expired: &QueuedClientExpiredDispatch,
    turn_id: &str,
    now_ms: i64,
) -> anyhow::Result<bool> {
    Ok(sqlx::query(
        "UPDATE queued_client_bindings
         SET state = 'persisted', queued_item_id = NULL, turn_id = ?,
             dispatch_owner_id = NULL, dispatch_lease_expires_at_ms = NULL,
             dispatch_lock_device = NULL, dispatch_lock_inode = NULL,
             revision = revision + 1, updated_at_ms = ?
         WHERE thread_id = ? AND client_user_message_id = ?
           AND payload_sha256 = ? AND queued_item_id = ?
           AND state = 'dispatching' AND dispatch_owner_id = ?
           AND dispatch_lock_device = ? AND dispatch_lock_inode = ?
           AND revision = ? AND dispatch_lease_expires_at_ms <= ?",
    )
    .bind(turn_id)
    .bind(datetime_to_epoch_millis(Utc::now()))
    .bind(expired.thread_id.to_string())
    .bind(&expired.client_id)
    .bind(&expired.payload_sha256)
    .bind(&expired.queued_item_id)
    .bind(&expired.previous_owner_id)
    .bind(expired.lock_device)
    .bind(expired.lock_inode)
    .bind(expired.revision)
    .bind(now_ms)
    .execute(connection)
    .await?
    .rows_affected()
        == 1)
}

async fn delete_exact_dispatch_row(
    connection: &mut SqliteConnection,
    thread_id: &str,
    queued_item_id: &str,
    client_id: &str,
) -> anyhow::Result<()> {
    let deleted = sqlx::query("DELETE FROM queued_items WHERE thread_id = ? AND id = ?")
        .bind(thread_id)
        .bind(queued_item_id)
        .execute(connection)
        .await?
        .rows_affected();
    if deleted != 1 {
        return Err(binding_conflict(format!(
            "client message id `{client_id}` dispatch queue row changed before completion"
        )));
    }
    Ok(())
}

fn dispatch_lock_file_name(thread_id: ThreadId, client_id: &str, payload_sha256: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(thread_id.to_string().as_bytes());
    digest.update([0]);
    digest.update(client_id.as_bytes());
    digest.update([0]);
    digest.update(payload_sha256.as_bytes());
    format!("{:x}.lock", digest.finalize())
}

fn release_process_dispatch_reservation(registry_key: &DispatchRegistryKey) {
    ACTIVE_DISPATCH_LOCKS
        .get_or_init(|| StdMutex::new(HashSet::new()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .remove(registry_key);
}

impl DispatchLockDirectory {
    pub(crate) fn open(sqlite_home: &Path) -> std::io::Result<Self> {
        let canonical_home = fs::canonicalize(sqlite_home)?;
        open_dispatch_lock_directory(canonical_home)
    }
}

#[cfg(unix)]
fn open_dispatch_lock_directory(canonical_home: PathBuf) -> std::io::Result<DispatchLockDirectory> {
    let home = CString::new(canonical_home.as_os_str().as_bytes()).map_err(|_| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "SQLite home contains an interior NUL",
        )
    })?;
    let home_fd = unsafe {
        libc::open(
            home.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        )
    };
    if home_fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let home_directory = unsafe { File::from_raw_fd(home_fd) };
    validate_owned_directory(&home_directory, /*strict_mode*/ false)?;

    let directory_name = c"queue-dispatch-locks";
    let mkdir_result = unsafe {
        libc::mkdirat(
            home_directory.as_raw_fd(),
            directory_name.as_ptr(),
            DISPATCH_LOCK_DIRECTORY_MODE as libc::mode_t,
        )
    };
    if mkdir_result != 0 {
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::AlreadyExists {
            return Err(error);
        }
    }
    let directory_fd = unsafe {
        libc::openat(
            home_directory.as_raw_fd(),
            directory_name.as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        )
    };
    if directory_fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let directory = unsafe { File::from_raw_fd(directory_fd) };
    let chmod_result = unsafe {
        libc::fchmod(
            directory.as_raw_fd(),
            DISPATCH_LOCK_DIRECTORY_MODE as libc::mode_t,
        )
    };
    if chmod_result != 0 {
        return Err(std::io::Error::last_os_error());
    }
    validate_owned_directory(&directory, /*strict_mode*/ true)?;
    let identity = unix_file_identity(&directory.metadata()?)?;
    Ok(DispatchLockDirectory {
        path: canonical_home.join("queue-dispatch-locks"),
        identity,
        _home_directory: home_directory,
        directory,
    })
}

#[cfg(unix)]
fn open_secure_dispatch_lock(
    directory: &DispatchLockDirectory,
    file_name: &std::ffi::OsStr,
) -> std::io::Result<(File, DispatchLockIdentity)> {
    let file_name = CString::new(file_name.as_bytes()).map_err(|_| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "exact queue dispatch lock file name contains an interior NUL",
        )
    })?;
    let file_fd = unsafe {
        libc::openat(
            directory.directory.as_raw_fd(),
            file_name.as_ptr(),
            libc::O_RDWR | libc::O_CREAT | libc::O_CLOEXEC | libc::O_NOFOLLOW,
            DISPATCH_LOCK_FILE_MODE,
        )
    };
    if file_fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let file = unsafe { File::from_raw_fd(file_fd) };
    let chmod_result =
        unsafe { libc::fchmod(file.as_raw_fd(), DISPATCH_LOCK_FILE_MODE as libc::mode_t) };
    if chmod_result != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o777 != DISPATCH_LOCK_FILE_MODE
        || metadata.nlink() != 1
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "exact queue dispatch lock must be a single-link, owner-only regular file",
        ));
    }
    let identity = unix_file_identity(&metadata)?;
    Ok((file, identity))
}

#[cfg(not(unix))]
fn open_dispatch_lock_directory(canonical_home: PathBuf) -> std::io::Result<DispatchLockDirectory> {
    let path = canonical_home.join("queue-dispatch-locks");
    match fs::create_dir(&path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error),
    }
    let metadata = fs::symlink_metadata(&path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "exact queue dispatch lock directory is not a real directory",
        ));
    }
    Ok(DispatchLockDirectory {
        identity: hashed_path_identity(&path),
        path,
    })
}

#[cfg(not(unix))]
fn open_secure_dispatch_lock(
    directory: &DispatchLockDirectory,
    file_name: &std::ffi::OsStr,
) -> std::io::Result<(File, DispatchLockIdentity)> {
    let path = directory.path.join(file_name);
    if let Ok(metadata) = fs::symlink_metadata(&path)
        && (metadata.file_type().is_symlink() || !metadata.is_file())
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "exact queue dispatch lock is not a regular file",
        ));
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&path)?;
    Ok((file, hashed_path_identity(&path)))
}

#[cfg(unix)]
fn validate_owned_directory(directory: &File, strict_mode: bool) -> std::io::Result<()> {
    let metadata = directory.metadata()?;
    let mode = metadata.mode() & 0o777;
    if !metadata.is_dir()
        || metadata.uid() != unsafe { libc::geteuid() }
        || (strict_mode && mode != DISPATCH_LOCK_DIRECTORY_MODE)
        || (!strict_mode && mode & 0o022 != 0)
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "SQLite home and dispatch lock directory must be owner-controlled directories",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn unix_file_identity(metadata: &fs::Metadata) -> std::io::Result<DispatchLockIdentity> {
    Ok(DispatchLockIdentity {
        device: i64::try_from(metadata.dev()).map_err(|_| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "device id exceeds SQLite INTEGER",
            )
        })?,
        inode: i64::try_from(metadata.ino()).map_err(|_| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "inode exceeds SQLite INTEGER",
            )
        })?,
    })
}

#[cfg(not(unix))]
fn hashed_path_identity(path: &Path) -> DispatchLockIdentity {
    let digest = Sha256::digest(path.as_os_str().to_string_lossy().as_bytes());
    let mut device = [0_u8; 8];
    let mut inode = [0_u8; 8];
    device.copy_from_slice(&digest[..8]);
    inode.copy_from_slice(&digest[8..16]);
    DispatchLockIdentity {
        device: i64::from_be_bytes(device) & i64::MAX,
        inode: i64::from_be_bytes(inode) & i64::MAX,
    }
}

#[cfg(test)]
#[path = "queued_items_tests.rs"]
mod tests;
