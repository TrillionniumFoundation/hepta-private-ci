//! A fenced publication predecessor is not an eligible CURRENT view. Fresh
//! writer authority can extend authentic expired history without renewing it.
use super::*;

impl LearningArtifactOwnerHost {
    pub(crate) fn open_for_fresh_evidence_publication(
        root: impl AsRef<Path>,
        trust: ArtifactOwnerTrustV1,
        lease: SignedArtifactWriterLeaseV1,
        retained_head: SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<Self, ArtifactOwnerHostError> {
        let mut host = Self::open_internal(root, trust, lease, Some(retained_head), now)?;
        host.publication_ancestor_enabled = true;
        host.discover_publication_predecessor(now)?;
        Ok(host)
    }

    pub(crate) fn discover_publication_predecessor(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        // Every historical publication lookup still requires the actual
        // current writer lease and the same exclusive host lifetime fence.
        self.require_current_writer(now)?;
        if self.publication_ancestor_enabled {
            self.read_context().discover_publication_ancestor(now)
        } else {
            self.discover_current_head(now)
        }
    }

    pub(crate) fn recover_publication_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        let current = self
            .discover_publication_predecessor(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadRollback)?;
        let context = self.read_context();
        let receipt = context.current_registry_receipt(&current)?;
        let registry = read_registry_snapshot(
            File::open(context.registry_snapshot_path(receipt))?,
            receipt,
        )?;
        if registry.head_digest() != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        context.validate_current_registry_inventory(&registry)?;
        Ok(registry)
    }
}
