use std::fmt;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::InboxDisposition;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;

use crate::MatrixSidecarConfig;

#[derive(Clone, Eq, PartialEq)]
pub struct MatrixTimelineEvent {
    pub event_id: MatrixEventId,
    pub room_id: MatrixRoomId,
    pub sender: MatrixUserId,
    pub event_type: String,
    pub payload: Vec<u8>,
    pub mentioned_user_ids: Vec<MatrixUserId>,
    pub origin_server_ts_ms: u64,
    pub received_at_ms: u64,
}

impl fmt::Debug for MatrixTimelineEvent {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("MatrixTimelineEvent")
            .field("event_id", &self.event_id)
            .field("room_id", &self.room_id)
            .field("sender", &self.sender)
            .field("event_type", &self.event_type)
            .field("payload_bytes", &self.payload.len())
            .field("mentioned_user_ids", &self.mentioned_user_ids)
            .field("origin_server_ts_ms", &self.origin_server_ts_ms)
            .field("received_at_ms", &self.received_at_ms)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IngressIgnoredReason {
    WrongRoom,
    WrongSender,
    MissingExplicitMention,
    UnsupportedMessageType,
    MalformedEvent,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IngressDisposition {
    Accepted,
    Duplicate,
    Ignored(IngressIgnoredReason),
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct IngressMetrics {
    pub accepted: u64,
    pub duplicate: u64,
    pub ignored: u64,
    pub malformed: u64,
    pub failed: u64,
}

#[derive(Clone)]
pub struct MatrixIngress {
    pub(crate) config: MatrixSidecarConfig,
    pub(crate) store: MatrixDurableStore,
    accepted: Arc<AtomicU64>,
    duplicate: Arc<AtomicU64>,
    ignored: Arc<AtomicU64>,
    malformed: Arc<AtomicU64>,
    failed: Arc<AtomicU64>,
    fatal: Arc<AtomicBool>,
}

impl MatrixIngress {
    pub fn new(config: MatrixSidecarConfig, store: MatrixDurableStore) -> Self {
        Self {
            config,
            store,
            accepted: Arc::new(AtomicU64::new(0)),
            duplicate: Arc::new(AtomicU64::new(0)),
            ignored: Arc::new(AtomicU64::new(0)),
            malformed: Arc::new(AtomicU64::new(0)),
            failed: Arc::new(AtomicU64::new(0)),
            fatal: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn fatal(&self) -> bool {
        self.fatal.load(Ordering::Acquire)
    }

    pub fn metrics(&self) -> IngressMetrics {
        IngressMetrics {
            accepted: self.accepted.load(Ordering::Relaxed),
            duplicate: self.duplicate.load(Ordering::Relaxed),
            ignored: self.ignored.load(Ordering::Relaxed),
            malformed: self.malformed.load(Ordering::Relaxed),
            failed: self.failed.load(Ordering::Relaxed),
        }
    }

    pub(crate) fn fence(&self) {
        self.failed.fetch_add(1, Ordering::Relaxed);
        self.fatal.store(true, Ordering::Release);
    }

    pub(crate) fn record_ignored(&self, reason: IngressIgnoredReason) -> IngressDisposition {
        self.ignored.fetch_add(1, Ordering::Relaxed);
        IngressDisposition::Ignored(reason)
    }

    /// Account for one SDK timeline event that cannot be represented by the
    /// exact Hepta Matrix protocol. A malformed or future-format remote event
    /// is not durable state failure and must not stop sync for the Agent.
    pub fn record_malformed_event(&self) -> IngressDisposition {
        self.malformed.fetch_add(1, Ordering::Relaxed);
        self.record_ignored(IngressIgnoredReason::MalformedEvent)
    }

    pub fn filter(&self, event: &MatrixTimelineEvent) -> Option<IngressIgnoredReason> {
        if !self.config.binding.allowed_rooms.contains(&event.room_id) {
            return Some(IngressIgnoredReason::WrongRoom);
        }
        if !self.config.binding.allowed_senders.contains(&event.sender) {
            return Some(IngressIgnoredReason::WrongSender);
        }
        if self.config.binding.require_explicit_mention
            && !event
                .mentioned_user_ids
                .contains(&self.config.binding.expected_mxid)
        {
            return Some(IngressIgnoredReason::MissingExplicitMention);
        }
        None
    }

    /// Persist one already-normalized event through the durable store.
    ///
    /// Product sync uses the batch checkpoint API. This single-event entry is
    /// retained for deterministic transport tests and non-SDK callers; it does
    /// not own or advance a Matrix `/sync` cursor.
    pub async fn ingest(
        &self,
        event: MatrixTimelineEvent,
    ) -> Result<IngressDisposition, MatrixIngressError> {
        let draft = match self.prepare(event) {
            Ok(draft) => draft,
            Err(reason) => return Ok(IngressDisposition::Ignored(reason)),
        };
        match self.store.ingest_inbox(&draft).await {
            Ok(InboxDisposition::Accepted(_)) => {
                self.accepted.fetch_add(1, Ordering::Relaxed);
                Ok(IngressDisposition::Accepted)
            }
            Ok(InboxDisposition::Duplicate(_)) => {
                self.duplicate.fetch_add(1, Ordering::Relaxed);
                Ok(IngressDisposition::Duplicate)
            }
            Err(error) => {
                self.fence();
                Err(error.into())
            }
        }
    }

    pub(crate) fn prepare(
        &self,
        event: MatrixTimelineEvent,
    ) -> Result<InboxDraft, IngressIgnoredReason> {
        if let Some(reason) = self.filter(&event) {
            self.record_ignored(reason);
            return Err(reason);
        }
        Ok(InboxDraft {
            event_id: event.event_id,
            room_id: event.room_id,
            sender: event.sender,
            event_type: event.event_type,
            payload: event.payload,
            binding_revision: self.config.binding.revision,
            generation: self.config.matrix_generation,
            origin_server_ts_ms: event.origin_server_ts_ms,
            received_at_ms: event.received_at_ms,
        })
    }

    pub(crate) fn record_sync_commit(&self, accepted: usize, duplicates: usize) {
        let accepted = u64::try_from(accepted).unwrap_or(u64::MAX);
        let duplicates = u64::try_from(duplicates).unwrap_or(u64::MAX);
        self.accepted.fetch_add(accepted, Ordering::Relaxed);
        self.duplicate.fetch_add(duplicates, Ordering::Relaxed);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixIngressError {
    #[error("Matrix ingress request conflicts with durable state")]
    Conflict,
    #[error("Matrix ingress durable store is unavailable")]
    Unavailable,
}

impl From<MatrixDurableError> for MatrixIngressError {
    fn from(error: MatrixDurableError) -> Self {
        match error {
            MatrixDurableError::Unavailable => Self::Unavailable,
            MatrixDurableError::Invalid
            | MatrixDurableError::AccessDenied
            | MatrixDurableError::Conflict
            | MatrixDurableError::Corrupt => Self::Conflict,
        }
    }
}
