//! Bounded, deletion-aware cognitive compaction and checkpoint qualification.
//!
//! This crate exposes one checkpoint contract and one durable publication
//! boundary. Legacy checkpoint construction and the raw SQLite bundle/store are
//! intentionally not exported. Product callers publish only sealed material
//! verified against an installed, root-authenticated trust manifest.

#![forbid(unsafe_code)]

mod archive_codec;
mod coordinator;
mod durable;
#[allow(unused_imports)]
#[path = "fenced_coordinator_final.rs"]
mod fenced_coordinator;
mod publication;
#[allow(clippy::too_many_arguments)]
mod qualified;
mod trust;
mod trust_registry;

pub use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofWitnessV1;
pub use coordinator::CompactionCoordinatorErrorV2;
pub use coordinator::CompactionPublicationMetricsV2;
pub use coordinator::CompactionPublicationReceiptV2;
pub use coordinator::CompactionReopenMetricsV2;
pub use coordinator::VerifiedCompactionSelectionV2;
// Read-only receipts and fenced outbox claims are safe to expose. Raw bundle,
// trust-set and store construction remain unreachable outside this crate.
pub use durable::DurableCompactionDisposition;
pub use durable::DurableCompactionError;
pub use durable::DurableCompactionOutboxEventV1;
pub use fenced_coordinator::MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2;
pub use fenced_coordinator::MemoryCheckpointCoordinatorV2;
pub use publication::CompactionNonceBindingV1;
pub use publication::CompactionPublicationEvidenceV1;
pub use publication::CompactionPublicationRequestV1;
pub use publication::SignedCompactionTokenAccountingV1;
pub use publication::VerifiedCompactionPublicationV1;
pub use qualified::CompactionInputRecordV2;
pub use qualified::CompactionLossReportV2;
pub use qualified::CompactionPolicyV2;
pub use qualified::CompactionQualificationV2;
pub use qualified::CompactionSemanticPayloadV2;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_BYTES;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::MAX_QUALIFIED_COMPACTION_TOKENS;
pub use qualified::QualifiedCompactionCandidateV2;
pub use qualified::QualifiedCompactionError;
pub use qualified::TokenizationReceiptV1;
pub use trust::COMPACTION_TRUST_SCHEMA_VERSION;
pub use trust::CompactionTrustRoleV1;
pub use trust::QualifiedCandidateBuildRequestV1;
pub use trust::SignedCompactionEvaluationReceiptV1;
pub use trust::SignedRetentionSelectionReceiptV1;
pub use trust::SignedSemanticGenerationReceiptV1;
pub use trust::TrustEnrollmentV1;
pub use trust::TrustedCompactionError;
pub use trust::TrustedCompactionEvaluatorV1;
pub use trust::TrustedCompactionProofRequestV1;
pub use trust::TrustedCompactionProofV1;
pub use trust::TrustedRetentionSelectorV1;
pub use trust::TrustedSemanticGeneratorV1;
pub use trust::TrustedTokenizerV1;
pub use trust::build_qualified_candidate;
pub use trust::compaction_input_manifest_digest;
pub use trust::compaction_qualification_digest;
pub use trust::prove_compaction;
pub use trust_registry::CompactionAdmissionErrorV1;
pub use trust_registry::CompactionTrustedPrincipalV1;
pub use trust_registry::MAX_COMPACTION_TRUST_ENTRIES_V1;
pub use trust_registry::MAX_COMPACTION_TRUST_MANIFEST_BYTES_V1;
pub use trust_registry::SignedCompactionTrustManifestV1;
pub use trust_registry::VerifiedCompactionTrustRegistryV1;

#[cfg(test)]
mod product_e2e_tests;
