//! Digest-only NDU snapshot binding for the Lane F shadow boundary.
//!
//! The reference is owner-local and additive. It does not change the V1 lane
//! snapshot wire record, grant execution authority, or select an artifact.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CoherentLaneFSnapshotV1;
use crate::PipelineErrorV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduSnapshotRefV1 {
    pub snapshot_digest: Digest32,
    pub lane_snapshot_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub fence_digest: Digest32,
    pub objective_revision: u64,
    pub authority_epoch: u64,
    pub body_generation: u64,
    pub ndu_generation: u64,
    pub model_artifact_digest: Digest32,
    pub ndu_artifact_digest: Digest32,
    pub neuron_checkpoint_digest: Digest32,
    pub prompt_registry_generation: u64,
    pub learning_artifact_generation: u64,
    pub context_schema_revision: u64,
    pub subject_id: StableId,
    pub subject_revision: u64,
    pub preference_state_digest: Digest32,
    pub utility_projection_digest: Digest32,
    pub action_risk_profile_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub valid_until_unix_ms: u64,
}

impl NduSnapshotRefV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_lane_snapshot(
        lane: &CoherentLaneFSnapshotV1,
        subject_id: StableId,
        subject_revision: u64,
        objective_digest: Digest32,
        fence_digest: Digest32,
        ndu_snapshot_digest: Digest32,
        ndu_generation: u64,
        preference_state_digest: Digest32,
        utility_projection_digest: Digest32,
        action_risk_profile_digest: Digest32,
        no_change_baseline_digest: Digest32,
        valid_until_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<Self, NduSnapshotRefError> {
        let snapshot_digest = lane.digest().map_err(NduSnapshotRefError::Lane)?;
        let mut reference = Self {
            snapshot_digest: Digest32::ZERO,
            lane_snapshot_digest: snapshot_digest,
            ndu_snapshot_digest,
            objective_digest,
            fence_digest,
            objective_revision: lane.objective_revision,
            authority_epoch: lane.authority_epoch,
            body_generation: lane.body_generation,
            ndu_generation,
            model_artifact_digest: lane.model_artifact_digest,
            ndu_artifact_digest: lane.ndu_artifact_digest,
            neuron_checkpoint_digest: lane.neuron_checkpoint_digest,
            prompt_registry_generation: lane.prompt_registry_generation,
            learning_artifact_generation: lane.learning_artifact_generation,
            context_schema_revision: lane.context_schema_revision,
            subject_id,
            subject_revision,
            preference_state_digest,
            utility_projection_digest,
            action_risk_profile_digest,
            no_change_baseline_digest,
            valid_until_unix_ms,
        };
        reference.snapshot_digest = reference.canonical_digest();
        reference.validate(now_unix_ms)?;
        Ok(reference)
    }

    pub fn validate(&self, now_unix_ms: u64) -> Result<(), NduSnapshotRefError> {
        if self.snapshot_digest.is_zero()
            || self.lane_snapshot_digest.is_zero()
            || self.ndu_snapshot_digest.is_zero()
            || self.objective_digest.is_zero()
            || self.fence_digest.is_zero()
            || self.model_artifact_digest.is_zero()
            || self.ndu_artifact_digest.is_zero()
            || self.neuron_checkpoint_digest.is_zero()
            || self.preference_state_digest.is_zero()
            || self.utility_projection_digest.is_zero()
            || self.action_risk_profile_digest.is_zero()
            || self.no_change_baseline_digest.is_zero()
        {
            return Err(NduSnapshotRefError::EmptyDigest);
        }
        if self.objective_revision == 0
            || self.authority_epoch == 0
            || self.body_generation == 0
            || self.ndu_generation == 0
            || self.prompt_registry_generation == 0
            || self.learning_artifact_generation == 0
            || self.context_schema_revision == 0
            || self.subject_revision == 0
        {
            return Err(NduSnapshotRefError::InvalidRevision);
        }
        if self.valid_until_unix_ms <= now_unix_ms {
            return Err(NduSnapshotRefError::Expired);
        }
        if self.canonical_digest() != self.snapshot_digest {
            return Err(NduSnapshotRefError::DigestMismatch);
        }
        Ok(())
    }

    pub fn validate_against_snapshot_digest(
        &self,
        lane_snapshot_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<(), NduSnapshotRefError> {
        self.validate(now_unix_ms)?;
        if self.lane_snapshot_digest != lane_snapshot_digest {
            return Err(NduSnapshotRefError::LaneMismatch);
        }
        Ok(())
    }

    pub fn validate_against_lane(
        &self,
        lane: &CoherentLaneFSnapshotV1,
        now_unix_ms: u64,
    ) -> Result<(), NduSnapshotRefError> {
        self.validate(now_unix_ms)?;
        if self.lane_snapshot_digest != lane.digest().map_err(NduSnapshotRefError::Lane)? {
            return Err(NduSnapshotRefError::LaneMismatch);
        }
        if self.objective_revision != lane.objective_revision
            || self.authority_epoch != lane.authority_epoch
            || self.body_generation != lane.body_generation
            || self.model_artifact_digest != lane.model_artifact_digest
            || self.ndu_artifact_digest != lane.ndu_artifact_digest
            || self.neuron_checkpoint_digest != lane.neuron_checkpoint_digest
            || self.prompt_registry_generation != lane.prompt_registry_generation
            || self.learning_artifact_generation != lane.learning_artifact_generation
            || self.context_schema_revision != lane.context_schema_revision
        {
            return Err(NduSnapshotRefError::LaneMismatch);
        }
        Ok(())
    }

    pub fn canonical_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.intelligence.ndu-snapshot-ref.v1\0".to_vec();
        for value in [
            self.objective_revision,
            self.authority_epoch,
            self.body_generation,
            self.ndu_generation,
            self.prompt_registry_generation,
            self.learning_artifact_generation,
            self.context_schema_revision,
            self.subject_revision,
            self.valid_until_unix_ms,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for digest in [
            self.lane_snapshot_digest,
            self.ndu_snapshot_digest,
            self.objective_digest,
            self.fence_digest,
            self.model_artifact_digest,
            self.ndu_artifact_digest,
            self.neuron_checkpoint_digest,
            self.preference_state_digest,
            self.utility_projection_digest,
            self.action_risk_profile_digest,
            self.no_change_baseline_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.subject_id);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduSnapshotRefError {
    Lane(PipelineErrorV1),
    EmptyDigest,
    InvalidRevision,
    Expired,
    DigestMismatch,
    LaneMismatch,
}

impl fmt::Display for NduSnapshotRefError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduSnapshotRefError {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|_| panic!("id"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn lane() -> CoherentLaneFSnapshotV1 {
        CoherentLaneFSnapshotV1 {
            objective_revision: 1,
            authority_epoch: 2,
            body_generation: 3,
            model_artifact_digest: digest("model"),
            ndu_artifact_digest: digest("ndu"),
            neuron_checkpoint_digest: digest("neuron"),
            prompt_registry_generation: 4,
            learning_artifact_generation: 5,
            context_schema_revision: 6,
        }
    }

    fn reference(now: u64) -> NduSnapshotRefV1 {
        NduSnapshotRefV1::from_lane_snapshot(
            &lane(),
            id("subject:1"),
            7,
            digest("objective"),
            digest("fence"),
            digest("ndu-snapshot"),
            8,
            digest("preference"),
            digest("utility"),
            digest("risk"),
            digest("baseline"),
            100,
            now,
        )
        .unwrap_or_else(|error| panic!("reference: {error}"))
    }

    #[test]
    fn binds_all_lane_fields_and_owner_digests() {
        let value = reference(1);
        assert!(value.validate_against_lane(&lane(), 1).is_ok());
        assert_eq!(
            value.lane_snapshot_digest,
            lane().digest().unwrap_or_else(|_| panic!("lane"))
        );
        assert_eq!(value.snapshot_digest, value.canonical_digest());
    }

    #[test]
    fn lane_drift_is_rejected() {
        let value = reference(1);
        let mut drifted = lane();
        drifted.authority_epoch = 9;
        assert_eq!(
            value.validate_against_lane(&drifted, 1),
            Err(NduSnapshotRefError::LaneMismatch)
        );
    }

    #[test]
    fn expiry_and_digest_mutation_fail_closed() {
        let mut value = reference(1);
        assert_eq!(value.validate(100), Err(NduSnapshotRefError::Expired));
        value.subject_revision = 8;
        assert_eq!(value.validate(1), Err(NduSnapshotRefError::DigestMismatch));
    }
}
