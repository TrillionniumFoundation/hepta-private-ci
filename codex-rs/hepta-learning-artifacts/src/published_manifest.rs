//! Exact V2 source binding behind the stable V1 publication index.

use crate::ArtifactAdmissionError;
use crate::ArtifactManifest;
use crate::ArtifactPublicationError;
use crate::LearningArtifactManifestV2;
use crate::ValidatedArtifactManifestV2;
use crate::validate_artifact_manifest_v2;

/// Reconstruct the full source manifest selected by a named publication.
/// The signed V1 index commits to the canonical V2 manifest in support_digest;
/// that field is not the dataset digest. No authority is inferred from this
/// check: independent selection and CURRENT revalidation remain necessary.
pub fn validate_published_artifact_manifest_v2(
    indexed: &ArtifactManifest,
    source: LearningArtifactManifestV2,
    now: u64,
) -> Result<ValidatedArtifactManifestV2, ArtifactPublicationError> {
    let validated = validate_artifact_manifest_v2(source, now).map_err(|error| {
        ArtifactPublicationError::Admission(ArtifactAdmissionError::Manifest(error))
    })?;
    if indexed != &project_published_manifest_v2(&validated) {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    }
    Ok(validated)
}

pub(crate) fn project_published_manifest_v2(
    validated: &ValidatedArtifactManifestV2,
) -> ArtifactManifest {
    let source = &validated.manifest;
    ArtifactManifest {
        artifact_id: source.artifact_id.clone(),
        kind: source.kind,
        generation: source.generation,
        predecessor_id: if source.predecessor_ids.len() == 1 {
            source.predecessor_ids.first().cloned()
        } else {
            None
        },
        content_digest: source.bytes_digest,
        objective_digest: source.objective_class_digest,
        support_digest: validated.manifest_digest,
        producer_id: source.producer_id.clone(),
        compatibility_digest: source.compatibility_digest,
        encoded_size_bytes: source.encoded_size_bytes,
    }
}
