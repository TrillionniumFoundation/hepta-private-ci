//! Durable complete admissions and withdrawal-aware owner composition.
//!
//! The signed V1 registry support digest commits the complete V2 manifest.
//! Sidecars restore that provenance without changing any V1 registry bytes.

use super::*;
use crate::admission_storage::MAX_ARTIFACT_ADMISSION_BYTES;
use crate::admission_storage::encode_artifact_admission;
use crate::read_artifact_admission_by_digest;
use crate::read_artifact_admission_by_manifest_digest;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

// Two immutable admission/index names per possible publication, with the same
// bounded allowance for orphan and interrupted temporary records. Every entry
// consumes capacity; ownership alone does not authorize deleting an orphan.
const MAX_ADMISSION_RECORDS: usize = MAX_HEAD_RECORDS * 4;

pub(crate) struct CurrentArtifactProvenance {
    pub(crate) ineligible: BTreeSet<StableId>,
    pub(crate) source_datasets: BTreeMap<StableId, BTreeSet<Digest32>>,
}

impl LearningArtifactOwnerHost {
    pub(super) fn persist_admission(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), ArtifactOwnerHostError> {
        let bytes = encode_artifact_admission(admission)?;
        let directory = self.root.join("admissions");
        let path = self
            .root
            .join("admissions")
            .join(format!("{}.bin", admission.admission_digest));
        let manifest_path =
            self.manifest_admission_path(admission.validated_manifest.manifest_digest);
        let admission_exists = path.try_exists()?;
        let manifest_exists = manifest_path.try_exists()?;
        let new_records = usize::from(!admission_exists) + usize::from(!manifest_exists);
        if new_records > 0 {
            // A missing admission temporarily needs both pending and final
            // names. That pending is removed before the index hard link, so
            // reserve the larger of the two publication peaks.
            let peak_new_records = new_records.max(if admission_exists { 0 } else { 2 });
            let maximum_existing = MAX_ADMISSION_RECORDS - peak_new_records;
            for (index, entry) in fs::read_dir(directory)?.enumerate() {
                entry?;
                if index >= maximum_existing {
                    return Err(ArtifactOwnerHostError::Capacity);
                }
            }
        }
        // begin_publication holds the same-host mutation fence across this
        // capacity check and both create-only effects. Complete existing
        // sidecars remain reusable when Prepared failed at the quota boundary.
        records::write_record_with_limit(&path, &bytes, MAX_ARTIFACT_ADMISSION_BYTES)?;
        match fs::hard_link(&path, &manifest_path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let existing = read_artifact_admission_by_manifest_digest(
                    File::open(&manifest_path)?,
                    admission.validated_manifest.manifest_digest,
                )?;
                if existing.validated_manifest != admission.validated_manifest
                    || existing.withdrawal_scope_digest != admission.withdrawal_scope_digest
                {
                    return Err(ArtifactOwnerHostError::ProvenanceMismatch);
                }
            }
            Err(error) => return Err(error.into()),
        }
        records::sync_parent(&manifest_path)?;
        Ok(())
    }

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

    pub(crate) fn current_provenance(
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

    fn read_manifest_admission(
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

    fn manifest_admission_path(&self, manifest_digest: Digest32) -> PathBuf {
        self.root
            .join("admissions")
            .join(format!("{manifest_digest}.manifest"))
    }
}

#[cfg(test)]
#[path = "owner_admissions_tests.rs"]
mod tests;
