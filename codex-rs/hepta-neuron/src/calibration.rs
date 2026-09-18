//! Deterministic application of independently qualified calibration/OOD artifacts.
//!
//! The runtime never manufactures calibration quality. Artifacts carry measured
//! ECE/FAR metadata and exact model/config bindings; callers must authenticate
//! those artifacts before admission. Missing or insufficient evidence fails to
//! abstain/slow-path rather than converting raw residuals into confidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::protocol::PPM_ONE;
use crate::protocol::Q24_ONE;

const MAX_BINS: usize = 64;
const Q24_ERROR_LIMIT: i64 = 16 * Q24_ONE;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationBinV1 {
    pub maximum_prediction_error_q24: i64,
    pub confidence_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCalibrationArtifactV1 {
    pub artifact_digest: Digest32,
    pub config_digest: Digest32,
    pub policy_digest: Digest32,
    pub model_identity_digest: Digest32,
    pub generation: Generation,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub measured_ece_ppm: u32,
    pub measured_ood_false_acceptance_ppm: u32,
    pub subgroup_audit_digest: Digest32,
    pub detector_digest: Digest32,
    pub support_digest: Digest32,
    pub maximum_in_domain_ood_q24: i64,
    pub bins: Vec<CalibrationBinV1>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CalibrationPolicyV1 {
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub minimum_confidence_ppm: u32,
    pub saturation_limit: u32,
    pub maximum_active_fraction_ppm: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SignalFallbackReasonV1 {
    MissingCalibration,
    CalibrationBindingMismatch,
    CalibrationExpired,
    CalibrationQualityInsufficient,
    OutOfDistribution,
    LowConfidence,
    DeadActivation,
    DenseActivation,
    ProjectionLimit,
    ResourceEnvelopeExceeded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedSignalV1 {
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub calibration_artifact_digest: Option<Digest32>,
    pub fallback_reason: Option<SignalFallbackReasonV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CalibrationError {
    InvalidPolicy,
    InvalidArtifact(&'static str),
    ArtifactDigestMismatch,
}

impl fmt::Display for CalibrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CalibrationError {}

impl CalibrationPolicyV1 {
    pub fn digest(&self) -> Result<Digest32, CalibrationError> {
        validate_policy(*self)?;
        let mut bytes = b"hepta.neuron.calibration-policy.v1".to_vec();
        for value in [
            self.maximum_ece_ppm,
            self.maximum_ood_false_acceptance_ppm,
            self.minimum_confidence_ppm,
            self.saturation_limit,
            self.maximum_active_fraction_ppm,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl NeuronCalibrationArtifactV1 {
    pub fn calculate_digest(&self) -> Result<Digest32, CalibrationError> {
        validate_artifact_shape(self)?;
        let mut bytes = b"hepta.neuron.calibration-artifact.v1".to_vec();
        for digest in [
            self.config_digest,
            self.policy_digest,
            self.model_identity_digest,
            self.subgroup_audit_digest,
            self.detector_digest,
            self.support_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.valid_from_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.expires_after_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.measured_ece_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.measured_ood_false_acceptance_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_in_domain_ood_q24.to_be_bytes());
        bytes.extend_from_slice(&(self.bins.len() as u64).to_be_bytes());
        for bin in &self.bins {
            bytes.extend_from_slice(&bin.maximum_prediction_error_q24.to_be_bytes());
            bytes.extend_from_slice(&bin.confidence_ppm.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn validate(&self) -> Result<(), CalibrationError> {
        if self.artifact_digest.is_zero() {
            return Err(CalibrationError::InvalidArtifact("artifact digest"));
        }
        let expected = self.calculate_digest()?;
        if expected != self.artifact_digest {
            return Err(CalibrationError::ArtifactDigestMismatch);
        }
        Ok(())
    }
}

pub fn apply_calibration(
    policy: CalibrationPolicyV1,
    artifact: Option<&NeuronCalibrationArtifactV1>,
    config_digest: Digest32,
    model_identity_digest: Digest32,
    generation: Generation,
    sequence: u64,
    prediction_error_q24: i64,
    ood_score_q24: i64,
    active_fraction_ppm: u32,
    projection_count: u32,
) -> Result<CalibratedSignalV1, CalibrationError> {
    validate_policy(policy)?;
    if active_fraction_ppm == 0 {
        return Ok(fallback(
            artifact,
            SignalFallbackReasonV1::DeadActivation,
            PPM_ONE,
        ));
    }
    if active_fraction_ppm > policy.maximum_active_fraction_ppm {
        return Ok(fallback(
            artifact,
            SignalFallbackReasonV1::DenseActivation,
            PPM_ONE,
        ));
    }
    if projection_count >= policy.saturation_limit {
        return Ok(fallback(
            artifact,
            SignalFallbackReasonV1::ProjectionLimit,
            PPM_ONE,
        ));
    }
    let Some(artifact) = artifact else {
        return Ok(fallback(
            None,
            SignalFallbackReasonV1::MissingCalibration,
            PPM_ONE,
        ));
    };
    artifact.validate()?;
    if artifact.config_digest != config_digest
        || artifact.policy_digest != policy.digest()?
        || artifact.model_identity_digest != model_identity_digest
        || artifact.generation != generation
    {
        return Ok(fallback(
            Some(artifact),
            SignalFallbackReasonV1::CalibrationBindingMismatch,
            PPM_ONE,
        ));
    }
    if sequence < artifact.valid_from_sequence || sequence > artifact.expires_after_sequence {
        return Ok(fallback(
            Some(artifact),
            SignalFallbackReasonV1::CalibrationExpired,
            PPM_ONE,
        ));
    }
    if artifact.measured_ece_ppm > policy.maximum_ece_ppm
        || artifact.measured_ood_false_acceptance_ppm > policy.maximum_ood_false_acceptance_ppm
    {
        return Ok(fallback(
            Some(artifact),
            SignalFallbackReasonV1::CalibrationQualityInsufficient,
            PPM_ONE,
        ));
    }
    let ood_ppm = scaled_ood_ppm(ood_score_q24, artifact.maximum_in_domain_ood_q24);
    if ood_score_q24 > artifact.maximum_in_domain_ood_q24 {
        return Ok(fallback(
            Some(artifact),
            SignalFallbackReasonV1::OutOfDistribution,
            ood_ppm,
        ));
    }
    let error = prediction_error_q24.clamp(0, Q24_ERROR_LIMIT);
    let confidence_ppm = artifact
        .bins
        .iter()
        .find(|bin| error <= bin.maximum_prediction_error_q24)
        .map_or(0, |bin| bin.confidence_ppm);
    if confidence_ppm < policy.minimum_confidence_ppm {
        return Ok(CalibratedSignalV1 {
            confidence_ppm,
            ood_ppm,
            abstain: true,
            calibration_artifact_digest: Some(artifact.artifact_digest),
            fallback_reason: Some(SignalFallbackReasonV1::LowConfidence),
        });
    }
    Ok(CalibratedSignalV1 {
        confidence_ppm,
        ood_ppm,
        abstain: false,
        calibration_artifact_digest: Some(artifact.artifact_digest),
        fallback_reason: None,
    })
}

fn validate_policy(policy: CalibrationPolicyV1) -> Result<(), CalibrationError> {
    if policy.maximum_ece_ppm > PPM_ONE
        || policy.maximum_ood_false_acceptance_ppm > PPM_ONE
        || policy.minimum_confidence_ppm > PPM_ONE
        || policy.saturation_limit == 0
        || policy.maximum_active_fraction_ppm == 0
        || policy.maximum_active_fraction_ppm > PPM_ONE
    {
        return Err(CalibrationError::InvalidPolicy);
    }
    Ok(())
}

fn validate_artifact_shape(artifact: &NeuronCalibrationArtifactV1) -> Result<(), CalibrationError> {
    for (name, digest) in [
        ("config", artifact.config_digest),
        ("policy", artifact.policy_digest),
        ("model runtime", artifact.model_identity_digest),
        ("subgroup audit", artifact.subgroup_audit_digest),
        ("detector", artifact.detector_digest),
        ("support", artifact.support_digest),
    ] {
        if digest.is_zero() {
            return Err(CalibrationError::InvalidArtifact(name));
        }
    }
    if artifact.valid_from_sequence == 0
        || artifact.expires_after_sequence < artifact.valid_from_sequence
        || artifact.measured_ece_ppm > PPM_ONE
        || artifact.measured_ood_false_acceptance_ppm > PPM_ONE
        || !(1..=Q24_ONE).contains(&artifact.maximum_in_domain_ood_q24)
        || !(1..=MAX_BINS).contains(&artifact.bins.len())
    {
        return Err(CalibrationError::InvalidArtifact("bounds"));
    }
    let mut previous = -1_i64;
    for bin in &artifact.bins {
        if bin.maximum_prediction_error_q24 <= previous
            || !(0..=Q24_ERROR_LIMIT).contains(&bin.maximum_prediction_error_q24)
            || bin.confidence_ppm > PPM_ONE
        {
            return Err(CalibrationError::InvalidArtifact("bins"));
        }
        previous = bin.maximum_prediction_error_q24;
    }
    if previous != Q24_ERROR_LIMIT {
        return Err(CalibrationError::InvalidArtifact("bin coverage"));
    }
    Ok(())
}

fn fallback(
    artifact: Option<&NeuronCalibrationArtifactV1>,
    reason: SignalFallbackReasonV1,
    ood_ppm: u32,
) -> CalibratedSignalV1 {
    CalibratedSignalV1 {
        confidence_ppm: 0,
        ood_ppm,
        abstain: true,
        calibration_artifact_digest: artifact.map(|value| value.artifact_digest),
        fallback_reason: Some(reason),
    }
}

fn scaled_ood_ppm(score_q24: i64, maximum_q24: i64) -> u32 {
    if score_q24 <= 0 {
        return 0;
    }
    if score_q24 >= maximum_q24 {
        return PPM_ONE;
    }
    let scaled = i128::from(score_q24) * i128::from(PPM_ONE) / i128::from(maximum_q24);
    u32::try_from(scaled).unwrap_or(PPM_ONE)
}
