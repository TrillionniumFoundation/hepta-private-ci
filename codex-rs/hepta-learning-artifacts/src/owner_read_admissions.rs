//! Complete V2 provenance read without publication authority.
use super::admissions::CurrentArtifactProvenance;
use super::*;
use crate::read_artifact_admission_by_digest;
use crate::read_artifact_admission_by_manifest_digest;
use std::collections::BTreeSet;
impl ArtifactOwnerReadContext<'_> {
    pub(super) fn validate_checkpoint_admission(
        &self,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    ) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactOwnerHostError> {
        let path = self
            .root
            .join("admissions")
            .join(format!("{}.bin", checkpoint.admission_digest));
        let admission =
            read_artifact_admission_by_digest(File::open(path)?, checkpoint.admission_digest)?;
        if admission.withdrawal_scope_digest != checkpoint.withdrawal_scope_digest
            || admission.withdrawal_head_digest != checkpoint.withdrawal_head_digest
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let indexed = read_artifact_admission_by_manifest_digest(
            File::open(self.manifest_admission_path(admission.validated_manifest.manifest_digest))?,
            admission.validated_manifest.manifest_digest,
        )?;
        if indexed.validated_manifest != admission.validated_manifest
            || indexed.withdrawal_scope_digest != admission.withdrawal_scope_digest
        {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        Ok(admission)
    }
    pub(super) fn validate_parent_provenance(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        registry: &ArtifactRegistry,
    ) -> Result<(), ArtifactOwnerHostError> {
        let child = &admission.validated_manifest.manifest;
        for predecessor_id in &child.predecessor_ids {
            let parent = registry
                .manifest(predecessor_id)
                .ok_or(ArtifactOwnerHostError::ProvenanceMismatch)?;
            if !registry.is_eligible(predecessor_id)
                || parent.generation >= child.generation
                || parent.kind != child.kind
                || parent.objective_digest != child.objective_class_digest
            {
                return Err(ArtifactOwnerHostError::ProvenanceMismatch);
            }
            let stored = self.read_manifest_admission(parent)?;
            if stored.withdrawal_scope_digest != admission.withdrawal_scope_digest
                || !stored
                    .validated_manifest
                    .manifest
                    .source_dataset_digests
                    .iter()
                    .all(|dataset| child.source_dataset_digests.contains(dataset))
            {
                return Err(ArtifactOwnerHostError::ProvenanceMismatch);
            }
        }
        Ok(())
    }
    pub(super) fn current_provenance(
        &self,
        registry: &ArtifactRegistry,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<CurrentArtifactProvenance, ArtifactOwnerHostError> {
        if withdrawals.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest) {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        let mut ineligible = BTreeSet::new();
        let mut source_datasets = BTreeMap::new();
        for record in registry.records() {
            let ArtifactEvent::Register { manifest, .. } = &record.event else {
                continue;
            };
            if !registry.is_eligible(&manifest.artifact_id) {
                continue;
            }
            let admission = self.read_manifest_admission(manifest)?;
            if admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest {
                return Err(ArtifactOwnerHostError::ProvenanceMismatch);
            }
            if withdrawals
                .admit_manifest(admission.validated_manifest.manifest.clone(), now)
                .is_err()
            {
                ineligible.insert(manifest.artifact_id.clone());
            }
            self.validate_parent_provenance(&admission, registry)?;
            source_datasets.insert(
                manifest.artifact_id.clone(),
                admission
                    .validated_manifest
                    .manifest
                    .source_dataset_digests
                    .into_iter()
                    .collect(),
            );
        }
        // Registration is append ordered, so an ancestor's current exclusions
        // can be carried forward without changing the registry digest chain.
        for record in registry.records() {
            if let ArtifactEvent::Register { manifest, .. } = &record.event
                && manifest
                    .predecessor_id
                    .as_ref()
                    .is_some_and(|id| ineligible.contains(id))
            {
                ineligible.insert(manifest.artifact_id.clone());
            }
        }
        Ok(CurrentArtifactProvenance {
            ineligible,
            source_datasets,
        })
    }
    pub(super) fn read_manifest_admission(
        &self,
        manifest: &ArtifactManifest,
    ) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactOwnerHostError> {
        let admission = read_artifact_admission_by_manifest_digest(
            File::open(self.manifest_admission_path(manifest.support_digest))?,
            manifest.support_digest,
        )?;
        let v2 = &admission.validated_manifest.manifest;
        if v2.artifact_id != manifest.artifact_id
            || v2.kind != manifest.kind
            || v2.generation != manifest.generation
            || v2.predecessor_ids.len() > 1
            || v2.predecessor_ids.first() != manifest.predecessor_id.as_ref()
            || v2.bytes_digest != manifest.content_digest
            || v2.objective_class_digest != manifest.objective_digest
            || v2.compatibility_digest != manifest.compatibility_digest
            || v2.producer_id != manifest.producer_id
            || v2.encoded_size_bytes != manifest.encoded_size_bytes
        {
            return Err(ArtifactOwnerHostError::ProvenanceMismatch);
        }
        Ok(admission)
    }
    pub(super) fn manifest_admission_path(&self, manifest_digest: Digest32) -> PathBuf {
        self.root
            .join("admissions")
            .join(format!("{manifest_digest}.manifest"))
    }
}
