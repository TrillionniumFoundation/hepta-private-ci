//! Canonical, deletion-aware cognitive compaction engine.
//!
//! The crate intentionally exposes a single checkpoint contract:
//! [`CompactCheckpointV1`]. Construction is only available through the
//! qualified path, so callers cannot bypass tombstone/non-resurrection,
//! provenance, semantic-payload, or qualification invariants.

#![forbid(unsafe_code)]

mod qualified;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use qualified::CompactionEvaluatorEvidenceV1;
pub use qualified::CompactionInputRecordV2;
pub use qualified::CompactionLossReportV2;
pub use qualified::CompactionPolicyV2;
pub use qualified::CompactionQualificationV2;
pub use qualified::MAX_COMPACT_PAYLOAD_BYTES;
pub use qualified::MAX_COMPACT_PAYLOAD_TOKENS;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::QualifiedCompactionCandidateV2;
pub use qualified::QualifiedCompactionError;
pub use qualified::QualifiedCompactionProofV2;
pub use qualified::SemanticCompactionArtifactV1;
pub use qualified::build_qualified_candidate;
pub use qualified::prove_compaction;

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
