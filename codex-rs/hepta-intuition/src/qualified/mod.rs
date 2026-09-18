//! Authenticated current-generation qualification for calibrated intuition.
//!
//! The legacy calibrated API validates structure and binding only. This module
//! adds a cryptographic HMAC-SHA256 trust boundary for the canonical policy
//! profile, calibration/OOD/completeness artifacts, external learned-scorer
//! output, and the exact assignment/randomness plan. MAC keys must come from
//! trusted host configuration, never from the request being admitted.

mod auth;
mod decision;
mod digest;
mod types;

pub use auth::assignment_scope_digest_v1;
pub use auth::calibration_scope_digest_v1;
pub use auth::completeness_scope_digest_v1;
pub use auth::issue_qualification_mac_v1;
pub use auth::ood_scope_digest_v1;
pub use auth::policy_profile_scope_digest_v1;
pub use auth::scorer_output_scope_digest_v1;
#[cfg(test)]
pub(crate) use auth::hmac_sha256;
pub use decision::decide_qualified_v1;
pub use digest::canonical_assignment_digest_v1;
pub use digest::canonical_calibration_artifact_digest_v1;
pub use digest::canonical_completeness_receipt_digest_v1;
pub use digest::canonical_ood_artifact_digest_v1;
pub use digest::canonical_policy_profile_digest_v1;
pub use digest::canonical_scorer_contract_digest_v1;
pub use digest::canonical_scorer_output_digest_v1;
pub use types::CanonicalPolicyProfileV1;
pub use types::LearnedScoreEvidenceV1;
pub use types::LearnedScorerContractV1;
pub use types::QualificationMacKeyV1;
pub use types::QualificationMacV1;
pub use types::QualificationTrustV1;
pub use types::QualifiedArtifactsV1;
pub use types::QualifiedDecisionRequestV1;
pub use types::QualifiedError;
pub use types::QualifiedIntuitionReceiptV1;
pub use types::RiskPolicyV1;

#[cfg(test)]
#[path = "../qualified_tests.rs"]
mod tests;
