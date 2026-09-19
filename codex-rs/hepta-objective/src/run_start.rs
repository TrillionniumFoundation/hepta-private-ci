use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ObjectiveFunction;
use crate::validate_compiled_objective_v1;

const RUN_START_DIGEST_DOMAIN: &[u8] = b"hepta.run-start-snapshot.v1";

/// Typed in-process representation of the registered `RunStartSnapshotV1`.
///
/// It binds an already compiled immutable objective to the exact preference,
/// model, prompt, artifact, authority and generation state selected for one
/// run. Constructing the snapshot grants no execution or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartSnapshotV1 {
    pub run_id: StableId,
    pub objective_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RunStartSnapshotError {
    InvalidObjective(crate::ObjectiveError),
    ObjectiveDigestMismatch,
    HardConstraintDigestMismatch,
    EmptyDigest(&'static str),
    ZeroIdentity(&'static str),
}

impl fmt::Display for RunStartSnapshotError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidObjective(error) => {
                write!(formatter, "invalid compiled objective: {error}")
            }
            Self::ObjectiveDigestMismatch => {
                formatter.write_str("run snapshot objective digest mismatch")
            }
            Self::HardConstraintDigestMismatch => {
                formatter.write_str("run snapshot hard-constraint digest mismatch")
            }
            Self::EmptyDigest(field) => {
                write!(formatter, "run snapshot {field} digest must not be zero")
            }
            Self::ZeroIdentity(field) => write!(formatter, "run snapshot {field} must be non-zero"),
        }
    }
}

impl Error for RunStartSnapshotError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::InvalidObjective(error) => Some(error),
            _ => None,
        }
    }
}

impl From<crate::ObjectiveError> for RunStartSnapshotError {
    fn from(value: crate::ObjectiveError) -> Self {
        Self::InvalidObjective(value)
    }
}

impl RunStartSnapshotV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn bind(
        run_id: StableId,
        objective: &ObjectiveFunction,
        preference_state_digest: Digest32,
        model_tuple_digest: Digest32,
        prompt_registry_digest: Digest32,
        artifact_set_digest: Digest32,
        authority_epoch: u64,
        generation: u64,
        fence_digest: Digest32,
    ) -> Result<Self, RunStartSnapshotError> {
        validate_compiled_objective_v1(objective)?;
        let value = Self {
            run_id,
            objective_digest: objective.semantic_digest,
            hard_constraint_digest: objective.hard_constraint_digest,
            preference_state_digest,
            model_tuple_digest,
            prompt_registry_digest,
            artifact_set_digest,
            authority_epoch,
            generation,
            fence_digest,
        };
        value.validate_for_objective(objective)?;
        Ok(value)
    }

    pub fn validate_for_objective(
        &self,
        objective: &ObjectiveFunction,
    ) -> Result<(), RunStartSnapshotError> {
        validate_compiled_objective_v1(objective)?;
        if self.objective_digest != objective.semantic_digest {
            return Err(RunStartSnapshotError::ObjectiveDigestMismatch);
        }
        if self.hard_constraint_digest != objective.hard_constraint_digest {
            return Err(RunStartSnapshotError::HardConstraintDigestMismatch);
        }
        for (field, digest) in [
            ("objective", self.objective_digest),
            ("hard constraint", self.hard_constraint_digest),
            ("preference state", self.preference_state_digest),
            ("model tuple", self.model_tuple_digest),
            ("prompt registry", self.prompt_registry_digest),
            ("artifact set", self.artifact_set_digest),
            ("fence", self.fence_digest),
        ] {
            if digest.is_zero() {
                return Err(RunStartSnapshotError::EmptyDigest(field));
            }
        }
        if self.authority_epoch == 0 {
            return Err(RunStartSnapshotError::ZeroIdentity("authority epoch"));
        }
        if self.generation == 0 {
            return Err(RunStartSnapshotError::ZeroIdentity("generation"));
        }
        Ok(())
    }

    /// Digest every semantic field in a fixed order. The digest is a binding
    /// receipt only; it is not an execution grant.
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RUN_START_DIGEST_DOMAIN);
        push_id(&mut bytes, &self.run_id);
        for digest in [
            self.objective_digest,
            self.hard_constraint_digest,
            self.preference_state_digest,
            self.model_tuple_digest,
            self.prompt_registry_digest,
            self.artifact_set_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        bytes.extend_from_slice(self.fence_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_binds_every_run_start_field() {
        // Full objective binding is exercised through admission tests. This
        // fixture verifies the snapshot-only digest cannot ignore a field.
        let base = RunStartSnapshotV1 {
            run_id: StableId::new("run-1").expect("id"),
            objective_digest: Digest32::of_bytes(b"objective"),
            hard_constraint_digest: Digest32::of_bytes(b"hard"),
            preference_state_digest: Digest32::of_bytes(b"preference"),
            model_tuple_digest: Digest32::of_bytes(b"model"),
            prompt_registry_digest: Digest32::of_bytes(b"prompt"),
            artifact_set_digest: Digest32::of_bytes(b"artifacts"),
            authority_epoch: 1,
            generation: 1,
            fence_digest: Digest32::of_bytes(b"fence"),
        };
        let mut changed = base.clone();
        changed.generation = 2;
        assert_ne!(base.digest(), changed.digest());
    }
}
