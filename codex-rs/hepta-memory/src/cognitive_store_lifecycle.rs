use crate::CognitiveStore;

impl CognitiveStore {
    /// Close the shared SQLite pool and wait for its connections and worker
    /// threads to finish shutting down.
    ///
    /// This closes the pool for every clone of this store. Drain outstanding
    /// operations before awaiting it. The store handles keep their filesystem
    /// recovery fence throughout this wait and until all handles are dropped.
    /// A host handing the database to exact-cut recovery must await this method
    /// and then drop every handle before requesting recovery.
    ///
    /// Cancelling the wait does not reopen the pool. Keep a store handle and
    /// await `close` again before handing off its database. Dropping a store
    /// without completing this wait is not a synchronous SQLite shutdown.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

#[cfg(test)]
#[path = "cognitive_store_lifecycle_tests.rs"]
mod tests;
