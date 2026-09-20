//! Hepta operation, durable-ledger/outbox, and reconciliation semantics.
//!
//! Queue acknowledgement is deliberately separate from terminal effect
//! observation. Once dispatch may have crossed an external boundary, the
//! operation cannot be blindly retried; it remains indeterminate until a
//! current-fence observer reconciles it.
//!
//! The SQLite-backed durable owner provides crash/reopen persistence for the
//! operation ledger and generation-fenced outbox. The in-memory `OperationLedger`
//! and `Outbox` remain deterministic reference models. This crate still does not
//! authenticate callers, mint/consume final-use authority on its own, dispatch a
//! background effect, or establish production activation.

#![forbid(unsafe_code)]

mod durable;
mod error;
mod ledger;
mod model;
mod outbox;

pub use durable::DurableOperationBinding;
pub use durable::DurableOutboxRecord;
pub use durable::DurableOutboxState;
pub use durable::MAX_DURABLE_OUTBOX_PAYLOAD_BYTES;
pub use durable::DurableOperationLedger;
pub use durable::DurableOperationRecord;
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
