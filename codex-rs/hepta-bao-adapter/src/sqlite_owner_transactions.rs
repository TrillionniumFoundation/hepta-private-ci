//! Existing durable owner transactions implementation.

use super::*;

impl SqliteBaoOwnerV1 {
    pub(super) fn ensure_writable(&self) -> Result<(), SqliteBaoOwnerErrorV1> {
        if self.is_fenced() {
            Err(SqliteBaoOwnerErrorV1::Fenced)
        } else {
            Ok(())
        }
    }

    pub(super) async fn begin(
        &self,
    ) -> Result<Transaction<'static, Sqlite>, SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        let started = Instant::now();
        let result = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage);
        if let Ok(mut metrics) = self.runtime_metrics.lock() {
            metrics.record_begin_wait(started);
        }
        let tx = result?;
        // The writer may have waited behind a failed checkpoint publisher or
        // uncertain commit. Recheck after acquiring the database reservation.
        self.ensure_writable()?;
        Ok(tx)
    }

    pub(super) async fn commit(
        &self,
        tx: Transaction<'static, Sqlite>,
    ) -> Result<(), SqliteBaoOwnerErrorV1> {
        self.ensure_writable()?;
        let started = Instant::now();
        let mut commit_fence = OwnerUncertainOutcomeFence {
            owner: self,
            armed: true,
        };
        let result = tx.commit().await;
        commit_fence.armed = false;
        match result {
            Ok(()) => {
                if let Ok(mut metrics) = self.runtime_metrics.lock() {
                    metrics.record_commit(started, true);
                }
                Ok(())
            }
            Err(error) => {
                self.fenced.store(true, Ordering::Release);
                if let Ok(mut metrics) = self.runtime_metrics.lock() {
                    metrics.record_commit(started, false);
                }
                Err(SqliteBaoOwnerErrorV1::CommitIndeterminate(
                    error.to_string(),
                ))
            }
        }
    }
}
