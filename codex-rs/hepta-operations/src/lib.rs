//! Canonical operation identity plus bounded reference and standalone durable semantics.
//!
//! `OperationIntentV1` is the canonical cross-owner semantic identity. The
//! in-memory reference models `OperationLedger` and `Outbox` provide deterministic
//! oracles and do not provide durable storage.
//!
//! `DurableOperationStore` is the standalone durable qualification owner. It is
//! used for fault-matrix, recovery and migration qualification where one isolated
//! SQLite database owns both the source ledger and source outbox. It is not the
//! Agentd product owner and must never dual-write one logical operation with the
//! CognitiveStore-backed production path.
//!
//! The Agentd product owner is CognitiveStore through
//! `hepta_memory::ProductionDurableWriter`; that owner atomically binds canonical
//! `OperationIntentV1`, local event/outbox state, final-use dispatch claims and
//! destination terminal observations. `DestinationDedupeStore` remains a reusable
//! destination-owner helper for stores whose domain mutation and dedupe proof can
//! share one transaction.

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
mod sqlite;

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
/// Standalone-store record shape used only by `DurableOperationStore`.
///
/// Product callers must construct canonical [`OperationIntentV1`] and enter the
/// CognitiveStore-backed `ProductionDurableWriter`; no implicit conversion or
/// dual-write bridge exists.
pub use durable_model::OperationIntentV1 as DurableOperationIntentV1;
pub use durable_model::OutboxStatusV1;
pub use durable_model::PrepareDisposition;
pub use durable_model::PreparedIntent;
pub use durable_model::ReconciliationReceiptV1;
pub use durable_store::AuthorizedDispatch;
pub use durable_store::DurableOperationStore;
pub use error::OperationError;
pub use ledger::MAX_MODEL_OPERATION_RECORDS;
pub use ledger::OperationLedger;
pub use model::OPERATION_INTENT_V1_SCHEMA_VERSION;
pub use model::OperationIntentV1;
pub use model::OperationKey;
pub use model::OperationRecord;
pub use model::OperationState;
pub use model::ReconciliationOutcome;
pub use model::ReferenceAuthorityWitness;
pub use outbox::MAX_MODEL_OUTBOX_ATTEMPTS;
pub use outbox::MAX_MODEL_OUTBOX_RECORDS;
pub use outbox::Outbox;
pub use outbox::OutboxIntent;
pub use outbox::OutboxState;

#[cfg(test)]
mod exact_claim_tests;
#[cfg(test)]
mod fault_tests;
