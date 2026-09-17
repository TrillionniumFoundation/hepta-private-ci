#![forbid(unsafe_code)]

use std::future::Future;

use codex_hepta_matrix_store::MatrixDispatchIntent;
use codex_hepta_matrix_store::MatrixDispatchReceipt;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixEventId;
use codex_hepta_matrix_store::MatrixRoomId;
use codex_hepta_matrix_store::MatrixTransactionId;

pub use codex_hepta_matrix_store::MatrixDispatchState as SendState;
pub type SendIntent = MatrixDispatchIntent;
pub type SendReceipt = MatrixDispatchReceipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ServerObservation {
    pub transaction_id: MatrixTransactionId,
    pub server_event_id: MatrixEventId,
    pub room_id: MatrixRoomId,
    pub binding_revision: u64,
    pub session_generation: u64,
    pub observation_digest: String,
    pub observed_at_ms: u64,
}

/// Reusable façade over the canonical MatrixDurableStore dispatch ledger.
///
/// This type deliberately owns no map, queue, sender, or independent durable
/// state. The existing matrixd runtime remains the sole sender and the store
/// remains the sole source of dispatch truth across restart/reconciliation.
pub struct MatrixSendObserver<'a> {
    store: &'a MatrixDurableStore,
}

impl<'a> MatrixSendObserver<'a> {
    pub fn new(store: &'a MatrixDurableStore) -> Self {
        Self { store }
    }

    pub fn prepare_send(
        &self,
        now_ms: u64,
        intent: &SendIntent,
    ) -> impl Future<Output = Result<SendReceipt, MatrixDurableError>> + '_ {
        let intent = intent.clone();
        async move { self.store.prepare_matrix_dispatch(now_ms, &intent).await }
    }

    pub fn observe_send(
        &self,
        observation: &ServerObservation,
    ) -> impl Future<Output = Result<Option<SendReceipt>, MatrixDurableError>> + '_ {
        let observation = observation.clone();
        async move {
            self.store
                .observe_matrix_server_event(
                    Some(&observation.transaction_id),
                    &observation.server_event_id,
                    &observation.room_id,
                    observation.binding_revision,
                    observation.session_generation,
                    &observation.observation_digest,
                    observation.observed_at_ms,
                )
                .await
        }
    }

    pub async fn apply_redaction(
        &self,
        server_event_id: &MatrixEventId,
        redaction_event_id: &MatrixEventId,
        redaction_digest: &str,
        observed_at_ms: u64,
    ) -> Result<Option<SendReceipt>, MatrixDurableError> {
        self.store
            .observe_matrix_redaction(
                server_event_id,
                redaction_event_id,
                redaction_digest,
                observed_at_ms,
            )
            .await
    }

    pub async fn receipt(
        &self,
        transaction_id: &MatrixTransactionId,
    ) -> Result<Option<SendReceipt>, MatrixDurableError> {
        self.store.matrix_dispatch_receipt(transaction_id).await
    }
}

#[cfg(test)]
#[path = "send_observer_tests.rs"]
mod tests;
