//! Durable, per-agent Matrix ingress and egress state.
//!
//! This crate deliberately contains no Matrix SDK, App Server, supervisor, or
//! execution authority. It only owns a bounded, restart-safe local queue and
//! the typed identities needed to drive it.

#![forbid(unsafe_code)]

mod model;
mod store;

pub use codex_hepta_matrix_protocol::MatrixEventId;
pub use codex_hepta_matrix_protocol::MatrixRoomId;
pub use codex_hepta_matrix_protocol::MatrixTransactionId;
pub use codex_hepta_matrix_protocol::MatrixUserId;
pub use model::ChangeEvent;
pub use model::ChangeKind;
pub use model::ChangePage;
pub use model::InboxAdmissionDraft;
pub use model::InboxDispatchRecord;
pub use model::InboxDispatchState;
pub use model::InboxDisposition;
pub use model::InboxDraft;
pub use model::InboxQueuedDraft;
pub use model::InboxRecord;
pub use model::InboxState;
pub use model::MatrixControlPage;
pub use model::MatrixControlSnapshot;
pub use model::MatrixDurableConfig;
pub use model::MatrixQueueMetrics;
pub use model::MatrixSnapshot;
pub use model::MatrixSyncCheckpoint;
pub use model::MatrixSyncCommit;
pub use model::OutboxDisposition;
pub use model::OutboxDraft;
pub use model::OutboxKind;
pub use model::OutboxRecord;
pub use model::OutboxState;
pub use model::PendingApprovalDraft;
pub use model::PendingApprovalKind;
pub use model::PendingApprovalRecord;
pub use model::RoomBinding;
pub use model::RoomBindingDraft;
pub use model::RoomThreadBinding;
pub use model::RoomThreadBindingDraft;
pub use store::MatrixDurableError;
pub use store::MatrixDurableStore;
// Native channel.matrix owner-local observations, not an inter-module wire API.
#[doc(hidden)]
pub use store::MatrixSyncUnchangedRequestV1;
#[doc(hidden)]
pub use store::MatrixSyncUnchangedResultV1;
