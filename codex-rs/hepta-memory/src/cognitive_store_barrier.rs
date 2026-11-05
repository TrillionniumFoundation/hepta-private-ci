//! One owner's checkpoint serialization, independent of ordinary read polling.

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::unavailable;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    /// Refresh the protected Dirty acknowledgement only after taking the actual
    /// SQLite writer lock. A checkout may have waited behind a publication that
    /// closed its earlier commit permission while BEGIN IMMEDIATE was queued.
    pub(crate) async fn begin_write_transaction(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        self.commit_gate.require_open()?;
        let transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if let Some(publication) = &self.bound_publication {
            publication.begin_writes().await.map_err(unavailable)?;
        } else if self.commit_gate.is_managed() {
            drop(self.commit_gate.transition_attempt());
            return Err(CognitiveStoreError::Unavailable(
                "managed writer has no bound checkpoint coordinator".to_string(),
            ));
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
