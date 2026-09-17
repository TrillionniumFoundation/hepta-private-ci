//! Hepta operation ledger, transactional outbox and reconciliation semantics.
//!
//! The original bounded in-memory model remains as a deterministic oracle. The
//! durable surface adds a FULL-synchronous SQLite ledger/outbox aggregate with
//! atomic intent publication, fenced pre-dispatch leases, crash/reopen recovery,
//! non-retryable indeterminate dispatches, terminal reconciliation and bounded
//! terminal retention. Queue acknowledgement is deliberately separate from
//! terminal effect observation.
//!
//! Product activation still requires a named caller, destination-owned durable
//! deduplication and a trusted terminal observer. The final-use dispatcher binds
//! the non-serializable token owned by `kernel.authority` immediately around the
//! adapter entry; this crate does not mint authority.

#![forbid(unsafe_code)]

mod dispatcher;
mod durable_model;
mod durable_store;
mod error;
mod ledger;
mod model;
mod outbox;

pub use dispatcher::EffectAdapter;
pub use dispatcher::ReconciliationObservation;
pub use dispatcher::TerminalObserver;
pub use durable_model::ArmedDispatch;
pub use durable_model::DEFAULT_TERMINAL_RETAINED_ROWS;
pub use durable_model::DEFAULT_TERMINAL_RETENTION_MS;
pub use durable_model::DispatchClaim;
pub use durable_model::DispatchLease;
pub use durable_model::DispatchObservation;
pub use durable_model::DurableOperationIntent;
pub use durable_model::DurableOperationMetrics;
pub use durable_model::DurableOperationRecord;
pub use durable_model::DurableOperationState;
pub use durable_model::DurableOutboxRecord;
pub use durable_model::DurableOutboxState;
pub use durable_model::DurableStoreConfig;
pub use durable_model::MAX_DURABLE_ACTIVE_OPERATIONS;
pub use durable_model::MAX_DURABLE_CLAIM_BATCH;
pub use durable_model::MAX_DURABLE_LEASE_MS;
pub use durable_model::MAX_DURABLE_OUTBOX_ATTEMPTS;
pub use durable_model::MAX_DURABLE_OUTBOX_ROWS;
pub use durable_store::DurableOperationStore;
pub use error::OperationError;
pub use ledger::MAX_MODEL_OPERATION_RECORDS;
pub use ledger::OperationLedger;
pub use model::OperationKey;
pub use model::OperationRecord;
pub use model::OperationState;
pub use model::ReconciliationOutcome;
pub use model::ReferenceAuthorityWitness;
pub use outbox::MAX_MODEL_OUTBOX_RECORDS;
pub use outbox::Outbox;
pub use outbox::OutboxIntent;
pub use outbox::OutboxState;

#[cfg(test)]
#[path = "durable_tests.rs"]
mod durable_tests;
