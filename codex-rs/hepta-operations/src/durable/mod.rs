mod codec;
mod dispatcher;
mod model;
mod reconcile;
mod store;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_types::StableId;
#[cfg(test)]
use codex_hepta_types::Digest32;
#[cfg(test)]
use codex_hepta_types::Generation;
#[cfg(test)]
use codex_state::SqliteConfig;

pub use dispatcher::DispatchBoundaryResult;
pub use dispatcher::DurableDispatcher;
pub use model::DestinationReceipt;
pub use model::DispatchLease;
pub use model::DurableOperationRecord;
pub use model::DurableOperationState;
pub use model::DurableOutboxState;
pub use model::DurableOutboxStatus;
pub use model::OperationsMetrics;
pub use model::PrepareOperationIntent;
pub use store::DurableOperationStore;

pub const MAX_DURABLE_OPERATION_RECORDS: i64 = 100_000;
pub const MAX_OPERATION_CLAIM_BATCH: u32 = 256;
pub const MAX_OPERATION_ATTEMPTS: u32 = 32;
pub const MAX_OPERATION_LEASE_MS: i64 = 60_000;

#[derive(Debug, thiserror::Error)]
pub enum DurableOperationError {
    #[error("invalid durable operation request: {0}")]
    Invalid(&'static str),
    #[error("durable operation identity conflict: {0}")]
    Conflict(StableId),
    #[error("durable operation is missing: {0}")]
    Missing(StableId),
    #[error("durable operation store capacity exceeded")]
    Capacity,
    #[error("dispatch lease is stale")]
    StaleLease,
    #[error("operation crossed an effect boundary and requires reconciliation")]
    ReconciliationRequired,
    #[error("durable operation is unavailable in its current state")]
    UnavailableState,
    #[error("durable operation store is corrupt: {0}")]
    Corrupt(String),
    #[error("durable operation store is unavailable: {0}")]
    Unavailable(String),
    #[error("final-use authority rejected the dispatch: {0}")]
    Authority(#[from] FinalUseError),
}

pub(crate) fn unavailable(error: impl std::fmt::Display) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
mod tests;
