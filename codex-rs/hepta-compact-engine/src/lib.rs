//! Bounded, deletion-aware cognitive compaction and checkpoint qualification.
//!
//! This crate exposes one checkpoint contract: the canonical Lane C
//! `CompactCheckpointV1`. Legacy checkpoint construction is intentionally not
//! exported. The only public construction path requires an authoritative
//! snapshot plus versioned signed selector, generator, tokenizer and evaluator
//! trust receipts.

#![forbid(unsafe_code)]

#[allow(clippy::too_many_arguments)]
mod qualified;
mod trust;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofWitnessV1;
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
