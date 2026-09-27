//! Bounded, deletion-aware cognitive compaction and checkpoint qualification.
//!
//! This crate exposes one checkpoint contract: the canonical Lane C
//! `CompactCheckpointV1`. Legacy checkpoint construction is intentionally not
//! exported. Durable publication must use an installed, root-authenticated
//! trust registry and replayable verified publication material.

#![forbid(unsafe_code)]

mod archive_codec;
mod durable;
mod publication;
#[allow(clippy::too_many_arguments)]
mod qualified;
mod trust;
mod trust_registry;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofWitnessV1;
pub use durable::CompactionArtifactImagesV1;
pub use durable::DURABLE_COMPACTION_SCHEMA_VERSION;
pub use durable::DurableCompactionBundleV1;
pub use durable::DurableCompactionDisposition;
pub use durable::DurableCompactionError;
pub use durable::DurableCompactionOutboxEventV1;
pub use durable::DurableCompactionPublicationReceiptV1;
pub use durable::DurableCompactionSelectionV1;
pub use durable::DurableCompactionStoreV1;
pub use durable::DurableCompactionTrustSetV1;
pub use durable::MAX_DURABLE_COMPACTION_ARTIFACT_BYTES;
pub use durable::MAX_DURABLE_COMPACTION_OUTBOX_PAYLOAD_BYTES;
pub use durable::MEMORY_CHECKPOINT_COORDINATOR_CALLER;
pub use durable::MemoryCheckpointCoordinatorV1;
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
