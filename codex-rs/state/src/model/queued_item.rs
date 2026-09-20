use anyhow::Result;
use codex_protocol::ThreadId;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

/// One durable, ordered user submission for a thread.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuedUserSubmissionRecord {
    pub id: String,
    pub thread_id: ThreadId,
    pub payload: String,
}

/// Durable state for one exact `(thread, client message id, payload digest)`
/// queue admission.  The binding survives queue-row deletion so a replay
/// cannot resurrect an already persisted or explicitly cancelled message.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueuedClientBindingState {
    Reserved,
    Queued,
    Dispatching,
    Persisted,
    Cancelled,
}

impl QueuedClientBindingState {
    pub(crate) fn parse(value: &str) -> Result<Self> {
        match value {
            "reserved" => Ok(Self::Reserved),
            "queued" => Ok(Self::Queued),
            "dispatching" => Ok(Self::Dispatching),
            "persisted" => Ok(Self::Persisted),
            "cancelled" => Ok(Self::Cancelled),
            value => anyhow::bail!("invalid queued client binding state `{value}`"),
        }
    }
}

/// CAS lease returned after the SQLite writer transaction has reserved one
/// client-message identity. Multiple same-payload retries may share this lease;
/// finalization remains idempotent because it rechecks the durable state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuedClientBindingLease {
    pub reservation_id: String,
    pub revision: i64,
    pub queued_item_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QueuedClientBindingReserveOutcome {
    Reserved(QueuedClientBindingLease),
    Queued(QueuedUserSubmissionRecord),
    Dispatching(QueuedUserSubmissionRecord),
    Persisted { turn_id: String },
    Cancelled,
}

/// Fenced authority for one exact Core admission attempt. The token is valid
/// only while its matching process-held dispatch lock remains alive.
#[derive(Debug, PartialEq, Eq)]
pub struct QueuedClientDispatchLease {
    pub(crate) thread_id: ThreadId,
    pub(crate) client_id: String,
    pub(crate) payload_sha256: String,
    pub(crate) queued_item_id: String,
    pub(crate) owner_id: String,
    pub(crate) revision: i64,
    pub(crate) lease_expires_at_ms: i64,
    pub(crate) lock_nonce: String,
    pub(crate) lock_device: i64,
    pub(crate) lock_inode: i64,
}

impl QueuedClientDispatchLease {
    pub fn thread_id(&self) -> ThreadId {
        self.thread_id
    }
}

/// Snapshot of an expired dispatch row. Expiry alone is not takeover proof:
/// callers must also hold the binding's process lock and scan the exact rollout
/// before passing this token to recovery.
#[derive(Debug, PartialEq, Eq)]
pub struct QueuedClientExpiredDispatch {
    pub(crate) thread_id: ThreadId,
    pub(crate) client_id: String,
    pub(crate) payload_sha256: String,
    pub(crate) queued_item_id: String,
    pub(crate) previous_owner_id: String,
    pub(crate) revision: i64,
    pub(crate) lease_expires_at_ms: i64,
    pub(crate) lock_nonce: String,
    pub(crate) lock_device: i64,
    pub(crate) lock_inode: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub enum QueuedClientDispatchClaimOutcome {
    Acquired(QueuedClientDispatchLease),
    InFlight {
        owner_id: String,
        revision: i64,
        lease_expires_at_ms: i64,
    },
    Expired(QueuedClientExpiredDispatch),
    Persisted {
        turn_id: String,
    },
    Cancelled,
    Missing,
    Unbound,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueuedClientBindingFinalizeMode {
    AllowIfAbsent,
    ReconcileOnly,
}

/// Complete one exact queue admission after the caller has inspected the
/// authoritative rollout. Keeping the correlated values together prevents a
/// caller from accidentally mixing identities from different reservations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuedClientBindingFinalizeRequest {
    pub thread_id: ThreadId,
    pub client_id: String,
    pub payload_sha256: String,
    pub payload_json: String,
    pub lease: QueuedClientBindingLease,
    pub mode: QueuedClientBindingFinalizeMode,
    pub observed_turn_id: Option<String>,
    pub runtime_capacity: Option<usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QueuedClientBindingFinalizeOutcome {
    Queued {
        record: QueuedUserSubmissionRecord,
        created: bool,
    },
    Persisted {
        turn_id: String,
    },
    Missing,
    Cancelled,
}

/// Typed fail-closed rejection for incompatible reuse or mutation of a durable
/// client-message binding.
#[derive(Debug)]
pub struct QueuedClientBindingConflict {
    pub message: String,
}

impl std::fmt::Display for QueuedClientBindingConflict {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for QueuedClientBindingConflict {}

impl QueuedUserSubmissionRecord {
    pub(crate) fn try_from_row(row: &SqliteRow) -> Result<Self> {
        Ok(Self {
            id: row.try_get("id")?,
            thread_id: ThreadId::try_from(row.try_get::<String, _>("thread_id")?)?,
            payload: row.try_get("payload_json")?,
        })
    }
}
