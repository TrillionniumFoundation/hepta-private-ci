//! Host-only preparation through the existing writer's complete V2 provenance.
//! The host authenticates the source notice before calling this method; only
//! the original signed publication and durable ACK commit the returned suffix.
use super::*;
use crate::DatasetRevocationRequest;
use crate::PreparedDatasetRevocation;

impl LearningArtifactOwnerService {
    /// Resolve exact dataset membership from authenticated CURRENT sidecars.
    /// Retain the resulting suffix with the original publication request for
    /// recovery. Re-preparing after revocation is not an exact retry.
    pub fn prepare_dataset_revocation_from_current(
        &self,
        request: &DatasetRevocationRequest,
        now: u64,
    ) -> Result<PreparedDatasetRevocation, LearningArtifactOwnerServiceError> {
        let current = self.current_registry_view(now)?;
        let targets = self
            .registry
            .records()
            .iter()
            .filter_map(|record| match &record.event {
                ArtifactEvent::Register { manifest, .. } => current
                    .supports_dataset(manifest, request.dataset_digest)
                    .then(|| manifest.artifact_id.clone()),
                ArtifactEvent::Quarantine(_) | ArtifactEvent::Revoke(_) => None,
            })
            .collect();
        Ok(crate::dataset_revocation::prepare_targets(
            &self.registry,
            current.receipt().head_digest,
            request,
            targets,
            crate::publication_registry_suffix::MAX_PUBLICATION_STATE_CHANGES,
        )?)
    }
}
