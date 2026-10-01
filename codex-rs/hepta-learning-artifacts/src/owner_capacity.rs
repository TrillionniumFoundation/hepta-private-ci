//! Entry budgets for the owner's create-only publication domains.
//!
//! Callers hold the host mutation fence across preflight and publication. A new
//! atomic record reserves both its final name and its temporary name, so a kill
//! between hard-link publication and temporary cleanup cannot exceed the budget.

use super::*;

pub(super) const MAX_PAYLOAD_RECORDS: usize = MAX_HEAD_RECORDS * 2;
pub(super) const MAX_REGISTRY_RECORDS: usize = MAX_HEAD_RECORDS * 4;
pub(super) const MAX_WITNESS_RECORDS: usize = MAX_HEAD_RECORDS * 4;

fn preflight_directory(
    directory: &Path,
    maximum_entries: usize,
    reservation: usize,
) -> Result<(), ArtifactOwnerHostError> {
    let maximum_existing = maximum_entries
        .checked_sub(reservation)
        .ok_or(ArtifactOwnerHostError::Capacity)?;
    for (index, entry) in fs::read_dir(directory)?.enumerate() {
        entry?;
        if index >= maximum_existing {
            return Err(ArtifactOwnerHostError::Capacity);
        }
    }
    Ok(())
}

pub(super) fn preflight_atomic_record(
    path: &Path,
    maximum_entries: usize,
) -> Result<(), ArtifactOwnerHostError> {
    // Exact reuse allocates no temporary or final name. Content and durability
    // are checked by the immutable writer before a checkpoint can advance.
    if path.try_exists()? {
        return Ok(());
    }
    let parent = path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?;
    preflight_directory(parent, maximum_entries, /*reservation*/ 2)
}

fn preflight_head_count(directory: &Path) -> Result<(), ArtifactOwnerHostError> {
    let mut heads = 0usize;
    for entry in fs::read_dir(directory)? {
        if entry?.path().extension().and_then(|value| value.to_str()) == Some("head") {
            heads += 1;
            if heads >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
        }
    }
    Ok(())
}

pub(super) fn preflight_head(path: &Path) -> Result<(), ArtifactOwnerHostError> {
    if path.try_exists()? {
        return Ok(());
    }
    preflight_atomic_record(path, MAX_HEAD_RECORDS * 2)?;
    preflight_head_count(path.parent().ok_or(ArtifactOwnerHostError::PathBoundary)?)
}

impl LearningArtifactOwnerHost {
    pub(super) fn preflight_new_publication(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
    ) -> Result<(), ArtifactOwnerHostError> {
        // A successful new Prepared must have room for the known payload,
        // all five checkpoint names and the next registry/witness/head. Only
        // existing exact operations bypass these conservative future budgets.
        preflight_directory(
            &self.root.join("transactions"),
            records::MAX_OWNER_RECORDS,
            /*reservation*/ 6,
        )?;
        let manifest = &admission.validated_manifest.manifest;
        preflight_atomic_record(
            &self.root.join("payloads").join(format!(
                "{}-{}.bin",
                manifest.artifact_id, manifest.bytes_digest
            )),
            MAX_PAYLOAD_RECORDS,
        )?;
        for (name, maximum_entries) in [
            ("registries", MAX_REGISTRY_RECORDS),
            ("witnesses", MAX_WITNESS_RECORDS),
            ("heads", MAX_HEAD_RECORDS * 2),
        ] {
            preflight_directory(
                &self.root.join(name),
                maximum_entries,
                /*reservation*/ 2,
            )?;
        }
        preflight_head_count(&self.root.join("heads"))?;
        Ok(())
    }
}
