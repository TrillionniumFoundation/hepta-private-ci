//! Operation, outbox and reconciliation semantics for Hepta.
//!
//! The `OperationLedger`/`Outbox` pair remains the bounded **In-memory reference model**
//! used as a deterministic transition oracle; that reference model **does not provide durable storage**.
//! `DurableOperationStore` is the SQLite-backed owner for production composition.
//! Queue or transport acknowledgement is deliberately separate from terminal effect
//! observation. Once dispatch may have crossed an external boundary, the operation
//! cannot be blindly retried; it remains dispatched/indeterminate until a
//! current-fence observer reconciles it.

#![forbid(unsafe_code)]

mod durable;
mod error;
mod ledger;
mod model;
mod outbox;

pub use durable::DestinationReceipt;
pub use durable::DispatchBoundaryResult;
pub use durable::DispatchLease;
pub use durable::DurableDispatcher;
pub use durable::DurableOperationError;
pub use durable::DurableOperationRecord;
pub use durable::DurableOperationState;
pub use durable::DurableOperationStore;
pub use durable::DurableOutboxState;
pub use durable::DurableOutboxStatus;
pub use durable::OperationsMetrics;
pub use durable::PrepareOperationIntent;
pub use durable::MAX_DURABLE_OPERATION_RECORDS;
pub use durable::MAX_OPERATION_ATTEMPTS;
pub use durable::MAX_OPERATION_CLAIM_BATCH;
pub use durable::MAX_OPERATION_LEASE_MS;
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
