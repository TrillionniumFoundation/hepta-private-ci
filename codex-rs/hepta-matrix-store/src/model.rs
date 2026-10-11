use std::fmt;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::LocalApprovalDecision;
use codex_hepta_matrix_protocol::MatrixdEventBatch;
use codex_hepta_matrix_protocol::PendingApproval;
use serde::Deserialize;
use serde::Serialize;

use crate::MatrixEventId;
use crate::MatrixRoomId;
use crate::MatrixTransactionId;
use crate::MatrixUserId;

pub const MIN_DELTA_COALESCE_WINDOW_MS: u64 = 100;
pub const MAX_DELTA_COALESCE_WINDOW_MS: u64 = 250;
pub const MAX_EVENT_CAPACITY: usize = 65_536;
pub const MAX_DELTA_BATCH_BYTES: usize = 64 * 1024;
pub const MAX_PAYLOAD_BYTES: usize = 1024 * 1024;
pub const MAX_PAGE_ITEMS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PendingApprovalKind {
    CommandExecution,
    FileChange,
}

impl PendingApprovalKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::CommandExecution => "command_execution",
            Self::FileChange => "file_change",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "command_execution" => Some(Self::CommandExecution),
            "file_change" => Some(Self::FileChange),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PendingApprovalDraft {
    pub approval: PendingApproval,
    pub request_id_json: String,
    pub request_kind: PendingApprovalKind,
    pub attached_agent_generation: u64,
    pub process_incarnation: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PendingApprovalRecord {
    pub approval: PendingApproval,
    pub request_id_json: String,
    pub request_kind: PendingApprovalKind,
    pub attached_agent_generation: u64,
    pub process_incarnation: String,
    pub resolution_decision: Option<LocalApprovalDecision>,
    pub resolving_at_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixControlSnapshot {
    pub cursor: u64,
    pub active_thread_id: Option<String>,
    pub active_turn_id: Option<String>,
    pub pending_approvals: Vec<PendingApproval>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixControlPage {
    pub batch: MatrixdEventBatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDurableConfig {
    pub delta_coalesce_window_ms: u64,
    pub max_delta_batch_bytes: usize,
    pub event_capacity: usize,
}

impl Default for MatrixDurableConfig {
    fn default() -> Self {
        Self {
            delta_coalesce_window_ms: 150,
            max_delta_batch_bytes: 16 * 1024,
            event_capacity: 1_024,
        }
    }
}

impl MatrixDurableConfig {
    pub(crate) fn is_valid(&self) -> bool {
        (MIN_DELTA_COALESCE_WINDOW_MS..=MAX_DELTA_COALESCE_WINDOW_MS)
            .contains(&self.delta_coalesce_window_ms)
            && (1..=MAX_DELTA_BATCH_BYTES).contains(&self.max_delta_batch_bytes)
            && (1..=MAX_EVENT_CAPACITY).contains(&self.event_capacity)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RoomBindingDraft {
    pub room_id: MatrixRoomId,
    pub agent_user_id: MatrixUserId,
    pub expected_revision: Option<u64>,
    pub generation: u64,
    pub changed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RoomBinding {
    pub room_id: MatrixRoomId,
    pub owner_agent_id: AgentId,
    pub agent_user_id: MatrixUserId,
    pub revision: u64,
    pub generation: u64,
    pub changed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RoomThreadBindingDraft {
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub generation: u64,
    pub project_id: String,
    pub thread_id: Option<String>,
    pub changed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RoomThreadBinding {
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub generation: u64,
    pub project_id: String,
    pub thread_id: Option<String>,
    pub changed_at_ms: u64,
}

#[derive(Clone, Eq, PartialEq)]
pub struct InboxDraft {
    pub event_id: MatrixEventId,
    pub room_id: MatrixRoomId,
    pub sender: MatrixUserId,
    pub event_type: String,
    pub payload: Vec<u8>,
    pub binding_revision: u64,
    pub generation: u64,
    pub origin_server_ts_ms: u64,
    pub received_at_ms: u64,
}

/// The Hepta-owned Matrix `/sync` cursor for one exact Agent generation.
///
/// The Matrix SDK may persist an internal cursor before it invokes event
/// handlers.  This checkpoint is intentionally separate and is advanced only
/// in the same SQLite transaction as the corresponding durable inbox batch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSyncCheckpoint {
    pub owner_agent_id: AgentId,
    pub binding_revision: u64,
    pub generation: u64,
    pub next_batch: String,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSyncCommit {
    pub checkpoint: MatrixSyncCheckpoint,
    pub accepted: usize,
    pub duplicates: usize,
}

impl fmt::Debug for InboxDraft {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("InboxDraft")
            .field("event_id", &self.event_id)
            .field("room_id", &self.room_id)
            .field("sender", &self.sender)
            .field("event_type", &self.event_type)
            .field("payload_bytes", &self.payload.len())
            .field("binding_revision", &self.binding_revision)
            .field("generation", &self.generation)
            .field("origin_server_ts_ms", &self.origin_server_ts_ms)
            .field("received_at_ms", &self.received_at_ms)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InboxState {
    Pending,
    Processed,
}

impl InboxState {
    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "processed" => Some(Self::Processed),
            _ => None,
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct InboxRecord {
    pub cursor: u64,
    pub event_id: MatrixEventId,
    pub room_id: MatrixRoomId,
    pub sender: MatrixUserId,
    pub event_type: String,
    pub payload: Vec<u8>,
    pub binding_revision: u64,
    pub generation: u64,
    pub origin_server_ts_ms: u64,
    pub received_at_ms: u64,
    pub state: InboxState,
    pub processed_at_ms: Option<u64>,
}

impl fmt::Debug for InboxRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("InboxRecord")
            .field("cursor", &self.cursor)
            .field("event_id", &self.event_id)
            .field("room_id", &self.room_id)
            .field("sender", &self.sender)
            .field("event_type", &self.event_type)
            .field("payload_bytes", &self.payload.len())
            .field("binding_revision", &self.binding_revision)
            .field("generation", &self.generation)
            .field("origin_server_ts_ms", &self.origin_server_ts_ms)
            .field("received_at_ms", &self.received_at_ms)
            .field("state", &self.state)
            .field("processed_at_ms", &self.processed_at_ms)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InboxDisposition {
    Accepted(InboxRecord),
    Duplicate(InboxRecord),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InboxDispatchState {
    Begun,
    Queued,
    Admitted,
    Completed,
}

impl InboxDispatchState {
    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "begun" => Some(Self::Begun),
            "queued" => Some(Self::Queued),
            "admitted" => Some(Self::Admitted),
            "completed" => Some(Self::Completed),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InboxDispatchRecord {
    pub event_id: MatrixEventId,
    pub client_user_message_id: String,
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub generation: u64,
    pub project_id: String,
    pub state: InboxDispatchState,
    pub thread_id: Option<String>,
    pub queued_submission_id: Option<String>,
    pub turn_id: Option<String>,
    pub begun_at_ms: u64,
    pub updated_at_ms: u64,
    pub completed_at_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InboxQueuedDraft {
    pub event_id: MatrixEventId,
    pub client_user_message_id: String,
    pub project_id: String,
    pub thread_id: String,
    pub queued_submission_id: String,
    pub queued_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InboxAdmissionDraft {
    pub event_id: MatrixEventId,
    pub client_user_message_id: String,
    pub project_id: String,
    pub thread_id: String,
    pub queued_submission_id: Option<String>,
    pub turn_id: String,
    pub admitted_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutboxKind {
    TextDelta,
    Final,
    ToolTransition,
    Approval,
    Terminal,
}

impl OutboxKind {
    pub fn is_critical(self) -> bool {
        self != Self::TextDelta
    }

    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::TextDelta => "text_delta",
            Self::Final => "final",
            Self::ToolTransition => "tool_transition",
            Self::Approval => "approval",
            Self::Terminal => "terminal",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "text_delta" => Some(Self::TextDelta),
            "final" => Some(Self::Final),
            "tool_transition" => Some(Self::ToolTransition),
            "approval" => Some(Self::Approval),
            "terminal" => Some(Self::Terminal),
            _ => None,
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct OutboxDraft {
    pub logical_outbox_id: String,
    pub revision: u64,
    pub txn_id: MatrixTransactionId,
    pub room_id: MatrixRoomId,
    pub kind: OutboxKind,
    pub payload: Vec<u8>,
    pub binding_revision: u64,
    pub generation: u64,
    pub created_at_ms: u64,
}

impl fmt::Debug for OutboxDraft {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OutboxDraft")
            .field("logical_outbox_id", &self.logical_outbox_id)
            .field("revision", &self.revision)
            .field("txn_id", &self.txn_id)
            .field("room_id", &self.room_id)
            .field("kind", &self.kind)
            .field("payload_bytes", &self.payload.len())
            .field("binding_revision", &self.binding_revision)
            .field("generation", &self.generation)
            .field("created_at_ms", &self.created_at_ms)
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OutboxState {
    Pending,
    InFlight,
    RetryScheduled,
    Sent,
    PermanentFailure,
}

impl OutboxState {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::InFlight => "in_flight",
            Self::RetryScheduled => "retry_scheduled",
            Self::Sent => "sent",
            Self::PermanentFailure => "permanent_failure",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "in_flight" => Some(Self::InFlight),
            "retry_scheduled" => Some(Self::RetryScheduled),
            "sent" => Some(Self::Sent),
            "permanent_failure" => Some(Self::PermanentFailure),
            _ => None,
        }
    }

    pub(crate) fn is_terminal(self) -> bool {
        matches!(self, Self::Sent | Self::PermanentFailure)
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct OutboxRecord {
    pub outbox_id: u64,
    pub stable_txn_id: MatrixTransactionId,
    pub room_id: MatrixRoomId,
    pub kind: OutboxKind,
    pub payload: Vec<u8>,
    pub logical_txn_count: u64,
    pub binding_revision: u64,
    pub generation: u64,
    pub state: OutboxState,
    pub attempts: u64,
    pub next_attempt_at_ms: u64,
    pub lease_until_ms: Option<u64>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
    pub sent_event_id: Option<MatrixEventId>,
    /// Original Matrix event replaced by this logical-stream revision.
    ///
    /// This is derived under the outbox claim transaction from the first
    /// successfully-sent revision. It is intentionally not caller supplied.
    pub replaces_event_id: Option<MatrixEventId>,
}

impl fmt::Debug for OutboxRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("OutboxRecord")
            .field("outbox_id", &self.outbox_id)
            .field("stable_txn_id", &self.stable_txn_id)
            .field("room_id", &self.room_id)
            .field("kind", &self.kind)
            .field("payload_bytes", &self.payload.len())
            .field("logical_txn_count", &self.logical_txn_count)
            .field("binding_revision", &self.binding_revision)
            .field("generation", &self.generation)
            .field("state", &self.state)
            .field("attempts", &self.attempts)
            .field("next_attempt_at_ms", &self.next_attempt_at_ms)
            .field("lease_until_ms", &self.lease_until_ms)
            .field("created_at_ms", &self.created_at_ms)
            .field("updated_at_ms", &self.updated_at_ms)
            .field("sent_event_id", &self.sent_event_id)
            .field("replaces_event_id", &self.replaces_event_id)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OutboxDisposition {
    Enqueued(OutboxRecord),
    Coalesced(OutboxRecord),
    Duplicate(OutboxRecord),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChangeKind {
    RoomBound,
    RoomThreadBound,
    InboxAccepted,
    InboxDispatchBegun,
    InboxDispatchQueued,
    InboxDispatchAdmitted,
    InboxProcessed,
    InboxRedacted,
    RoomLeft,
    RoomTombstoned,
    OutboxEnqueued,
    OutboxCoalesced,
    OutboxClaimed,
    OutboxRetryScheduled,
    OutboxSent,
    OutboxFailed,
}

impl ChangeKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::RoomBound => "room_bound",
            Self::RoomThreadBound => "room_thread_bound",
            Self::InboxAccepted => "inbox_accepted",
            Self::InboxDispatchBegun => "inbox_dispatch_begun",
            Self::InboxDispatchQueued => "inbox_dispatch_queued",
            Self::InboxDispatchAdmitted => "inbox_dispatch_admitted",
            Self::InboxProcessed => "inbox_processed",
            Self::InboxRedacted => "inbox_redacted",
            Self::RoomLeft => "room_left",
            Self::RoomTombstoned => "room_tombstoned",
            Self::OutboxEnqueued => "outbox_enqueued",
            Self::OutboxCoalesced => "outbox_coalesced",
            Self::OutboxClaimed => "outbox_claimed",
            Self::OutboxRetryScheduled => "outbox_retry_scheduled",
            Self::OutboxSent => "outbox_sent",
            Self::OutboxFailed => "outbox_failed",
        }
    }

    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "room_bound" => Some(Self::RoomBound),
            "room_thread_bound" => Some(Self::RoomThreadBound),
            "inbox_accepted" => Some(Self::InboxAccepted),
            "inbox_dispatch_begun" => Some(Self::InboxDispatchBegun),
            "inbox_dispatch_queued" => Some(Self::InboxDispatchQueued),
            "inbox_dispatch_admitted" => Some(Self::InboxDispatchAdmitted),
            "inbox_processed" => Some(Self::InboxProcessed),
            "inbox_redacted" => Some(Self::InboxRedacted),
            "room_left" => Some(Self::RoomLeft),
            "room_tombstoned" => Some(Self::RoomTombstoned),
            "outbox_enqueued" => Some(Self::OutboxEnqueued),
            "outbox_coalesced" => Some(Self::OutboxCoalesced),
            "outbox_claimed" => Some(Self::OutboxClaimed),
            "outbox_retry_scheduled" => Some(Self::OutboxRetryScheduled),
            "outbox_sent" => Some(Self::OutboxSent),
            "outbox_failed" => Some(Self::OutboxFailed),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChangeEvent {
    pub cursor: u64,
    pub kind: ChangeKind,
    pub room_id: Option<MatrixRoomId>,
    pub event_id: Option<MatrixEventId>,
    pub txn_id: Option<MatrixTransactionId>,
    pub recorded_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChangePage {
    pub events: Vec<ChangeEvent>,
    pub next_cursor: u64,
    pub latest_cursor: u64,
    pub gap: bool,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct MatrixQueueMetrics {
    pub pending_inbox_depth: u64,
    pub pending_dispatch_depth: u64,
    pub pending_outbox_depth: u64,
    pub oldest_inbox_age_ms: Option<u64>,
    pub oldest_dispatch_age_ms: Option<u64>,
    pub oldest_outbox_age_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSnapshot {
    pub owner_agent_id: AgentId,
    pub cursor: u64,
    pub bindings: Vec<RoomBinding>,
    pub room_threads: Vec<RoomThreadBinding>,
    pub pending_inbox: Vec<InboxRecord>,
    pub pending_dispatches: Vec<InboxDispatchRecord>,
    pub pending_outbox: Vec<OutboxRecord>,
    pub metrics: MatrixQueueMetrics,
    pub inbox_truncated: bool,
    pub dispatch_truncated: bool,
    pub outbox_truncated: bool,
}
