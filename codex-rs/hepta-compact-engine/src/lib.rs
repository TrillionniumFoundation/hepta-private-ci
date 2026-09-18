//! Bounded, deletion-aware cognitive compaction and checkpoint qualification.
//!
//! This crate exposes one checkpoint contract: the canonical Lane C
//! `CompactCheckpointV1`.  Legacy checkpoint construction is intentionally not
//! exported; every checkpoint must pass the same lineage, deletion, budget and
//! qualification path.

#![forbid(unsafe_code)]

mod qualified;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
pub use qualified::CompactionInputRecordV2;
pub use qualified::CompactionLossReportV2;
pub use qualified::CompactionPolicyV2;
pub use qualified::CompactionQualificationV2;
pub use qualified::CompactionSemanticPayloadV2;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::QualifiedCompactionCandidateV2;
pub use qualified::QualifiedCompactionError;
pub use qualified::build_qualified_candidate;
pub use qualified::prove_compaction;
