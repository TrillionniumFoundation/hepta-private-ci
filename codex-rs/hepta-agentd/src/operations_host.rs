//! Product composition seam for `kernel.operations`.
//!
//! Opening the host establishes the Agent-local durable owner store. It grants
//! no effect authority: callers must still supply a current owner generation,
//! claim a lease, and consume a real final-use authority token through the
//! returned dispatcher before crossing an external effect boundary.

use std::sync::Arc;

use codex_hepta_operations::DurableDispatcher;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Clone)]
pub struct AgentdOperationsHost {
    store: Arc<DurableOperationStore>,
}

impl AgentdOperationsHost {
    pub async fn open(identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let sqlite_home = AbsolutePathBuf::from_absolute_path(&identity.home_root)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let sqlite = SqliteConfig::from_sqlite_home(sqlite_home);
        let store = DurableOperationStore::open(&sqlite)
            .await
            .map_err(|error| AgentdError::Protocol(format!("open kernel.operations store: {error}")))?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    pub fn store(&self) -> Arc<DurableOperationStore> {
        Arc::clone(&self.store)
    }

    pub fn dispatcher(&self, owner_generation: u64) -> Result<DurableDispatcher, AgentdError> {
        let owner_generation = Generation::new(owner_generation)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let worker_id = StableId::new("runtime.agentd:kernel.operations")
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        DurableDispatcher::new(
            self.store.as_ref().clone(),
            worker_id,
            owner_generation,
            30_000,
        )
        .map_err(|error| AgentdError::Protocol(error.to_string()))
    }
}
