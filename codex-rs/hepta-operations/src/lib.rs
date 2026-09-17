//! Durable operation ledger, transactional cross-owner outbox and deterministic
//! reference semantics for Hepta effects.
//!
//! `OperationLedger` and `Outbox` remain bounded in-memory reference models for
//! transition-oracle tests. `DurableOperationStore` is the SQLite-backed owner
//! for production composition: operation intent and outbox publication share
//! one transaction, leases are fenced and recoverable, unknown effects become
//! indeterminate, and terminal settlement requires authoritative observation.
//! External effect authority remains owned by `kernel.authority` and is consumed
//! through `DurableDispatcher` immediately at adapter entry.

#![forbid(unsafe_code)]

mod destination_dedupe;
mod dispatcher;
mod durable;
mod error;
mod ledger;
mod model;
mod outbox;

pub use destination_dedupe::DESTINATION_DEDUPE_SCHEMA_V1;
pub use destination_dedupe::DestinationDedupeKey;
pub use destination_dedupe::DestinationReservation;
pub use destination_dedupe::finish_destination_effect;
pub use destination_dedupe::reserve_destination_effect;
pub use dispatcher::DestinationEffectAdapter;
pub use dispatcher::DispatchEnvelope;
pub use dispatcher::DispatchResult;
pub use dispatcher::DurableDispatchError;
pub use dispatcher::DurableDispatcher;
pub use durable::DEFAULT_BUSY_TIMEOUT_MS;
pub use durable::DispatchLease;
pub use durable::DurableIntent;
pub use durable::DurableOperationError;
pub use durable::DurableOperationState;
pub use durable::DurableOperationStatus;
pub use durable::DurableOperationStore;
pub use durable::DurableOutboxState;
pub use durable::DurableOutboxStatus;
pub use durable::MAX_DURABLE_ATTEMPTS;
pub use durable::MAX_DURABLE_CLAIM_BATCH;
pub use durable::MAX_DURABLE_LEASE_MS;
pub use durable::MAX_DURABLE_OPERATION_ROWS;
pub use durable::MAX_DURABLE_OUTBOX_ROWS;
pub use durable::MAX_DURABLE_RETRY_DELAY_MS;
pub use durable::OperationIdentity;
pub use durable::OperationMetrics;
pub use durable::RecoveryReport;
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
