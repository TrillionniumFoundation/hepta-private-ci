//! One owner's checkpoint serialization, independent of ordinary read polling.

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::unavailable;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    /// Admit mutations only after the original SQLite writer lock is held.
    /// A checkout can precede a queued BEGIN and a newer Current publication.
    /// Reconfirming Dirty here keeps that publication from closing permission
    /// between write admission and COMMIT; the commit hook remains mandatory.
    pub(crate) async fn begin_write_transaction(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        let transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if self.commit_gate.is_managed() {
            let Some(checkpoint) = self.bound_owner_publication() else {
                drop(self.commit_gate.transition_attempt());
                return Err(CognitiveStoreError::Unavailable(
                    "managed owner has no bound write coordination capability".to_string(),
                ));
            };
            checkpoint.prepare_write().await;
            self.commit_gate.require_open()?;
        }
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
