use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use crate::WorkCancellationV1;
use crate::WorkControlError;
use crate::WorkControlV1;

const MAX_PROFILE_SAMPLES: usize = 1_000_000;
const MAX_PROFILE_OPERATIONS: u64 = 2_000_000_000;
const MAX_PROFILE_DURATION_MILLIS: u64 = 24 * 60 * 60 * 1_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeLimitsV1 {
    max_duration_millis: u64,
    max_operations: u64,
}

impl RuntimeLimitsV1 {
    pub fn new(
        max_duration_millis: u64,
        max_operations: u64,
    ) -> Result<Self, ProfileError> {
        if max_duration_millis == 0
            || max_duration_millis > MAX_PROFILE_DURATION_MILLIS
            || max_operations == 0
            || max_operations > MAX_PROFILE_OPERATIONS
        {
            return Err(ProfileError::InvalidRuntimeLimits);
        }
        Ok(Self {
            max_duration_millis,
            max_operations,
        })
    }

    #[must_use]
    pub fn max_duration_millis(self) -> u64 {
        self.max_duration_millis
    }

    #[must_use]
    pub fn max_operations(self) -> u64 {
        self.max_operations
    }

    pub fn start(self) -> Result<(WorkControlV1, WorkCancellationV1), WorkControlError> {
        WorkControlV1::new(self.max_duration_millis, self.max_operations)
    }
}

/// Canonical tabular training identity. Its digest is derived internally from
/// every behavior-affecting field and is never supplied independently.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrainingProfileV1 {
    generation: Generation,
    objective_digest: Digest32,
    sensor_core_digest: Digest32,
    dataset_frontier: u64,
    minimum_samples_per_cell: usize,
    maximum_absolute_error: FixedQ32,
    runtime: RuntimeLimitsV1,
    digest: Digest32,
}

impl TrainingProfileV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        generation: Generation,
        objective_digest: Digest32,
        sensor_core_digest: Digest32,
        dataset_frontier: u64,
        minimum_samples_per_cell: usize,
        maximum_absolute_error: FixedQ32,
        runtime: RuntimeLimitsV1,
    ) -> Result<Self, ProfileError> {
        require_digest(objective_digest, "objective")?;
        require_digest(sensor_core_digest, "sensor core")?;
        if dataset_frontier == 0 {
            return Err(ProfileError::InvalidDatasetFrontier);
        }
        if minimum_samples_per_cell == 0 || minimum_samples_per_cell > MAX_PROFILE_SAMPLES {
            return Err(ProfileError::InvalidMinimumSupport);
        }
        if maximum_absolute_error < FixedQ32::ZERO {
            return Err(ProfileError::InvalidErrorBudget);
        }
        let minimum_samples_u64 = u64::try_from(minimum_samples_per_cell)
            .map_err(|_| ProfileError::InvalidMinimumSupport)?;
        let mut bytes = b"hepta.bellman-operator.training-profile.v1\0".to_vec();
        bytes.extend_from_slice(&generation.get().to_be_bytes());
        bytes.extend_from_slice(objective_digest.as_array());
        bytes.extend_from_slice(sensor_core_digest.as_array());
        bytes.extend_from_slice(&dataset_frontier.to_be_bytes());
        bytes.extend_from_slice(&minimum_samples_u64.to_be_bytes());
        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());
        bytes.extend_from_slice(&runtime.max_duration_millis.to_be_bytes());
        bytes.extend_from_slice(&runtime.max_operations.to_be_bytes());
        let digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            generation,
            objective_digest,
            sensor_core_digest,
            dataset_frontier,
            minimum_samples_per_cell,
            maximum_absolute_error,
            runtime,
            digest,
        })
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub fn sensor_core_digest(&self) -> Digest32 {
        self.sensor_core_digest
    }

    #[must_use]
    pub fn dataset_frontier(&self) -> u64 {
        self.dataset_frontier
    }

    #[must_use]
    pub fn minimum_samples_per_cell(&self) -> usize {
        self.minimum_samples_per_cell
    }

    #[must_use]
    pub fn maximum_absolute_error(&self) -> FixedQ32 {
        self.maximum_absolute_error
    }

    #[must_use]
    pub fn runtime_limits(&self) -> RuntimeLimitsV1 {
        self.runtime
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn start_work(
        &self,
    ) -> Result<(WorkControlV1, WorkCancellationV1), WorkControlError> {
        self.runtime.start()
    }
}

/// Canonical world-model identity. Objective, sensor core, dataset frontier,
/// generation, support, uncertainty and runtime limits share one digest preimage.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelProfileV1 {
    generation: Generation,
    objective_digest: Digest32,
    sensor_core_digest: Digest32,
    dataset_frontier: u64,
    minimum_support_per_state_action: usize,
    maximum_uncertainty: FixedQ32,
    runtime: RuntimeLimitsV1,
    digest: Digest32,
}

impl WorldModelProfileV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        generation: Generation,
        objective_digest: Digest32,
        sensor_core_digest: Digest32,
        dataset_frontier: u64,
        minimum_support_per_state_action: usize,
        maximum_uncertainty: FixedQ32,
        runtime: RuntimeLimitsV1,
    ) -> Result<Self, ProfileError> {
        require_digest(objective_digest, "objective")?;
        require_digest(sensor_core_digest, "sensor core")?;
        if dataset_frontier == 0 {
            return Err(ProfileError::InvalidDatasetFrontier);
        }
        if minimum_support_per_state_action == 0
            || minimum_support_per_state_action > MAX_PROFILE_SAMPLES
        {
            return Err(ProfileError::InvalidMinimumSupport);
        }
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&maximum_uncertainty) {
            return Err(ProfileError::InvalidUncertaintyBudget);
        }
        let minimum_support_u64 = u64::try_from(minimum_support_per_state_action)
            .map_err(|_| ProfileError::InvalidMinimumSupport)?;
        let mut bytes = b"hepta.bellman-operator.world-model-profile.v1\0".to_vec();
        bytes.extend_from_slice(&generation.get().to_be_bytes());
        bytes.extend_from_slice(objective_digest.as_array());
        bytes.extend_from_slice(sensor_core_digest.as_array());
        bytes.extend_from_slice(&dataset_frontier.to_be_bytes());
        bytes.extend_from_slice(&minimum_support_u64.to_be_bytes());
        bytes.extend_from_slice(&maximum_uncertainty.raw().to_be_bytes());
        bytes.extend_from_slice(&runtime.max_duration_millis.to_be_bytes());
        bytes.extend_from_slice(&runtime.max_operations.to_be_bytes());
        let digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            generation,
            objective_digest,
            sensor_core_digest,
            dataset_frontier,
            minimum_support_per_state_action,
            maximum_uncertainty,
            runtime,
            digest,
        })
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub fn sensor_core_digest(&self) -> Digest32 {
        self.sensor_core_digest
    }

    #[must_use]
    pub fn dataset_frontier(&self) -> u64 {
        self.dataset_frontier
    }

    #[must_use]
    pub fn minimum_support_per_state_action(&self) -> usize {
        self.minimum_support_per_state_action
    }

    #[must_use]
    pub fn maximum_uncertainty(&self) -> FixedQ32 {
        self.maximum_uncertainty
    }

    #[must_use]
    pub fn runtime_limits(&self) -> RuntimeLimitsV1 {
        self.runtime
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn start_work(
        &self,
    ) -> Result<(WorkControlV1, WorkCancellationV1), WorkControlError> {
        self.runtime.start()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProfileError {
    EmptyDigest(&'static str),
    InvalidDatasetFrontier,
    InvalidMinimumSupport,
    InvalidErrorBudget,
    InvalidUncertaintyBudget,
    InvalidRuntimeLimits,
}

impl fmt::Display for ProfileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProfileError {}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), ProfileError> {
    if digest.is_zero() {
        return Err(ProfileError::EmptyDigest(label));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hash(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn training_digest_changes_with_behavioral_fields() {
        let runtime = RuntimeLimitsV1::new(1_000, 10_000).unwrap();
        let first = TrainingProfileV1::new(
            Generation::new(1).unwrap(),
            hash("objective"),
            hash("sensor"),
            7,
            2,
            FixedQ32::ZERO,
            runtime,
        )
        .unwrap();
        let second = TrainingProfileV1::new(
            Generation::new(1).unwrap(),
            hash("objective"),
            hash("sensor"),
            7,
            3,
            FixedQ32::ZERO,
            runtime,
        )
        .unwrap();
        assert_ne!(first.digest(), second.digest());
    }

    #[test]
    fn world_profile_rejects_out_of_range_uncertainty() {
        let runtime = RuntimeLimitsV1::new(1_000, 10_000).unwrap();
        assert_eq!(
            WorldModelProfileV1::new(
                Generation::new(1).unwrap(),
                hash("objective"),
                hash("sensor"),
                7,
                2,
                FixedQ32::from_raw(FixedQ32::ONE.raw() + 1),
                runtime,
            ),
            Err(ProfileError::InvalidUncertaintyBudget)
        );
    }
}
