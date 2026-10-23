//! One owner's checkpoint serialization, independent of ordinary read polling.

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::unavailable;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    pub(crate) async fn begin_checkpoint_barrier(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        if let Some(barrier) = &self.checkpoint_barrier {
            return barrier.begin().await.map_err(unavailable);
        }
        if self.commit_gate.is_managed() {
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
