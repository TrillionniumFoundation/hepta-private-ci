//! Runtime health classification and deterministic fallback selection.

use std::error::Error as StdError;
use std::fmt;

use crate::calibration::CalibrationAssessmentV1;
use crate::sparse::SparseSignalReceipt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeStabilityProfileV1 {
    pub minimum_active_fraction_ppm: u32,
    pub maximum_active_fraction_ppm: u32,
    pub maximum_projection_count: u32,
    pub maximum_threshold_saturation_count: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeHealthV1 {
    Healthy,
    DeadActivation,
    DenseActivation,
    ProjectionOverflow,
    ThresholdSaturation,
    CalibrationAbstain,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FallbackCapabilitiesV1 {
    pub stateless_head_qualified: bool,
    pub deterministic_rule_qualified: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimePathV1 {
    TemporalCheckpoint,
    StatelessSelectedHead,
    DeterministicCalibratedRule,
    SlowPath,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FallbackError {
    InvalidStabilityProfile,
    InvalidThresholdBounds,
    Arithmetic,
}

impl fmt::Display for FallbackError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FallbackError {}

pub fn assess_runtime_health(
    profile: RuntimeStabilityProfileV1,
    signal: &SparseSignalReceipt,
    thresholds_q24: &[i64],
    threshold_minimum_q24: i64,
    threshold_maximum_q24: i64,
    calibration: &CalibrationAssessmentV1,
) -> Result<RuntimeHealthV1, FallbackError> {
    if profile.minimum_active_fraction_ppm > profile.maximum_active_fraction_ppm
        || profile.maximum_active_fraction_ppm > 1_000_000
    {
        return Err(FallbackError::InvalidStabilityProfile);
    }
    if threshold_minimum_q24 > threshold_maximum_q24 {
        return Err(FallbackError::InvalidThresholdBounds);
    }
    if signal.active_fraction_ppm < profile.minimum_active_fraction_ppm {
        return Ok(RuntimeHealthV1::DeadActivation);
    }
    if signal.active_fraction_ppm > profile.maximum_active_fraction_ppm {
        return Ok(RuntimeHealthV1::DenseActivation);
    }
    if signal.projection_count > profile.maximum_projection_count {
        return Ok(RuntimeHealthV1::ProjectionOverflow);
    }
    let threshold_saturation_count = thresholds_q24
        .iter()
        .filter(|&&value| value == threshold_minimum_q24 || value == threshold_maximum_q24)
        .count();
    let threshold_saturation_count =
        u32::try_from(threshold_saturation_count).map_err(|_| FallbackError::Arithmetic)?;
    if threshold_saturation_count > profile.maximum_threshold_saturation_count {
        return Ok(RuntimeHealthV1::ThresholdSaturation);
    }
    if calibration.abstain {
        return Ok(RuntimeHealthV1::CalibrationAbstain);
    }
    Ok(RuntimeHealthV1::Healthy)
}

pub fn select_runtime_path(
    health: RuntimeHealthV1,
    capabilities: FallbackCapabilitiesV1,
) -> RuntimePathV1 {
    if health == RuntimeHealthV1::Healthy {
        return RuntimePathV1::TemporalCheckpoint;
    }
    if capabilities.stateless_head_qualified {
        return RuntimePathV1::StatelessSelectedHead;
    }
    if capabilities.deterministic_rule_qualified {
        return RuntimePathV1::DeterministicCalibratedRule;
    }
    RuntimePathV1::SlowPath
}

#[cfg(test)]
#[path = "fallback_tests.rs"]
mod tests;
