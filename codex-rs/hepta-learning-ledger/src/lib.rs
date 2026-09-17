//! Append-only causal learning facts with independent outcomes and revocation
//! lineage.
//!
//! The pure core owns no ambient I/O or execution authority. An opt-in durable
//! adapter writes only learning facts through a host-authorized file handle;
//! it grants no model, tool, network, selection, promotion or release authority.

#![forbid(unsafe_code)]

mod acknowledged;
mod causal_v2;
mod composed;
mod credit_commit;
mod dataset_from_ledger;
mod dataset_receipt_v3;
mod durable;
mod durable_codec;
mod durable_lock;
mod error;
mod journal;
mod ledger;
mod model;
mod segment_codec;
mod segments;
mod shadow;
mod signed_evidence;
mod witness;

pub use acknowledged::AcknowledgedLearningJournal;
pub use acknowledged::WitnessedLearningLedger;
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
pub use composed::AuthenticatedDecisionCommitV1;
pub use composed::AuthenticatedOutcomeCommitV1;
pub use composed::CausalLearningWriterV1;
pub use composed::ComposedLearningError;
pub use composed::credit_evidence_payload_v1;
pub use composed::dataset_evidence_payload_v1;
pub use composed::decision_evidence_payload_v1;
pub use composed::episode_role_payload_v1;
pub use composed::outcome_evidence_payload_v1;
pub use credit_commit::DurableCreditBatchError;
pub use credit_commit::DurableCreditBatchReceiptV1;
pub use credit_commit::append_conserved_credit_batch_v1;
pub use dataset_from_ledger::LedgerDerivedDatasetError;
pub use dataset_from_ledger::LedgerDerivedDatasetPlanV1;
pub use dataset_from_ledger::freeze_dataset_from_ledger_v3;
pub use dataset_receipt_v3::DatasetReceiptError;
pub use dataset_receipt_v3::DatasetSnapshotReceiptV3;
pub use dataset_receipt_v3::freeze_dataset_receipt_v3;
pub use dataset_receipt_v3::verify_dataset_snapshot_receipt_v3;
pub use durable::DurableLedger;
pub use durable::DurableLedgerError;
pub use durable::LedgerAnchor;
pub use durable::LedgerRecovery;
pub use durable::inspect_ledger;
pub use error::LedgerError;
pub use journal::DurableLearningJournal;
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
pub use segments::LedgerSegmentCheckpoint;
pub use segments::LedgerSegmentLimits;
pub use segments::MAX_LEDGER_SEGMENTS;
pub use segments::SegmentedLedger;
pub use segments::inspect_ledger_segments;
pub use shadow::ShadowAppendReceipt;
pub use shadow::ShadowDecisionArtifact;
pub use shadow::ShadowDecisionError;
pub use shadow::ShadowDecisionRequest;
pub use shadow::append_shadow_decision;
pub use shadow::canonical_candidate_set_digest;
pub use shadow::prepare_shadow_decision;
pub use signed_evidence::LearningEvidenceRoleV1;
pub use signed_evidence::LearningEvidenceTrustV1;
pub use signed_evidence::LearningEvidenceVerifierV1;
pub use signed_evidence::SignedEvidenceError;
pub use signed_evidence::SignedLearningEvidenceV1;
pub use signed_evidence::TrustedLearningSignerV1;
pub use signed_evidence::VerifiedLearningEvidenceV1;
pub use signed_evidence::verify_signed_role_separation;
pub use witness::LedgerWitnessStore;

#[cfg(test)]
#[path = "shadow_tests.rs"]
mod shadow_tests;
