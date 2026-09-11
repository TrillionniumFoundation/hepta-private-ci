//! Append-only causal learning facts with independent outcomes and revocation
//! lineage.
//!
//! The pure core owns no ambient I/O or execution authority. An opt-in durable
//! adapter writes only learning facts through a host-authorized file handle;
//! it grants no model, tool, network, selection, promotion or release authority.

#![forbid(unsafe_code)]

mod causal_v2;
mod durable;
mod durable_codec;
mod durable_lock;
mod error;
mod ledger;
mod model;
mod shadow;

pub use causal_v2::AuthenticatedOutcomeV1;
pub use causal_v2::AuthenticatedPrincipalV1;
pub use causal_v2::CandidateSetCompletenessReceiptV1;
pub use causal_v2::CausalV2Error;
pub use causal_v2::CreditAllocationBatchV1;
pub use causal_v2::CreditAllocationReceiptV1;
pub use causal_v2::CreditAllocationV1;
pub use causal_v2::DatasetFreezeRequestV1;
pub use causal_v2::DatasetSnapshotV2;
pub use causal_v2::OutcomeTerminalityV1;
pub use causal_v2::OutcomeWatermarkV1;
pub use causal_v2::finalize_credit_batch;
pub use causal_v2::freeze_dataset;
pub use causal_v2::validate_authenticated_outcome;
pub use causal_v2::validate_candidate_set_completeness;
pub use causal_v2::verify_independent_roles;
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

#[cfg(test)]
#[path = "shadow_tests.rs"]
mod shadow_tests;
