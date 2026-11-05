//! Revalidate the original protected Dirty receipt under SQLite write exclusion.

use super::CognitiveStore;
use super::CognitiveStoreError;
use super::unavailable;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    /// A checkout can wait behind a later Current publication. Only after
    /// BEGIN IMMEDIATE succeeds can this writer revalidate its permission.
    /// Publication uses the same SQLite -> receipt-coordinator lock order.
    /// The coordinator never obtains a SQLite connection while locked.
    pub(crate) async fn begin_owner_write(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, CognitiveStoreError> {
        let started = tokio::time::Instant::now();
        self.commit_gate.require_open()?;
        let publication = if self.commit_gate.is_managed() {
            Some(self.bound_owner_publication().ok_or_else(|| {
                // A managed owner without its original coordinator cannot
                // silently fall back to an unmanaged write path.
                let _attempt = self.commit_gate.transition_attempt();
                CognitiveStoreError::Unavailable(
                    "managed owner has no bound write coordinator".to_string(),
                )
            })?)
        } else {
            None
        };
        // The complete managed admission uses one original bound duration:
        // pool checkout, SQLite lock wait and Dirty ACK share this deadline.
        // A caller's earlier timeout still cancels this same future.
        let end = publication.map(|owner| started + owner.deadline());
        let admission = async {
            let transaction = self
                .pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(unavailable)?;
            if let Some(publication) = publication {
                // This nested guard is declared after the transaction. On
                // cancellation/error it fences before the SQLite lock drops.
                // No source mutation has begun at this admission boundary.
                let attempt = self.commit_gate.checkpoint_attempt();
                publication.begin_writes().await.map_err(unavailable)?;
                self.commit_gate.require_open()?;
                if !self.commit_gate.commit_allowed() {
                    return Err(CognitiveStoreError::Unavailable(
                        "protected owner did not acknowledge Dirty under the write lock"
                            .to_string(),
                    ));
                }
                attempt.acknowledge();
            }
            // Keep the original whole-pool commit hook as the final boundary.
            Ok(transaction)
        };
        match end {
            Some(end) => tokio::time::timeout_at(end, admission)
                .await
                .map_err(unavailable)?,
            None => admission.await,
        }
    }
}
