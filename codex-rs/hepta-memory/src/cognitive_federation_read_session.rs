//! Operation-owned read-only connections. Idle federation readers retain no
//! SQLite handles; cancellation retains the generation fence through cleanup.
use codex_hepta_paths::HeptaAgentLayout;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio::runtime::Handle;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::cognitive_store::CognitiveStoreReadGeneration;
use crate::cognitive_store::unavailable;

pub(super) struct FederatedReadSession {
    pub(super) owner: CognitiveStore,
    generation: Option<CognitiveStoreReadGeneration>,
    runtime: Handle,
}

impl FederatedReadSession {
    pub(super) async fn open(
        layout: &HeptaAgentLayout,
        generation: CognitiveStoreReadGeneration,
    ) -> Result<Self, CognitiveStoreError> {
        let runtime = Handle::try_current().map_err(unavailable)?;
        let path = generation.database_path().to_path_buf();
        let home = AbsolutePathBuf::try_from(layout.cognitive_root().to_path_buf())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let pool = SqliteConfig::from_sqlite_home(home).lazy_read_only_pool(&path);
        // The cancellation cleanup owner exists before the first connection I/O.
        let session = Self {
            owner: CognitiveStore::from_read_only_pool(pool, layout.agent_id().clone(), path),
            generation: Some(generation),
            runtime,
        };
        let initialized = async {
            sqlx::query("PRAGMA query_only = ON")
                .execute(&session.owner.pool)
                .await
                .map_err(unavailable)?;
            let query_only: i64 = sqlx::query_scalar("PRAGMA query_only")
                .fetch_one(&session.owner.pool)
                .await
                .map_err(unavailable)?;
            if query_only != 1 {
                return Err(CognitiveStoreError::Corrupt(
                    "federated cognitive connection is not query-only".to_string(),
                ));
            }
            Ok(())
        }
        .await;
        if let Err(error) = initialized {
            session.close().await;
            return Err(error);
        }
        Ok(session)
    }

    pub(super) async fn close(mut self) {
        self.owner.pool.close().await;
        drop(self.generation.take());
    }
}

impl Drop for FederatedReadSession {
    fn drop(&mut self) {
        if let Some(generation) = self.generation.take() {
            let pool = self.owner.pool.clone();
            // Cleanup issues no new query and cannot deliver evidence. Keeping
            // the fence here prevents recovery while SQLite drains old handles.
            drop(self.runtime.spawn(async move {
                pool.close().await;
                drop(generation);
            }));
        }
    }
}

#[cfg(test)]
#[path = "cognitive_federation_read_session_tests.rs"]
mod tests;
