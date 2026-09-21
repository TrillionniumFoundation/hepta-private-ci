//! Canonical Hepta operation, outbox and reconciliation semantics.
//!
//! The in-memory `OperationLedger` / `Outbox` remain deterministic reference
//! models. `DurableOperationStore` is the kernel-owned SQLite implementation
//! for crash/reopen-safe operation identity, immutable transition history and
//! leased outbox state.
//!
//! Queue acknowledgement is deliberately separate from terminal effect
//! observation. Once dispatch may have crossed an external boundary, the
//! operation cannot be blindly retried; it remains indeterminate until a
//! current-generation observer reconciles it.
//!
//! This crate does not mint authority or dispatch external effects. Product
//! adapters must authenticate independently and consume final-use authority
//! immediately before the actual downstream boundary.

#![forbid(unsafe_code)]

mod durable;
mod error;
mod ledger;
mod model;
mod outbox;

pub use durable::DurableOperationError;
pub use durable::DurableOperationStore;
pub use durable::DurableOutboxState;
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
pub use outbox::MAX_MODEL_OUTBOX_RECORDS;
pub use outbox::Outbox;
pub use outbox::OutboxIntent;
pub use outbox::OutboxState;
