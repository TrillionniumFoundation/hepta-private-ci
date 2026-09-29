//! Withdrawal-aware final-use admission for already published artifacts.
//!
//! A signed CURRENT registry view proves which immutable registry is current. It
//! does not by itself retain the V2 dataset lineage that a withdrawal registry
//! needs. This additive view combines the opaque CURRENT view with the complete
//! V3 admission and revalidates that admission against the owner's current
//! withdrawal frontier immediately before use.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactManifest;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;
use crate::ValidatedArtifactManifestV2;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::validate_artifact_publication_v3;

pub struct VerifiedCurrentArtifactUseV1 {
    current: VerifiedCurrentRegistryViewV1,
    admission: WithdrawalBoundArtifactAdmissionV3,
    withdrawal_head_digest: Digest32,
}

impl VerifiedCurrentArtifactUseV1 {
    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.admission.validated_manifest.manifest.artifact_id
    }

    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 {
        self.admission.admission_digest
    }

    #[must_use]
    pub const fn withdrawal_head_digest(&self) -> Digest32 {
        self.withdrawal_head_digest
    }

    #[must_use]
    pub const fn registry_head_digest(&self) -> Digest32 {
        self.current.receipt().head_digest
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        VerifiedCurrentRegistryViewV1,
        WithdrawalBoundArtifactAdmissionV3,
    ) {
        (self.current, self.admission)
    }
}

impl fmt::Debug for VerifiedCurrentArtifactUseV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedCurrentArtifactUseV1")
            .field("artifact_id", self.artifact_id())
            .field("admission_digest", &self.admission_digest())
            .field("withdrawal_head_digest", &self.withdrawal_head_digest)
            .field("registry_head_digest", &self.registry_head_digest())
            .finish_non_exhaustive()
    }
}

impl LearningArtifactOwnerService {
    /// Issue a final-use view only when the complete V3 admission remains valid
    /// at the current durable withdrawal frontier and agrees with the exact
    /// artifact projection in signed CURRENT.
    pub fn current_artifact_use_view(
        &self,
        admission: WithdrawalBoundArtifactAdmissionV3,
        now: u64,
    ) -> Result<VerifiedCurrentArtifactUseV1, CurrentArtifactUseError> {
        validate_artifact_publication_v3(&admission, self.withdrawal_registry(), now)?;
        let current = self.current_registry_view(now)?;
        let v2 = &admission.validated_manifest;
        let projected = current
            .registry()
            .manifest(&v2.manifest.artifact_id)
            .ok_or(CurrentArtifactUseError::ProjectionMismatch)?;
        if !projection_matches(projected, v2)
            || !current.registry().is_eligible(&v2.manifest.artifact_id)
        {
            return Err(CurrentArtifactUseError::ProjectionMismatch);
        }
        Ok(VerifiedCurrentArtifactUseV1 {
            current,
            withdrawal_head_digest: admission.withdrawal_head_digest,
            admission,
        })
    }
}

pub(crate) fn projection_matches(
    projected: &ArtifactManifest,
    admitted: &ValidatedArtifactManifestV2,
) -> bool {
    let v2 = &admitted.manifest;
    projected.artifact_id == v2.artifact_id
        && projected.kind == v2.kind
        && projected.generation == v2.generation
        && projected.content_digest == v2.bytes_digest
        && projected.producer_id == v2.producer_id
        && projected.compatibility_digest == v2.compatibility_digest
        && projected.encoded_size_bytes == v2.encoded_size_bytes
        && projected.objective_digest == v2.objective_class_digest
        && projected.support_digest == admitted.manifest_digest
}

#[derive(Debug)]
pub enum CurrentArtifactUseError {
    Owner(LearningArtifactOwnerServiceError),
    Admission(ArtifactAdmissionError),
    ProjectionMismatch,
}

impl fmt::Display for CurrentArtifactUseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Owner(error) => write!(formatter, "artifact owner final-use check failed: {error}"),
            Self::Admission(error) => {
                write!(formatter, "artifact withdrawal admission is not current: {error}")
            }
            Self::ProjectionMismatch => formatter.write_str(
                "complete artifact admission does not match the signed current registry projection",
            ),
        }
    }
}

impl StdError for CurrentArtifactUseError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Owner(error) => Some(error),
            Self::Admission(error) => Some(error),
            Self::ProjectionMismatch => None,
        }
    }
}

impl From<LearningArtifactOwnerServiceError> for CurrentArtifactUseError {
    fn from(value: LearningArtifactOwnerServiceError) -> Self {
        Self::Owner(value)
    }
}

impl From<ArtifactAdmissionError> for CurrentArtifactUseError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}
