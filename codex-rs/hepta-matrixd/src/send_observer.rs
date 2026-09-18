#![forbid(unsafe_code)]

use std::future::Future;

use codex_hepta_matrix_store::MatrixDurableStore;

pub use codex_hepta_matrix_store::MatrixDispatchError as Error;
pub use codex_hepta_matrix_store::SendIntent;
pub use codex_hepta_matrix_store::SendReceipt;
pub use codex_hepta_matrix_store::SendState;
pub use codex_hepta_matrix_store::ServerObservation;

/// Thin owner-local facade over the canonical durable Matrix dispatch ledger.
///
/// This component intentionally owns no second sender and no process-local
/// delivery truth. Every transition is persisted by `MatrixDurableStore`.
#[derive(Clone)]
pub struct MatrixSendObserver {
    store: MatrixDurableStore,
}

impl MatrixSendObserver {
    pub fn new(store: MatrixDurableStore) -> Self {
        Self { store }
    }

    pub fn store(&self) -> &MatrixDurableStore {
        &self.store
    }

    pub fn prepare_send(
        &self,
        now_ms: u64,
        intent: SendIntent,
    ) -> impl Future<Output = Result<SendReceipt, Error>> + '_ {
        async move { self.store.prepare_send(now_ms, &intent).await }
    }

    pub fn observe_send(
        &self,
        observation: ServerObservation,
    ) -> impl Future<Output = Result<SendReceipt, Error>> + '_ {
        async move { self.store.observe_send(&observation).await }
    }

    pub fn apply_redaction<'a>(
        &'a self,
        server_event_id: &'a str,
        redaction_digest: &'a str,
        observed_at_ms: u64,
    ) -> impl Future<Output = Result<SendReceipt, Error>> + 'a {
        async move {
            self.store
                .apply_send_redaction(server_event_id, redaction_digest, observed_at_ms)
                .await
        }
    }

    pub fn receipt<'a>(
        &'a self,
        operation_id: &'a str,
    ) -> impl Future<Output = Result<Option<SendReceipt>, Error>> + 'a {
        async move { self.store.send_receipt(operation_id).await }
    }
}

#[cfg(test)]
#[path = "send_observer_tests.rs"]
mod tests;
