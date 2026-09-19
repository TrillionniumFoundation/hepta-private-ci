//! Append-only causal learning facts with independent outcomes and revocation
//! lineage.
//!
//! The pure core owns no ambient I/O or execution authority. An opt-in durable
//! adapter writes only learning facts through a host-authorized file handle;
//! it grants no model, tool, network, selection, promotion or release authority.

#![forbid(unsafe_code)]

mod causal_v2;
mod checkpoint;
mod dataset_receipt_v3;
mod durable;
mod durable_codec;
mod durable_lock;
mod error;
mod journal;
mod ledger;
mod model;
mod protocol_adapters;
mod segment_codec;
mod segments;
mod shadow;
mod signed_evidence;
mod trust_root;
mod witness;
mod writer;

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
pub use checkpoint::LedgerIndexCheckpointError;
pub use checkpoint::LedgerIndexCheckpointV1;
pub use checkpoint::generate_index_checkpoint;
pub use checkpoint::verify_index_checkpoint;
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
pub use model::AuthenticatedDecisionV2;
pub use model::AuthenticatedOutcomeV2;
pub use model::CandidateSetCompleteness;
pub use model::CreditAllocationBatchV2;
pub use model::CreditAssignment;
pub use model::DurableCreditAllocationV1;
pub use model::DurableOutcomeTerminalityV2;
pub use model::EpisodeDecision;
pub use model::LedgerEvent;
pub use model::LedgerRecord;
pub use model::LedgerSnapshot;
pub use model::OutcomeFinality;
pub use model::OutcomeObservation;
pub use model::Revocation;
pub use model::UnlearningLineageEventV1;
pub use protocol_adapters::CanonicalJsonProtocol;
pub use protocol_adapters::CreditAllocationV1Wire;
pub use protocol_adapters::CreditAssignmentReceiptV1;
pub use protocol_adapters::DatasetSnapshotV1;
pub use protocol_adapters::EpisodeOutcomeWatermarkV1;
pub use protocol_adapters::LearningDecisionV1;
pub use protocol_adapters::LearningEpisodeTerminalityV1;
pub use protocol_adapters::LearningEpisodeV1;
pub use protocol_adapters::OutcomeCensoringV1;
pub use protocol_adapters::OutcomeReceiptV1;
pub use protocol_adapters::ProtocolAdapterError;
pub use protocol_adapters::credit_batch_to_canonical_receipt;
pub use protocol_adapters::dataset_receipt_to_canonical_v1;
pub use protocol_adapters::decision_to_canonical_v1;
pub use protocol_adapters::episode_to_canonical_v1;
pub use protocol_adapters::outcome_to_canonical_v1;
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
pub use trust_root::LearningTrustRootV1;
pub use trust_root::SignedLearningTrustManifestV1;
pub use trust_root::TrustRootError;
pub use trust_root::VerifiedLearningTrustManifestV1;
pub use trust_root::trust_manifest_signing_bytes;
pub use trust_root::verify_learning_trust_manifest;
pub use witness::IndependentLedgerWitness;
pub use witness::WitnessError;
pub use writer::DatasetFreezePlanV1;
pub use writer::LedgerWriter;
pub use writer::LedgerWriterError;
pub use writer::UnlearningLineageReceiptV1;
pub use writer::UnlearningLineageRequestV1;
pub use writer::decision_evidence_payload;
pub use writer::outcome_evidence_payload;
pub use writer::unlearning_evidence_payload;

#[cfg(test)]
#[path = "convergence_tests.rs"]
mod convergence_tests;

#[cfg(test)]
#[path = "shadow_tests.rs"]
mod shadow_tests;
