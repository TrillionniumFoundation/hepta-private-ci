//! Durable complete admissions and withdrawal-aware owner composition.
//!
//! The signed V1 registry support digest commits the complete V2 manifest.
//! Sidecars restore that provenance without changing any V1 registry bytes.

use super::*;
use crate::admission_storage::MAX_ARTIFACT_ADMISSION_BYTES;
use crate::admission_storage::encode_artifact_admission;
#[cfg(test)]
use crate::read_artifact_admission_by_digest;
use crate::read_artifact_admission_by_manifest_digest;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

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
        let path = self
            .root
            .join("admissions")
            .join(format!("{}.bin", admission.admission_digest));
        records::write_record_with_limit(&path, &bytes, MAX_ARTIFACT_ADMISSION_BYTES)?;
        let manifest_path =
            self.manifest_admission_path(admission.validated_manifest.manifest_digest);
        // Each durable source needs its own inode: root custody readers reject
        // permanent hard links even when both names belong to this owner.
        match records::write_record_with_limit(&manifest_path, &bytes, MAX_ARTIFACT_ADMISSION_BYTES)
        {
            Ok(()) => {}
            Err(ArtifactOwnerHostError::IdentityConflict) => {
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
            Err(error) => return Err(error),
        }
        records::sync_parent(&manifest_path)?;
        Ok(())
    }

    pub(super) fn validate_parent_provenance(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        registry: &ArtifactRegistry,
    ) -> Result<(), ArtifactOwnerHostError> {
        self.read_context()
            .validate_parent_provenance(admission, registry)
    }

    pub(crate) fn current_provenance(
        &self,
        registry: &ArtifactRegistry,
        withdrawals: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<CurrentArtifactProvenance, ArtifactOwnerHostError> {
        self.read_context()
            .current_provenance(registry, withdrawals, now)
    }

    fn manifest_admission_path(&self, manifest_digest: Digest32) -> PathBuf {
        self.read_context().manifest_admission_path(manifest_digest)
    }
}

#[cfg(test)]
#[path = "owner_admissions_tests.rs"]
mod tests;
