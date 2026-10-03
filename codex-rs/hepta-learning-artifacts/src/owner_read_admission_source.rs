//! Read complete legacy admissions through their actual authenticated owner.
//! The original two-name layout remains immutable. General custody readers
//! still require a single link; callers can publish these verified whole bytes.
use super::*;
use crate::admission_storage::MAX_ARTIFACT_ADMISSION_BYTES;
use crate::admission_storage::encode_artifact_admission;
use crate::read_artifact_admission_by_digest;
use std::os::unix::fs::MetadataExt;

impl ReadOnlyArtifactCurrentOwnerV1 {
    /// Return only the original complete admission at this owner's exact
    /// manifest-index path, bound to current eligibility and both original pins.
    /// No writer lease, repair, signer or mutable storage handle is obtained.
    pub fn read_current_manifest_admission_source(
        &self,
        path: &Path,
        file_digest: Digest32,
        admission_digest: Digest32,
        now: u64,
    ) -> Result<Vec<u8>, ArtifactOwnerHostError> {
        let current = self.current_registry_view(now)?;
        if file_digest.is_zero()
            || admission_digest.is_zero()
            || path.parent() != Some(self.root.join("admissions").as_path())
            || path.extension().and_then(|part| part.to_str()) != Some("manifest")
        {
            return Err(ArtifactOwnerHostError::PathBoundary);
        }
        let before = fs::symlink_metadata(path)?;
        let admission = read_artifact_admission_by_digest(File::open(path)?, admission_digest)?;
        let bytes = encode_artifact_admission(&admission)?;
        let full = &admission.validated_manifest;
        let manifest = current
            .eligible_manifest(&full.manifest.artifact_id)
            .ok_or(ArtifactOwnerHostError::ProvenanceMismatch)?;
        let expected_path = self
            .root
            .join("admissions")
            .join(format!("{}.manifest", full.manifest_digest));
        if path != expected_path
            || manifest.support_digest != full.manifest_digest
            || admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
            || Digest32::of_bytes(&bytes) != file_digest
            || read_small_record(path, MAX_ARTIFACT_ADMISSION_BYTES)? != bytes
        {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        if before.nlink() == 2 {
            let alias = self
                .root
                .join("admissions")
                .join(format!("{admission_digest}.bin"));
            let alias_metadata = fs::symlink_metadata(alias)?;
            if before.dev() != alias_metadata.dev()
                || before.ino() != alias_metadata.ino()
                || alias_metadata.nlink() != 2
            {
                return Err(ArtifactOwnerHostError::PathBoundary);
            }
        }
        let after = fs::symlink_metadata(path)?;
        if before.dev() != after.dev()
            || before.ino() != after.ino()
            || before.nlink() != after.nlink()
            || self.current_registry_view(now)?.receipt() != current.receipt()
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(bytes)
    }
}
