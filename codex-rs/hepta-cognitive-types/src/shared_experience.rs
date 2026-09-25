//! Versioned, authority-free contracts for shared experience.
//!
//! These contracts reference existing private source events and owner revisions. They never
//! reclassify a private `MemoryEventV1`, grant access by construction, create a global writer,
//! or claim that revocation has already removed learned influence. Existing owners admit and
//! revalidate every use immediately before their physical read, training or artifact boundary.

use std::collections::BTreeSet;

use serde::Deserialize;
use serde::Serialize;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractGenerationV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;

pub const MAX_SHARED_DESTINATIONS_V2: usize = 32;
pub const MAX_SHARED_USE_GRANTS_V2: usize = 64;
pub const MAX_SHARED_OWNER_CUTS_V2: usize = 64;
pub const MAX_SHARED_CONTRIBUTIONS_V2: usize = 4_096;
pub const MAX_SHARED_DEPENDENCIES_V2: usize = 4_096;
pub const MAX_SHARED_REVOCATION_REFS_V2: usize = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum SharedExperienceUseClassV2 {
    RawEvidenceRead {
        consumer_id: ContractIdV1,
        consumer_workspace_sha256: ContractDigestV1,
    },
    PurposeBoundTraining {
        trainer_id: ContractIdV1,
        purpose_id: ContractIdV1,
        parameter_scope_sha256: ContractDigestV1,
        dataset_split_sha256: ContractDigestV1,
    },
    DerivedArtifactUse {
        artifact_id: ContractIdV1,
        artifact_consumer_id: ContractIdV1,
        artifact_lineage_sha256: ContractDigestV1,
    },
}

impl SharedExperienceUseClassV2 {
    pub fn consumer_id(&self) -> &ContractIdV1 {
        match self {
            Self::RawEvidenceRead { consumer_id, .. } => consumer_id,
            Self::PurposeBoundTraining { trainer_id, .. } => trainer_id,
            Self::DerivedArtifactUse {
                artifact_consumer_id,
                ..
            } => artifact_consumer_id,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperienceUseGrantV2 {
    pub grant_id: ContractIdV1,
    pub use_class: SharedExperienceUseClassV2,
    pub valid_from_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl SharedExperienceUseGrantV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.valid_from_unix_ms == 0 || self.expires_at_unix_ms <= self.valid_from_unix_ms {
            return Err(HnmfContractError::Invalid(
                "shared experience use grant interval",
            ));
        }
        Ok(())
    }
}

/// Identifies the owner format of the immutable source. A local Memory revision
/// digest is never reinterpreted as a canonical MemoryEventV1 digest.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SharedExperienceSourceKindV2 {
    CanonicalMemoryEvent,
    OwnerMemoryRevision,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperiencePublicationV2 {
    pub publication_operation_id: ContractIdV1,
    pub contribution_id: ContractIdV1,
    pub source_owner_id: ContractIdV1,
    pub source_owner_epoch: u64,
    pub source_kind: SharedExperienceSourceKindV2,
    pub source_record_id: ContractIdV1,
    pub source_revision: u64,
    pub source_record_sha256: ContractDigestV1,
    pub semantic_content_sha256: ContractDigestV1,
    pub source_scope_sha256: ContractDigestV1,
    pub environment_sha256: ContractDigestV1,
    pub applicability_sha256: ContractDigestV1,
    pub publication_policy_sha256: ContractDigestV1,
    pub policy_generation: ContractGenerationV1,
    pub destination_scope_ids: BTreeSet<ContractIdV1>,
    pub use_grants: Vec<SharedExperienceUseGrantV2>,
    pub retention_lineage_sha256: ContractDigestV1,
    pub correction_of_contribution_id: Option<ContractIdV1>,
    pub observed_at_unix_ms: u64,
    pub expires_at_unix_ms: Option<u64>,
}

impl SharedExperiencePublicationV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_owner_epoch == 0
            || self.source_revision == 0
            || self.observed_at_unix_ms == 0
            || self
                .expires_at_unix_ms
                .is_some_and(|expiry| expiry <= self.observed_at_unix_ms)
        {
            return Err(HnmfContractError::Invalid(
                "shared experience publication identity/time",
            ));
        }
        if self
            .correction_of_contribution_id
            .as_ref()
            .is_some_and(|predecessor| predecessor == &self.contribution_id)
        {
            return Err(HnmfContractError::Invalid(
                "shared contribution cannot correct itself",
            ));
        }
        if self.destination_scope_ids.is_empty()
            || self.destination_scope_ids.len() > MAX_SHARED_DESTINATIONS_V2
        {
            return Err(HnmfContractError::LimitExceeded {
                field: "destinationScopeIds",
                actual: self.destination_scope_ids.len(),
                maximum: MAX_SHARED_DESTINATIONS_V2,
            });
        }
        if self.use_grants.is_empty() || self.use_grants.len() > MAX_SHARED_USE_GRANTS_V2 {
            return Err(HnmfContractError::LimitExceeded {
                field: "useGrants",
                actual: self.use_grants.len(),
                maximum: MAX_SHARED_USE_GRANTS_V2,
            });
        }
        let mut previous: Option<&ContractIdV1> = None;
        let mut identities = BTreeSet::new();
        for grant in &self.use_grants {
            grant.validate()?;
            if previous.is_some_and(|left| left >= &grant.grant_id) {
                return Err(HnmfContractError::Invalid("shared use grant order"));
            }
            previous = Some(&grant.grant_id);
            if !identities.insert(grant.grant_id.clone()) {
                return Err(HnmfContractError::DuplicateIdentity("shared use grant"));
            }
            if grant.valid_from_unix_ms < self.observed_at_unix_ms
                || self
                    .expires_at_unix_ms
                    .is_some_and(|expiry| grant.expires_at_unix_ms > expiry)
            {
                return Err(HnmfContractError::Conflict(
                    "shared grant/publication interval",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperienceOwnerCutV2 {
    pub owner_id: ContractIdV1,
    pub owner_epoch: u64,
    pub source_frontier: u64,
    pub memory_frontier: u64,
    pub learning_frontier: u64,
    pub deletion_frontier: u64,
    pub revocation_frontier: u64,
    pub schema_sha256: ContractDigestV1,
    pub policy_sha256: ContractDigestV1,
}

impl SharedExperienceOwnerCutV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.owner_epoch == 0
            || (self.source_frontier == 0
                && self.memory_frontier == 0
                && self.learning_frontier == 0)
        {
            return Err(HnmfContractError::Invalid("shared owner cut"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SharedExperienceSnapshotCompletenessV2 {
    Complete,
    Partial,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperienceSnapshotV2 {
    pub snapshot_id: ContractIdV1,
    pub generation: ContractGenerationV1,
    pub purpose_id: ContractIdV1,
    pub owner_cuts: Vec<SharedExperienceOwnerCutV2>,
    pub contribution_sha256s: BTreeSet<ContractDigestV1>,
    pub dependency_sha256s: BTreeSet<ContractDigestV1>,
    pub unavailable_owner_ids: BTreeSet<ContractIdV1>,
    pub completeness: SharedExperienceSnapshotCompletenessV2,
    pub snapshot_manifest_sha256: ContractDigestV1,
    pub deletion_frontier_sha256: ContractDigestV1,
    pub revocation_frontier_sha256: ContractDigestV1,
    pub created_at_unix_ms: u64,
}

impl SharedExperienceSnapshotV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.created_at_unix_ms == 0 {
            return Err(HnmfContractError::ZeroValue(
                "sharedSnapshot.createdAtUnixMs",
            ));
        }
        let requested_owners = self
            .owner_cuts
            .len()
            .checked_add(self.unavailable_owner_ids.len())
            .ok_or(HnmfContractError::Invalid("shared owner count overflow"))?;
        if requested_owners > MAX_SHARED_OWNER_CUTS_V2 {
            return Err(HnmfContractError::LimitExceeded {
                field: "ownerCuts",
                actual: requested_owners,
                maximum: MAX_SHARED_OWNER_CUTS_V2,
            });
        }
        if self.contribution_sha256s.len() > MAX_SHARED_CONTRIBUTIONS_V2 {
            return Err(HnmfContractError::LimitExceeded {
                field: "contributionSha256s",
                actual: self.contribution_sha256s.len(),
                maximum: MAX_SHARED_CONTRIBUTIONS_V2,
            });
        }
        if self.dependency_sha256s.len() > MAX_SHARED_DEPENDENCIES_V2 {
            return Err(HnmfContractError::LimitExceeded {
                field: "dependencySha256s",
                actual: self.dependency_sha256s.len(),
                maximum: MAX_SHARED_DEPENDENCIES_V2,
            });
        }
        let mut owner_ids = BTreeSet::new();
        let mut previous: Option<&ContractIdV1> = None;
        for cut in &self.owner_cuts {
            cut.validate()?;
            if previous.is_some_and(|left| left >= &cut.owner_id) {
                return Err(HnmfContractError::Invalid("shared owner cut order"));
            }
            previous = Some(&cut.owner_id);
            if !owner_ids.insert(cut.owner_id.clone()) {
                return Err(HnmfContractError::DuplicateIdentity("shared owner cut"));
            }
        }
        if owner_ids
            .iter()
            .any(|owner| self.unavailable_owner_ids.contains(owner))
        {
            return Err(HnmfContractError::Conflict(
                "owner cannot be available and unavailable",
            ));
        }
        match self.completeness {
            SharedExperienceSnapshotCompletenessV2::Complete
                if self.owner_cuts.is_empty()
                    || self.contribution_sha256s.is_empty()
                    || !self.unavailable_owner_ids.is_empty() =>
            {
                return Err(HnmfContractError::Invalid("complete shared snapshot shape"));
            }
            SharedExperienceSnapshotCompletenessV2::Partial
                if self.owner_cuts.is_empty()
                    || self.contribution_sha256s.is_empty()
                    || self.unavailable_owner_ids.is_empty() =>
            {
                return Err(HnmfContractError::Invalid("partial shared snapshot shape"));
            }
            SharedExperienceSnapshotCompletenessV2::Unavailable
                if !self.owner_cuts.is_empty()
                    || !self.contribution_sha256s.is_empty()
                    || self.unavailable_owner_ids.is_empty() =>
            {
                return Err(HnmfContractError::Invalid(
                    "unavailable shared snapshot shape",
                ));
            }
            _ => {}
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SharedExperienceUseDispositionV2 {
    Delivered,
    TrainingBatchMaterialized,
    ArtifactAdopted,
    Rejected,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperienceUseReceiptV2 {
    pub use_operation_id: ContractIdV1,
    pub publication_sha256: ContractDigestV1,
    pub grant: SharedExperienceUseGrantV2,
    pub source_owner_id: ContractIdV1,
    pub source_revision: u64,
    pub consumer_id: ContractIdV1,
    pub observed_policy_generation: ContractGenerationV1,
    pub observed_revocation_frontier: u64,
    pub payload_sha256: ContractDigestV1,
    pub used_at_unix_ms: u64,
    pub final_use_observed: bool,
    pub disposition: SharedExperienceUseDispositionV2,
}

impl SharedExperienceUseReceiptV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.grant.validate()?;
        if self.source_revision == 0
            || self.used_at_unix_ms == 0
            || &self.consumer_id != self.grant.use_class.consumer_id()
        {
            return Err(HnmfContractError::Invalid(
                "shared experience use receipt binding",
            ));
        }
        let successful = matches!(
            self.disposition,
            SharedExperienceUseDispositionV2::Delivered
                | SharedExperienceUseDispositionV2::TrainingBatchMaterialized
                | SharedExperienceUseDispositionV2::ArtifactAdopted
        );
        // A rejected/indeterminate attempt must remain representable after expiry.
        // Only a claimed successful physical use must lie inside the grant interval.
        if successful
            && (self.used_at_unix_ms < self.grant.valid_from_unix_ms
                || self.used_at_unix_ms >= self.grant.expires_at_unix_ms)
        {
            return Err(HnmfContractError::Invalid(
                "successful shared use outside grant",
            ));
        }
        if successful != self.final_use_observed {
            return Err(HnmfContractError::Conflict(
                "shared experience final-use observation",
            ));
        }
        let class_matches = matches!(
            (&self.grant.use_class, self.disposition),
            (
                SharedExperienceUseClassV2::RawEvidenceRead { .. },
                SharedExperienceUseDispositionV2::Delivered
            ) | (
                SharedExperienceUseClassV2::PurposeBoundTraining { .. },
                SharedExperienceUseDispositionV2::TrainingBatchMaterialized
            ) | (
                SharedExperienceUseClassV2::DerivedArtifactUse { .. },
                SharedExperienceUseDispositionV2::ArtifactAdopted
            ) | (_, SharedExperienceUseDispositionV2::Rejected)
                | (_, SharedExperienceUseDispositionV2::Indeterminate)
        );
        if !class_matches {
            return Err(HnmfContractError::Conflict("shared use class/disposition"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SharedExperienceRevocationCompletenessV2 {
    Complete,
    Partial,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SharedExperienceInfluenceStatusV2 {
    NotApplicable,
    Pending,
    ProvedRemoved,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SharedExperienceRevocationReceiptV2 {
    pub revocation_operation_id: ContractIdV1,
    pub contribution_id: ContractIdV1,
    pub publication_sha256: ContractDigestV1,
    pub source_owner_id: ContractIdV1,
    pub source_revision: u64,
    pub predecessor_policy_generation: ContractGenerationV1,
    pub next_policy_generation: ContractGenerationV1,
    pub revocation_frontier: u64,
    pub all_uses_revoked: bool,
    pub revoked_use_grant_ids: BTreeSet<ContractIdV1>,
    pub affected_projection_sha256s: BTreeSet<ContractDigestV1>,
    pub affected_training_dataset_sha256s: BTreeSet<ContractDigestV1>,
    pub affected_artifact_sha256s: BTreeSet<ContractDigestV1>,
    pub pending_offline_owner_ids: BTreeSet<ContractIdV1>,
    pub source_use_blocked: bool,
    pub training_use_blocked: bool,
    pub artifact_adoption_blocked: bool,
    pub influence_status: SharedExperienceInfluenceStatusV2,
    pub influence_proof_sha256: Option<ContractDigestV1>,
    pub completeness: SharedExperienceRevocationCompletenessV2,
}

impl SharedExperienceRevocationReceiptV2 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.source_revision == 0
            || self.revocation_frontier == 0
            || self.predecessor_policy_generation.next()? != self.next_policy_generation
            || !self.source_use_blocked
            || !self.training_use_blocked
            || !self.artifact_adoption_blocked
        {
            return Err(HnmfContractError::Conflict(
                "shared experience revocation identity/frontier",
            ));
        }
        if !self.all_uses_revoked && self.revoked_use_grant_ids.is_empty() {
            return Err(HnmfContractError::Invalid(
                "partial use revocation needs grant identities",
            ));
        }
        for (field, actual) in [
            (
                "affectedProjectionSha256s",
                self.affected_projection_sha256s.len(),
            ),
            (
                "affectedTrainingDatasetSha256s",
                self.affected_training_dataset_sha256s.len(),
            ),
            (
                "affectedArtifactSha256s",
                self.affected_artifact_sha256s.len(),
            ),
            ("revokedUseGrantIds", self.revoked_use_grant_ids.len()),
        ] {
            if actual > MAX_SHARED_REVOCATION_REFS_V2 {
                return Err(HnmfContractError::LimitExceeded {
                    field,
                    actual,
                    maximum: MAX_SHARED_REVOCATION_REFS_V2,
                });
            }
        }
        if self.pending_offline_owner_ids.len() > MAX_SHARED_OWNER_CUTS_V2 {
            return Err(HnmfContractError::LimitExceeded {
                field: "pendingOfflineOwnerIds",
                actual: self.pending_offline_owner_ids.len(),
                maximum: MAX_SHARED_OWNER_CUTS_V2,
            });
        }
        match self.completeness {
            SharedExperienceRevocationCompletenessV2::Complete
                if !self.pending_offline_owner_ids.is_empty() =>
            {
                return Err(HnmfContractError::Invalid(
                    "complete revocation has pending owners",
                ));
            }
            SharedExperienceRevocationCompletenessV2::Partial
                if self.pending_offline_owner_ids.is_empty() =>
            {
                return Err(HnmfContractError::Invalid(
                    "partial revocation needs pending owners",
                ));
            }
            _ => {}
        }
        match (self.influence_status, self.influence_proof_sha256) {
            (SharedExperienceInfluenceStatusV2::ProvedRemoved, Some(_))
            | (SharedExperienceInfluenceStatusV2::NotApplicable, None)
            | (SharedExperienceInfluenceStatusV2::Pending, None) => {}
            _ => {
                return Err(HnmfContractError::Invalid("shared influence proof/status"));
            }
        }
        Ok(())
    }
}
