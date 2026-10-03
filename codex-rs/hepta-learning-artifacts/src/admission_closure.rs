//! Full V3 lineage joins for authenticated owner views.
//!
//! The V1 projection cannot express expiry, multiple parents or dataset inputs.
//! Those facts must be joined from independently pinned admission sidecars;
//! missing evidence is an error rather than an empty dependency list.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactRegistry;
use crate::ArtifactState;
use crate::DatasetWithdrawalRegistry;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::limits::MAX_DURABLE_ARTIFACT_RECORDS;
use crate::validate_admission_registry_projection_v3;
use crate::verify_artifact_admission_v3;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ArtifactAdmissionClosureError {
    MissingAdmission,
    DuplicateAdmission,
    ManifestMismatch,
    ScopeMismatch,
    InvalidAdmission,
    InvalidPredecessor,
    LimitExceeded,
}

/// Compute the eligible identities in registration order. Every full V2 parent
/// must have an earlier registration and a lower generation, keeping the join
/// acyclic and its cost bounded by the admitted manifest resource ceilings.
pub(crate) fn eligible_admission_closure(
    registry: &ArtifactRegistry,
    admissions: &[WithdrawalBoundArtifactAdmissionV3],
    withdrawals: &DatasetWithdrawalRegistry,
    now: u64,
) -> Result<BTreeSet<StableId>, ArtifactAdmissionClosureError> {
    if admissions.len() > MAX_DURABLE_ARTIFACT_RECORDS {
        return Err(ArtifactAdmissionClosureError::LimitExceeded);
    }
    let scope = withdrawals
        .scope_digest()
        .ok_or(ArtifactAdmissionClosureError::ScopeMismatch)?;
    let mut by_id = BTreeMap::new();
    for admission in admissions {
        verify_artifact_admission_v3(
            admission,
            admission.withdrawal_head_digest,
            admission.admitted_at,
        )
        .map_err(|_| ArtifactAdmissionClosureError::InvalidAdmission)?;
        if admission.withdrawal_scope_digest != scope {
            return Err(ArtifactAdmissionClosureError::ScopeMismatch);
        }
        if by_id
            .insert(
                admission.validated_manifest.manifest.artifact_id.clone(),
                admission,
            )
            .is_some()
        {
            return Err(ArtifactAdmissionClosureError::DuplicateAdmission);
        }
    }

    let mut seen = BTreeMap::new();
    let mut eligible = BTreeSet::new();
    for record in registry.records() {
        let ArtifactEvent::Register { manifest, .. } = &record.event else {
            continue;
        };
        let admission = by_id
            .get(&manifest.artifact_id)
            .ok_or(ArtifactAdmissionClosureError::MissingAdmission)?;
        if validate_admission_registry_projection_v3(manifest, admission).is_err() {
            return Err(ArtifactAdmissionClosureError::ManifestMismatch);
        }
        let full = &admission.validated_manifest.manifest;
        for parent_id in &full.predecessor_ids {
            let parent: &&WithdrawalBoundArtifactAdmissionV3 = seen
                .get(parent_id)
                .ok_or(ArtifactAdmissionClosureError::InvalidPredecessor)?;
            let parent_manifest = &parent.validated_manifest.manifest;
            if full.generation <= parent_manifest.generation
                || full.kind != parent_manifest.kind
                || full.objective_class_digest != parent_manifest.objective_class_digest
                || admission.admitted_at < parent.admitted_at
            {
                return Err(ArtifactAdmissionClosureError::InvalidPredecessor);
            }
        }
        if registry.state(&manifest.artifact_id) == Some(ArtifactState::Candidate)
            && full.created_at <= now
            && admission.admitted_at <= now
            && now <= full.expires_at
            && full
                .source_dataset_digests
                .iter()
                .all(|dataset| !withdrawals.is_withdrawn(*dataset))
            && full
                .predecessor_ids
                .iter()
                .all(|parent| eligible.contains(parent))
        {
            eligible.insert(manifest.artifact_id.clone());
        }
        seen.insert(manifest.artifact_id.clone(), *admission);
    }
    if seen.len() != by_id.len() {
        return Err(ArtifactAdmissionClosureError::ManifestMismatch);
    }
    Ok(eligible)
}

#[cfg(test)]
#[path = "admission_closure_tests.rs"]
mod tests;
