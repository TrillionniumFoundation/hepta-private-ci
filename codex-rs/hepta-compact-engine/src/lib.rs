//! Canonical bounded cognitive compaction and checkpoint qualification.
//!
//! The crate intentionally exposes a single checkpoint contract:
//! `CompactCheckpointV1` from Lane C. Legacy checkpoint construction has been
//! removed from the public surface so deletion, provenance, budget and proof
//! invariants cannot be bypassed through a weaker parallel API.

#![forbid(unsafe_code)]

mod qualified;

pub use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
pub use codex_hepta_cognitive_types::lane_c::CompactionProofV2;
pub use qualified::CompactionInputRecordV2;
pub use qualified::CompactionLossReportV2;
pub use qualified::CompactionPolicyV2;
pub use qualified::CompactionQualificationV2;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::MAX_RETAINED_COMPACTION_BYTES;
pub use qualified::MAX_RETAINED_COMPACTION_TOKENS;
pub use qualified::QualifiedCompactionCandidateV2;
pub use qualified::QualifiedCompactionError;
pub use qualified::build_qualified_candidate;
pub use qualified::prove_compaction;
