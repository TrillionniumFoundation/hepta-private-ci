//! One owner's checkpoint serialization, independent of ordinary read polling.

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::unavailable;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    /// Retain the original SQLite write lock before validating this owner's
    /// durable Dirty permission. Checkout alone is insufficient: a connection
    /// may wait behind a later Current publication before its transaction starts.
    /// The lock excludes another publication until this transaction ends; the
    /// existing commit hook still rejects a permanent fence at the final COMMIT.
    pub(crate) async fn begin_write_transaction(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        let transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if self.commit_gate.is_managed() {
            let Some(coordinator) = &self.bound_publication else {
                drop(self.commit_gate.transition_attempt());
                return Err(CognitiveStoreError::Unavailable(
                    "managed owner has no bound write coordinator".to_string(),
                ));
            };
            coordinator.prepare_write().await.map_err(unavailable)?;
        }
        self.commit_gate.require_open()?;
        Ok(transaction)
    }

    pub(crate) async fn begin_checkpoint_barrier(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        if let Some(barrier) = &self.checkpoint_barrier {
            return barrier.begin().await.map_err(unavailable);
        }
        if self.commit_gate.is_managed() {
            // A managed owner with no serialization capability must never
            // continue writing after it failed to acknowledge its whole cut.
            drop(self.commit_gate.transition_attempt());
            return Err(CognitiveStoreError::Unavailable(
                "managed owner has no checkpoint serialization connection".to_string(),
            ));
        }
        self.pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)
    }
}
