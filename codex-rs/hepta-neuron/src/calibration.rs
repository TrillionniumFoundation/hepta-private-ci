//! Qualified confidence and OOD assessment over frozen-head observations.
//!
//! A calibration profile is an immutable, externally qualified artifact. This
//! module verifies profile/model/generation bindings and applies a deterministic
//! bounded mapping. It does not train, select or self-certify the profile.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::model::FrozenModelManifestV1;

const Q: i64 = 1 << 24;
const MAX_PREDICTION_ERROR_Q24: i64 = 16 * Q;
const PPM: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationProfileV1 {
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub detector_digest: Digest32,
    pub support_digest: Digest32,
    pub generation: Generation,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub measured_ece_ppm: u32,
    pub maximum_ece_ppm: u32,
    pub measured_ood_false_acceptance_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub residual_full_confidence_q24: i64,
    pub residual_abstain_q24: i64,
    pub maximum_in_domain_ood_q24: i64,
    pub minimum_confidence_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationAssessmentV1 {
    pub profile_digest: Digest32,
    pub prediction_error_q24: i64,
    pub ood_score_q24: i64,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub assessment_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CalibrationError {
    InvalidProfile,
    ModelMismatch,
    GenerationMismatch,
    SequenceOutsideWindow,
    InvalidObservation,
    Arithmetic,
}

impl fmt::Display for CalibrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CalibrationError {}

impl CalibrationProfileV1 {
    pub fn digest(&self) -> Result<Digest32, CalibrationError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.calibration-profile.v1".to_vec();
        for digest in [
            self.calibration_artifact_digest,
            self.ood_artifact_digest,
            self.encoder_digest,
            self.head_digest,
            self.detector_digest,
            self.support_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.valid_from_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.expires_after_sequence.to_be_bytes());
        for value in [
            self.measured_ece_ppm,
            self.maximum_ece_ppm,
            self.measured_ood_false_acceptance_ppm,
            self.maximum_ood_false_acceptance_ppm,
            self.minimum_confidence_ppm,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.residual_full_confidence_q24,
            self.residual_abstain_q24,
            self.maximum_in_domain_ood_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), CalibrationError> {
        if [
            self.calibration_artifact_digest,
            self.ood_artifact_digest,
            self.encoder_digest,
            self.head_digest,
            self.detector_digest,
            self.support_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
            || self.valid_from_sequence == 0
            || self.expires_after_sequence < self.valid_from_sequence
            || self.measured_ece_ppm > self.maximum_ece_ppm
            || self.maximum_ece_ppm > PPM
            || self.measured_ood_false_acceptance_ppm
                > self.maximum_ood_false_acceptance_ppm
            || self.maximum_ood_false_acceptance_ppm > PPM
            || self.minimum_confidence_ppm > PPM
            || !(0..=MAX_PREDICTION_ERROR_Q24).contains(&self.residual_full_confidence_q24)
            || !(0..=MAX_PREDICTION_ERROR_Q24).contains(&self.residual_abstain_q24)
            || self.residual_abstain_q24 <= self.residual_full_confidence_q24
            || !(0..=Q).contains(&self.maximum_in_domain_ood_q24)
        {
            return Err(CalibrationError::InvalidProfile);
        }
        Ok(())
    }
}

pub fn assess_calibration(
    profile: &CalibrationProfileV1,
    manifest: &FrozenModelManifestV1,
    generation: Generation,
    sequence: u64,
    prediction_error_q24: i64,
    ood_score_q24: i64,
) -> Result<CalibrationAssessmentV1, CalibrationError> {
    let profile_digest = profile.digest()?;
    if profile.encoder_digest != manifest.encoder_digest || profile.head_digest != manifest.head_digest {
        return Err(CalibrationError::ModelMismatch);
    }
    if profile.generation != generation {
        return Err(CalibrationError::GenerationMismatch);
    }
    if sequence < profile.valid_from_sequence || sequence > profile.expires_after_sequence {
        return Err(CalibrationError::SequenceOutsideWindow);
    }
    if !(0..=MAX_PREDICTION_ERROR_Q24).contains(&prediction_error_q24)
        || !(0..=Q).contains(&ood_score_q24)
    {
        return Err(CalibrationError::InvalidObservation);
    }

    let confidence_ppm = confidence_ppm(profile, prediction_error_q24)?;
    let ood_ppm = q24_probability_to_ppm(ood_score_q24)?;
    let abstain = confidence_ppm < profile.minimum_confidence_ppm
        || ood_score_q24 > profile.maximum_in_domain_ood_q24;
    let mut bytes = b"hepta.neuron.calibration-assessment.v1".to_vec();
    bytes.extend_from_slice(profile_digest.as_array());
    bytes.extend_from_slice(manifest.digest().map_err(|_| CalibrationError::ModelMismatch)?.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(&prediction_error_q24.to_be_bytes());
    bytes.extend_from_slice(&ood_score_q24.to_be_bytes());
    bytes.extend_from_slice(&confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&ood_ppm.to_be_bytes());
    bytes.push(u8::from(abstain));
    let assessment_digest = Digest32::of_bytes(&bytes);
    Ok(CalibrationAssessmentV1 {
        profile_digest,
        prediction_error_q24,
        ood_score_q24,
        confidence_ppm,
        ood_ppm,
        abstain,
        assessment_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn confidence_ppm(
    profile: &CalibrationProfileV1,
    prediction_error_q24: i64,
) -> Result<u32, CalibrationError> {
    if prediction_error_q24 <= profile.residual_full_confidence_q24 {
        return Ok(PPM);
    }
    if prediction_error_q24 >= profile.residual_abstain_q24 {
        return Ok(0);
    }
    let span = profile
        .residual_abstain_q24
        .checked_sub(profile.residual_full_confidence_q24)
        .ok_or(CalibrationError::Arithmetic)?;
    let remaining = profile
        .residual_abstain_q24
        .checked_sub(prediction_error_q24)
        .ok_or(CalibrationError::Arithmetic)?;
    let scaled = i128::from(remaining)
        .checked_mul(i128::from(PPM))
        .ok_or(CalibrationError::Arithmetic)?
        / i128::from(span);
    u32::try_from(scaled).map_err(|_| CalibrationError::Arithmetic)
}

fn q24_probability_to_ppm(value: i64) -> Result<u32, CalibrationError> {
    let scaled = i128::from(value)
        .checked_mul(i128::from(PPM))
        .ok_or(CalibrationError::Arithmetic)?
        / i128::from(Q);
    u32::try_from(scaled).map_err(|_| CalibrationError::Arithmetic)
}

#[cfg(test)]
#[path = "calibration_tests.rs"]
mod tests;
