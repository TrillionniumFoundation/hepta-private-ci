//! Authority-neutral canonical execution records and an evidence-chain validator.
//!
//! This crate cannot execute commands, mint approvals, verify signatures, or grant
//! FinalUse. A trusted, independent host must implement the verification ports
//! before accepting a start or an effect receipt. The in-memory journal is not
//! a replacement for a durable, authenticated production evidence ledger.

#![forbid(unsafe_code)]

mod journal;
mod record;

pub use journal::EffectReceiptVerifier;
pub use journal::ExecutionJournal;
pub use journal::ExecutionVerifier;
pub use record::ApprovalRequest;
pub use record::CompletionStatus;
pub use record::Currentness;
pub use record::EffectReceipt;
pub use record::ExecutionBinding;
pub use record::ExecutionCancelled;
pub use record::ExecutionClass;
pub use record::ExecutionCompleted;
pub use record::ExecutionError;
pub use record::ExecutionIntent;
pub use record::ExecutionOutputChunk;
pub use record::ExecutionReconciled;
pub use record::ExecutionRecord;
pub use record::ExecutionReservation;
pub use record::ExecutionStarted;
pub use record::FinalUse;
pub use record::ReconciliationStatus;
pub use record::EXECUTION_SCHEMA_VERSION;
pub use record::MAX_EXECUTION_RECORD_BYTES;

#[cfg(test)]
#[path = "journal_tests.rs"]
mod tests;
