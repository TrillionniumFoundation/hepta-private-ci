//! Durable and reference operation, outbox and reconciliation semantics.
//!
//! `OperationLedger` and `Outbox` remain deterministic in-memory reference
//! models. `DurableOperationStore` is the production-oriented SQLite owner: it
//! atomically co-commits operation intent and source outbox state, fences claims,
//! fails closed after unknown effects, and requires independent terminal
//! reconciliation. Destination owners can use `DestinationDedupeStore` against
//! their own migrated SQLite pool so dedupe and domain mutation share one
//! transaction.

#![forbid(unsafe_code)]

mod destination_dedupe;
mod dispatcher;
mod durable_model;
mod durable_store;
mod error;
mod exact_claim;
mod ledger;
mod model;
mod outbox;

pub use destination_dedupe::DestinationApplyStart;
pub use destination_dedupe::DestinationApplyTransaction;
pub use destination_dedupe::DestinationDedupeStore;
pub use dispatcher::DurableDispatcher;
pub use durable_model::DestinationApplyDisposition;
pub use durable_model::DestinationApplyReceipt;
pub use durable_model::DestinationOperationIdentity;
pub use durable_model::DispatchClaim;
pub use durable_model::DispatchEffect;
pub use durable_model::DurableOperationError;
pub use durable_model::DurableOperationRecord;
pub use durable_model::DurableOperationState;
pub use durable_model::DurableOutboxState;
pub use durable_model::MAX_DURABLE_CLAIM_BATCH;
pub use durable_model::MAX_DURABLE_LEASE_MS;
pub use durable_model::MAX_DURABLE_OUTBOX_ATTEMPTS;
pub use durable_model::MAX_DURABLE_PENDING_OPERATIONS;
pub use durable_model::OperationBacklogMetrics;
pub use durable_model::OperationIntentV1;
pub use durable_model::OutboxStatusV1;
pub use durable_model::PrepareDisposition;
pub use durable_model::PreparedIntent;
pub use durable_model::ReconciliationReceiptV1;
pub use durable_store::AuthorizedDispatch;
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
mod exact_claim_tests;
#[cfg(test)]
mod fault_tests;
