//! Curated compatibility facade for production integrations.
//!
//! Low-level encoders, repair helpers and internal host state remain outside
//! this module. The facade is intentionally smaller than the crate root so
//! downstream products can pin a stable contract while the implementation
//! continues to evolve.

pub const LEARNING_ARTIFACTS_STABLE_FACADE: &str =
    "hepta.learning-artifacts.stable.v1";

pub use crate::ArtifactPublicationReceiptV1;
pub use crate::ArtifactSelectionVerifierV1;
pub use crate::DirectoryDurabilityProfileV1;
pub use crate::LearningArtifactOwnerService;
pub use crate::LearningArtifactOwnerServiceConfigV1;
pub use crate::LearningArtifactOwnerServiceError;
pub use crate::LearningArtifactPublishRequestV1;
pub use crate::SignedArtifactSelectionV1;
pub use crate::VerifiedArtifactSelectionV1;
pub use crate::VerifiedCurrentRegistryViewV1;
pub use crate::directory_durability_profile_v1;
