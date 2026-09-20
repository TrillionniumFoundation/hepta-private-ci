//! In-memory reference model for Hepta operation, outbox and reconciliation
//! semantics.
//!
//! Queue acknowledgement is deliberately separate from terminal effect
//! observation. Once dispatch may have crossed an external boundary, the
//! operation cannot be blindly retried; it remains indeterminate until a
//! current-fence observer reconciles it.
//!
//! This crate does not provide durable storage, crash/reopen recovery, a
//! background dispatcher or production authority. Product code must not infer
//! durability from cloning this model.

#![forbid(unsafe_code)]

mod error;
mod ledger;
mod model;
mod outbox;

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
