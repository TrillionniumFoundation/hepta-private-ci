//! Locate immutable input files through the same original CURRENT read-view.
//! These paths are data, not admission capabilities. The caller must open and
//! pin actual descriptors and still use the original selected-artifact loader.

use super::*;

impl LearningArtifactReadViewV1 {
    pub fn locate_selected_original_files(
        &self,
        selector: &crate::ArtifactSelectionVerifierV1,
        selected: &crate::SignedArtifactSelectionV1,
        now: u64,
    ) -> Result<(PathBuf, PathBuf), ArtifactOwnerHostError> {
        let before = self.read_original_registry(now)?;
        let withdrawals = self.read_original_withdrawals()?;
        selector.verify(selected, &before, now)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
        let payload_directory = directory(&self.root, "payloads", self.consumer_uid)?;
        let view = read_view::ArtifactOwnerReadView {
            root: &self.root, verifier: &self.verifier, required_current_head: None,
        };
        let registry = view.registry_snapshot_path(before.receipt());
        // This is the original ensure_payload_durable name, after authenticating
        // the actual registry manifest and independent selection above.
        let payload = self.root.join("payloads").join(format!(
            "{}-{}.bin", selected.artifact_id, selected.content_digest,
        ));
        if fs::canonicalize(&registry)? != registry || fs::canonicalize(&payload)? != payload {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        let after = self.read_original_registry(now)?;
        let withdrawals_after = self.read_original_withdrawals()?;
        if before.receipt() != after.receipt()
            || before.witness_digest() != after.witness_digest()
            || before.trust_digest() != after.trust_digest()
            || withdrawals.scope_digest() != withdrawals_after.scope_digest()
            || withdrawals.head_digest() != withdrawals_after.head_digest()
            || directory(&self.root, "payloads", self.consumer_uid)? != payload_directory
        {
            return Err(ArtifactOwnerHostError::Indeterminate);
        }
        selector.verify(selected, &after, now)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
        Ok((registry, payload))
    }
}
