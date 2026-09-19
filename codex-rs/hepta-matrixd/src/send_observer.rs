#![forbid(unsafe_code)]

use std::future::Future;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
pub use codex_hepta_matrix_store::MatrixDispatchAuthority;
pub use codex_hepta_matrix_store::MatrixDispatchRecord;
pub use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;

/// Compatibility seam for the channel.matrix implementation map.
///
/// There is deliberately no in-memory observer owner here. The canonical
/// stable transaction and every dispatch/observation transition live in the
/// same MatrixDurableStore that owns the outbox.
pub fn prepare_send<'a>(
    store: &'a MatrixDurableStore,
    outbox: &'a OutboxRecord,
    authority: &'a MatrixDispatchAuthority,
    now_ms: u64,
) -> impl Future<Output = Result<MatrixDispatchRecord, MatrixDurableError>> + 'a {
    store.prepare_matrix_dispatch(outbox, authority, now_ms)
}

/// Record a trusted homeserver event observation. HTTP/API acceptance is not
/// terminal success and therefore does not call this function.
pub fn observe_send<'a>(
    store: &'a MatrixDurableStore,
    txn_id: Option<&'a MatrixTransactionId>,
    event_id: &'a MatrixEventId,
    room_id: &'a MatrixRoomId,
    observation_digest: &'a str,
    now_ms: u64,
) -> impl Future<Output = Result<Option<MatrixDispatchRecord>, MatrixDurableError>> + 'a {
    store.observe_matrix_dispatch_succeeded(txn_id, event_id, room_id, observation_digest, now_ms)
}

/// Redaction is a later terminal observation and keeps the original send
/// observation digest immutable in the durable ledger.
pub fn observe_redaction<'a>(
    store: &'a MatrixDurableStore,
    event_id: &'a MatrixEventId,
    redaction_digest: &'a str,
    now_ms: u64,
) -> impl Future<Output = Result<Option<MatrixDispatchRecord>, MatrixDurableError>> + 'a {
    store.observe_matrix_dispatch_redacted(event_id, redaction_digest, now_ms)
}

#[cfg(test)]
#[path = "send_observer_tests.rs"]
mod tests;
