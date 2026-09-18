//! Hepta operation semantics and the production-oriented durable operation
//! ledger/outbox.
//!
//! `OperationLedger` and `Outbox` remain deterministic in-memory reference
//! models used as semantic oracles. `DurableOperationStore` is the persistent
//! implementation: it atomically co-commits intent and local outbox state,
//! fences claims with bounded leases, survives reopen, prevents blind retry
//! after dispatch start, supports owner/authority handoff, and reconciles only
//! from trusted terminal observations.
//!
//! Queue acknowledgement is deliberately separate from terminal effect
//! observation. Once dispatch may have crossed an external boundary, the
//! operation cannot be blindly retried; it remains dispatched/indeterminate
//! until a current-fence observer reconciles it.

#![forbid(unsafe_code)]

mod durable;
mod error;
mod ledger;
mod model;
mod outbox;

pub use durable::DispatchEnvelope;
pub use durable::DispatchLease;
pub use durable::DispatchStartDisposition;
pub use durable::DurableOperationRecord;
pub use durable::DurableOperationState;
pub use durable::DurableOperationStore;
pub use durable::EffectObservation;
pub use durable::MAX_DURABLE_ACTIVE_OPERATIONS;
pub use durable::MAX_DURABLE_CLAIM_BATCH;
pub use durable::MAX_DURABLE_OUTBOX_ATTEMPTS;
pub use durable::MAX_DURABLE_OUTBOX_LEASE_MS;
pub use durable::PreparedIntent;
pub use durable::execute_with_final_use;
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
