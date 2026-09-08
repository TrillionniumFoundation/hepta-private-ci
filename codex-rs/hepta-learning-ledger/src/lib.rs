//! Append-only causal learning facts with independent outcomes and revocation
//! lineage.
//!
//! The pure core owns no ambient I/O or execution authority. An opt-in durable
//! adapter writes only learning facts through a host-authorized file handle;
//! it grants no model, tool, network, selection, promotion or release authority.

#![forbid(unsafe_code)]

mod durable;
mod durable_codec;
mod durable_lock;
mod error;
mod ledger;
mod model;
mod shadow;

pub use durable::DurableLedger;
pub use durable::DurableLedgerError;
pub use durable::LedgerAnchor;
pub use durable::LedgerRecovery;
pub use durable::inspect_ledger;
pub use error::LedgerError;
pub use ledger::LearningLedger;
pub use model::AppendDisposition;
pub use model::AppendReceipt;
pub use model::CandidateSetCompleteness;
pub use model::CreditAssignment;
pub use model::EpisodeDecision;
pub use model::LedgerEvent;
pub use model::LedgerRecord;
pub use model::LedgerSnapshot;
pub use model::OutcomeFinality;
pub use model::OutcomeObservation;
pub use model::Revocation;
pub use shadow::ShadowAppendReceipt;
pub use shadow::ShadowDecisionArtifact;
pub use shadow::ShadowDecisionError;
pub use shadow::ShadowDecisionRequest;
pub use shadow::append_shadow_decision;
pub use shadow::canonical_candidate_set_digest;
pub use shadow::prepare_shadow_decision;
