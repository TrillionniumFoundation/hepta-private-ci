//! Canonical semantic profiles for learning.operator.
//!
//! Callers provide semantic values. Profile and runtime digests are derived
//! internally from the complete canonical field set, preventing a value/digest
//! split at the production admission boundary.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

use crate::OperatorResourceBudgetV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorProfileErrorV1 {
    EmptyDigest(&'static str),
    DatasetGeneration,
    MinimumSamples,
    MinimumSupport,
    ErrorBudget,
    RuntimeBudget,
}

impl fmt::Display for OperatorProfileErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorProfileErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrainingProfileV1 {
    objective_digest: Digest32,
    sensor_core_digest: Digest32,
    dataset_generation: u64,
    minimum_samples_per_cell: usize,
    maximum_absolute_error: FixedQ32,
    runtime_limits: OperatorResourceBudgetV1,
    runtime_profile_digest: Digest32,
    profile_digest: Digest32,
}

impl TrainingProfileV1 {
    pub fn new(
        objective_digest: Digest32,
        sensor_core_digest: Digest32,
        dataset_generation: u64,
        minimum_samples_per_cell: usize,
        maximum_absolute_error: FixedQ32,
        runtime_limits: OperatorResourceBudgetV1,
    ) -> Result<Self, OperatorProfileErrorV1> {
        require_digest(objective_digest, "objective")?;
        require_digest(sensor_core_digest, "sensor core")?;
        if dataset_generation == 0 {
            return Err(OperatorProfileErrorV1::DatasetGeneration);
        }
        if minimum_samples_per_cell == 0 || minimum_samples_per_cell > 1_000_000 {
            return Err(OperatorProfileErrorV1::MinimumSamples);
        }
        if maximum_absolute_error.raw() < 0 {
            return Err(OperatorProfileErrorV1::ErrorBudget);
        }
        validate_runtime(runtime_limits)?;
        let runtime_profile_digest = runtime_digest(runtime_limits);
        let mut bytes = b"hepta.learning-operator.training-profile.v1\0".to_vec();
        bytes.extend_from_slice(objective_digest.as_array());
        bytes.extend_from_slice(sensor_core_digest.as_array());
        bytes.extend_from_slice(&dataset_generation.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(minimum_samples_per_cell)
                .map_err(|_| OperatorProfileErrorV1::MinimumSamples)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&maximum_absolute_error.raw().to_be_bytes());
        bytes.extend_from_slice(runtime_profile_digest.as_array());
        let profile_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            objective_digest,
            sensor_core_digest,
            dataset_generation,
            minimum_samples_per_cell,
            maximum_absolute_error,
            runtime_limits,
            runtime_profile_digest,
            profile_digest,
        })
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn sensor_core_digest(&self) -> Digest32 {
        self.sensor_core_digest
    }

    #[must_use]
    pub const fn dataset_generation(&self) -> u64 {
        self.dataset_generation
    }

    #[must_use]
    pub const fn minimum_samples_per_cell(&self) -> usize {
        self.minimum_samples_per_cell
    }

    #[must_use]
    pub const fn maximum_absolute_error(&self) -> FixedQ32 {
        self.maximum_absolute_error
    }

    #[must_use]
    pub const fn runtime_limits(&self) -> OperatorResourceBudgetV1 {
        self.runtime_limits
    }

    #[must_use]
    pub const fn runtime_profile_digest(&self) -> Digest32 {
        self.runtime_profile_digest
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.profile_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelProfileV1 {
    objective_digest: Digest32,
    sensor_core_digest: Digest32,
    dataset_generation: u64,
    minimum_support: u32,
    maximum_one_step_calibration_error: FixedQ32,
    maximum_multistep_calibration_error: FixedQ32,
    maximum_ood_false_acceptance: ProbabilityQ32,
    maximum_drift_score: FixedQ32,
    runtime_limits: OperatorResourceBudgetV1,
    runtime_profile_digest: Digest32,
    profile_digest: Digest32,
}

impl WorldModelProfileV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        objective_digest: Digest32,
        sensor_core_digest: Digest32,
        dataset_generation: u64,
        minimum_support: u32,
        maximum_one_step_calibration_error: FixedQ32,
        maximum_multistep_calibration_error: FixedQ32,
        maximum_ood_false_acceptance: ProbabilityQ32,
        maximum_drift_score: FixedQ32,
        runtime_limits: OperatorResourceBudgetV1,
    ) -> Result<Self, OperatorProfileErrorV1> {
        require_digest(objective_digest, "objective")?;
        require_digest(sensor_core_digest, "sensor core")?;
        if dataset_generation == 0 {
            return Err(OperatorProfileErrorV1::DatasetGeneration);
        }
        if minimum_support == 0 || minimum_support > 65_536 {
            return Err(OperatorProfileErrorV1::MinimumSupport);
        }
        for value in [
            maximum_one_step_calibration_error,
            maximum_multistep_calibration_error,
            maximum_drift_score,
        ] {
            if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&value) {
                return Err(OperatorProfileErrorV1::ErrorBudget);
            }
        }
        validate_runtime(runtime_limits)?;
        let runtime_profile_digest = runtime_digest(runtime_limits);
        let mut bytes = b"hepta.learning-operator.world-model-profile.v1\0".to_vec();
        bytes.extend_from_slice(objective_digest.as_array());
        bytes.extend_from_slice(sensor_core_digest.as_array());
        bytes.extend_from_slice(&dataset_generation.to_be_bytes());
        bytes.extend_from_slice(&minimum_support.to_be_bytes());
        bytes.extend_from_slice(&maximum_one_step_calibration_error.raw().to_be_bytes());
        bytes.extend_from_slice(&maximum_multistep_calibration_error.raw().to_be_bytes());
        bytes.extend_from_slice(&maximum_ood_false_acceptance.raw().to_be_bytes());
        bytes.extend_from_slice(&maximum_drift_score.raw().to_be_bytes());
        bytes.extend_from_slice(runtime_profile_digest.as_array());
        let profile_digest = Digest32::of_bytes(&bytes);
        Ok(Self {
            objective_digest,
            sensor_core_digest,
            dataset_generation,
            minimum_support,
            maximum_one_step_calibration_error,
            maximum_multistep_calibration_error,
            maximum_ood_false_acceptance,
            maximum_drift_score,
            runtime_limits,
            runtime_profile_digest,
            profile_digest,
        })
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn sensor_core_digest(&self) -> Digest32 {
        self.sensor_core_digest
    }

    #[must_use]
    pub const fn dataset_generation(&self) -> u64 {
        self.dataset_generation
    }

    #[must_use]
    pub const fn minimum_support(&self) -> u32 {
        self.minimum_support
    }

    #[must_use]
    pub const fn maximum_one_step_calibration_error(&self) -> FixedQ32 {
        self.maximum_one_step_calibration_error
    }

    #[must_use]
    pub const fn maximum_multistep_calibration_error(&self) -> FixedQ32 {
        self.maximum_multistep_calibration_error
    }

    #[must_use]
    pub const fn maximum_ood_false_acceptance(&self) -> ProbabilityQ32 {
        self.maximum_ood_false_acceptance
    }

    #[must_use]
    pub const fn maximum_drift_score(&self) -> FixedQ32 {
        self.maximum_drift_score
    }

    #[must_use]
    pub const fn runtime_limits(&self) -> OperatorResourceBudgetV1 {
        self.runtime_limits
    }

    #[must_use]
    pub const fn runtime_profile_digest(&self) -> Digest32 {
        self.runtime_profile_digest
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.profile_digest
    }
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), OperatorProfileErrorV1> {
    if digest.is_zero() {
        return Err(OperatorProfileErrorV1::EmptyDigest(label));
    }
    Ok(())
}

fn validate_runtime(value: OperatorResourceBudgetV1) -> Result<(), OperatorProfileErrorV1> {
    if value.max_operations == 0 || value.max_estimated_bytes == 0 || value.max_elapsed_micros == 0
    {
        return Err(OperatorProfileErrorV1::RuntimeBudget);
    }
    Ok(())
}

fn runtime_digest(value: OperatorResourceBudgetV1) -> Digest32 {
    let mut bytes = b"hepta.learning-operator.runtime-profile.v1\0".to_vec();
    bytes.extend_from_slice(&value.max_operations.to_be_bytes());
    bytes.extend_from_slice(&value.max_estimated_bytes.to_be_bytes());
    bytes.extend_from_slice(&value.max_elapsed_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn world_model_profile_digest_binds_sensor_core_identity() {
        let left = WorldModelProfileV1::new(
            digest("objective"),
            digest("sensor-a"),
            1,
            1,
            FixedQ32::ZERO,
            FixedQ32::ZERO,
            ProbabilityQ32::from_raw(0).unwrap(),
            FixedQ32::ZERO,
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap();
        let right = WorldModelProfileV1::new(
            digest("objective"),
            digest("sensor-b"),
            1,
            1,
            FixedQ32::ZERO,
            FixedQ32::ZERO,
            ProbabilityQ32::from_raw(0).unwrap(),
            FixedQ32::ZERO,
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap();
        assert_ne!(left.sensor_core_digest(), right.sensor_core_digest());
        assert_ne!(left.digest(), right.digest());
    }
}
