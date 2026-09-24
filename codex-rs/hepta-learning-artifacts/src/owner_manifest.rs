//! Full V2 metadata lives under the same owner, addressed by the V1 support hash.
//! Publishing or recovering it does not change CURRENT or select an artifact.
use super::*;
use crate::ValidatedArtifactManifestV2;
use crate::closure_v2::MAX_ENCODED_MANIFEST_BYTES;
use crate::closure_v2::decode_manifest;
use crate::closure_v2::encode_manifest;

impl LearningArtifactOwnerHost {
    pub(super) fn persist_publication_manifest(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        let validated = &transaction.intent().admission.validated_manifest;
        let bytes = encode_manifest(&validated.manifest)
            .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
        if Digest32::of_bytes(&bytes) != validated.manifest_digest {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        write_bounded_create_only_or_exact(
            &self.manifest_path(validated.manifest_digest),
            &bytes,
            MAX_ENCODED_MANIFEST_BYTES,
        )
    }

    /// Resolve full metadata from the live, independently selected registry entry.
    /// Legacy entries missing the exact V2 bytes fail closed; never infer lineage
    /// or expiry from the lossy compatibility projection or the model payload.
    pub fn read_current_selected_manifest(
        &self,
        selector: &crate::ArtifactSelectionVerifierV1,
        selection: &crate::SignedArtifactSelectionV1,
        now: u64,
    ) -> Result<ValidatedArtifactManifestV2, ArtifactOwnerHostError> {
        let current = self.current_registry_view(now)?;
        let verified = selector
            .verify(selection, &current, now)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadConflict)?;
        self.read_registered_manifest(verified.manifest(), now)
    }

    pub(super) fn read_registered_manifest(
        &self,
        index: &ArtifactManifest,
        now: u64,
    ) -> Result<ValidatedArtifactManifestV2, ArtifactOwnerHostError> {
        let bytes = read_small_record(
            &self.manifest_path(index.support_digest),
            MAX_ENCODED_MANIFEST_BYTES,
        )?;
        if Digest32::of_bytes(&bytes) != index.support_digest {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        let validated =
            decode_manifest(&bytes, now).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
        let manifest = &validated.manifest;
        let predecessor = match manifest.predecessor_ids.as_slice() {
            [id] => Some(id.clone()),
            _ => None,
        };
        if validated.manifest_digest != index.support_digest
            || manifest.artifact_id != index.artifact_id
            || manifest.kind != index.kind
            || manifest.generation != index.generation
            || manifest.bytes_digest != index.content_digest
            || manifest.objective_class_digest != index.objective_digest
            || manifest.compatibility_digest != index.compatibility_digest
            || manifest.producer_id != index.producer_id
            || manifest.encoded_size_bytes != index.encoded_size_bytes
            || predecessor != index.predecessor_id
        {
            return Err(ArtifactOwnerHostError::IdentityConflict);
        }
        Ok(validated)
    }

    fn manifest_path(&self, digest: Digest32) -> PathBuf {
        self.root
            .join("transactions")
            .join(format!("{digest}.manifest-v2"))
    }
}
