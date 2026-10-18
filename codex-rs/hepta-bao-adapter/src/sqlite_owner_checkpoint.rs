//! Existing durable owner checkpoint implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub async fn checkpoint(&self) -> Result<BaoOwnerCheckpointV1, SqliteBaoOwnerErrorV1> {
        let mut tx = self.pool.begin().await.map_err(storage)?;
        let checkpoint = checkpoint_tx(&mut tx).await?;
        tx.commit().await.map_err(storage)?;
        Ok(checkpoint)
    }

    /// Publish the current authoritative checkpoint through a caller-owned,
    /// asynchronous compare-and-swap service. Publication failure fences this
    /// owner so later local commits cannot outrun the external anti-rollback
    /// frontier. The callback receives the previously trusted checkpoint and
    /// the new exact checkpoint; it must reject stale predecessors.
    pub async fn publish_checkpoint_with<F, Fut, E>(
        &self,
        expected_previous: Option<BaoOwnerCheckpointV1>,
        publisher: F,
    ) -> Result<BaoOwnerCheckpointV1, SqliteBaoOwnerErrorV1>
    where
        F: FnOnce(Option<BaoOwnerCheckpointV1>, BaoOwnerCheckpointV1) -> Fut,
        Fut: Future<Output = Result<(), E>>,
    {
        // Hold the SQLite writer reservation until publication resolves. A
        // competing local transaction must not commit beyond the snapshot
        // while its external predecessor is still being decided.
        let mut publication = self.begin().await?;
        let checkpoint = checkpoint_tx(&mut publication).await?;
        // Cancellation is an uncertain external CAS outcome too. Arm the
        // guard before invoking the callback and retain it through unlock.
        let mut publication_fence = OwnerUncertainOutcomeFence {
            owner: self,
            armed: true,
        };
        if publisher(expected_previous, checkpoint).await.is_err() {
            return Err(SqliteBaoOwnerErrorV1::ExternalCheckpointUnavailable);
        }
        publication.rollback().await.map_err(storage)?;
        publication_fence.armed = false;
        Ok(checkpoint)
    }
}
