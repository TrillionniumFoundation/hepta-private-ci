//! Selected-version recovery uses the existing selection digest and owner root.
//! These immutable records do not choose a release or authorize an effect. A
//! host retains the selected digest in its own durable configuration/run record.
use super::*;
use crate::ArtifactSelectionVerifierV1;
use crate::SignedArtifactSelectionV1;

impl LearningArtifactOwnerHost {
    /// Persist the complete independently signed selection after checking the
    /// actual CURRENT and payload. The returned digest is the existing canonical
    /// selection identity, suitable for a durable host configuration pin.
    pub fn persist_selected_descriptor(
        &self,
        selector: &ArtifactSelectionVerifierV1,
        selection: &SignedArtifactSelectionV1,
        now: u64,
    ) -> Result<Digest32, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        self.read_current_selected_payload(selector, selection, now)?;
        let bytes = selection.persisted_bytes();
        if bytes.len() > MAX_SMALL_RECORD_BYTES {
            return Err(ArtifactOwnerHostError::Capacity);
        }
        let digest = Digest32::of_bytes(&bytes);
        write_create_only_or_exact(&self.selection_path(digest), &bytes)?;
        Ok(digest)
    }

    /// Reopen exactly the pinned selection; do not scan for a replacement, train
    /// another model, or accept the descriptor's historical view as CURRENT.
    pub fn read_selected_descriptor(
        &self,
        selector: &ArtifactSelectionVerifierV1,
        digest: Digest32,
        now: u64,
    ) -> Result<SignedArtifactSelectionV1, ArtifactOwnerHostError> {
        let bytes = read_small_record(&self.selection_path(digest), MAX_SMALL_RECORD_BYTES)?;
        if digest.is_zero() || Digest32::of_bytes(&bytes) != digest {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        let selection = SignedArtifactSelectionV1::from_persisted_bytes(&bytes)
            .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
        let current = self.current_registry_view(now)?;
        selector
            .verify(&selection, &current, now)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadConflict)?;
        Ok(selection)
    }

    fn selection_path(&self, digest: Digest32) -> PathBuf {
        self.root
            .join("transactions")
            .join(format!("{digest}.selection"))
    }
}
