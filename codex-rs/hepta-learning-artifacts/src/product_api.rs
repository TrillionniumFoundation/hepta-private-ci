//! Stable product-facing learning-artifact API.
//!
//! Product callers should depend on this facade instead of the crate-root
//! compatibility exports. The facade exposes immutable manifests, authenticated
//! current views, exact pinned loading and independently verified selection. It
//! grants no publication, activation, promotion or release authority.

pub use crate::ArtifactAdmissionError;
pub use crate::ArtifactClosureError;
pub use crate::ArtifactKind;
pub use crate::ArtifactManifest;
pub use crate::ArtifactRecord;
pub use crate::ArtifactRegistrySnapshot;
pub use crate::ArtifactSelectionError;
pub use crate::ArtifactSelectionTrustV1;
pub use crate::ArtifactSelectionVerifierV1;
pub use crate::ArtifactState;
pub use crate::DatasetWithdrawalScopeV1;
pub use crate::LearningArtifactManifestV2;
pub use crate::LineageDisposition;
pub use crate::LoadedPinnedCandidate;
pub use crate::PinnedCandidateLoadError;
pub use crate::PinnedCandidateSpec;
pub use crate::ProvenanceModeV1;
pub use crate::RevalidatingCandidate;
pub use crate::SignedArtifactSelectionV1;
pub use crate::TrustedArtifactSelectorV1;
pub use crate::ValidatedArtifactManifestV2;
pub use crate::VerifiedArtifactSelectionV1;
pub use crate::VerifiedCurrentRegistryViewV1;
pub use crate::admit_manifest_at_withdrawal_head_v3;
pub use crate::load_pinned_candidate;
pub use crate::load_selected_candidate;
pub use crate::record_verified_selection;
pub use crate::validate_artifact_manifest_v2;
pub use crate::validate_artifact_publication_v3;
pub use crate::verify_artifact_admission_v3;
