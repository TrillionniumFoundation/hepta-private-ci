//! Loss-bounded, deletion-aware memory/context compaction.
//!
//! The crate exposes one canonical checkpoint contract from cognitive-types.
//! Legacy record-only checkpoint construction was removed because it could
//! bypass deletion/non-resurrection and qualification invariants.

#![forbid(unsafe_code)]

mod qualified;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use qualified::CompactionInputRecordV3;
pub use qualified::CompactionLossReportV3;
pub use qualified::CompactionPlanV3;
pub use qualified::CompactionPolicyV3;
pub use qualified::CompactionProofV2;
pub use qualified::CompactionQualificationV3;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_BYTES;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::MAX_QUALIFIED_COMPACTION_TOKENS;
pub use qualified::QualifiedCompactionCandidateV3;
pub use qualified::QualifiedCompactionError;
pub use qualified::SemanticCompactionReceiptV1;
pub use qualified::TrustedCompactionEvaluatorV1;
pub use qualified::build_qualified_candidate;
pub use qualified::plan_compaction;
pub use qualified::prove_compaction;
