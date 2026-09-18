//! Deterministic admission for externally produced world-model qualification evidence.
//!
//! This module does not manufacture holdout, future-window, drift, confidence,
//! device, or live-world evidence. It consumes already frozen measurements and
//! fails closed against a digest-bound profile. Independent acceptance remains
//! outside this crate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const CANONICAL_MIN_EFFECTIVE_SAMPLES: u32 = 200;
const CANONICAL_MIN_INDEPENDENT_SNAPSHOTS: u16 = 3;
const CANONICAL_MIN_FUTURE_WINDOWS: u16 = 2;
const PROFILE_DOMAIN: &[u8] = b"hepta.bellman-operator.world-model-qualification-profile.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelQualificationProfileV1 {
    pub profile_digest: Digest32,
    pub minimum_effective_samples: u32,
    pub minimum_heldout_samples: u32,
    pub minimum_independent_snapshots: u16,
    pub minimum_future_windows: u16,
    pub maximum_heldout_mae: FixedQ32,
    pub maximum_temporal_calibration_error: FixedQ32,
    pub maximum_drift_score: FixedQ32,
    pub maximum_confidence_half_width: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelQualificationAssessmentV1 {
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub dataset_digest: Digest32,
    pub profile: WorldModelQualificationProfileV1,
    pub effective_sample_size: u32,
    pub heldout_sample_count: u32,
    pub independent_snapshot_count: u16,
    pub future_window_count: u16,
    pub heldout_mae: FixedQ32,
    pub temporal_calibration_error: FixedQ32,
    pub drift_score: FixedQ32,
    pub confidence_half_width: FixedQ32,
    pub evaluator_id: StableId,
    pub evaluator_credential_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelQualificationAdmissionV1 {
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub profile_digest: Digest32,
    pub assessment_digest: Digest32,
    pub effective_sample_size: u32,
    pub independent_snapshot_count: u16,
    pub future_window_count: u16,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WorldModelQualificationError {
    EmptyDigest,
    InvalidProfile,
    InsufficientEffectiveSupport,
    InsufficientHoldout,
    InsufficientSnapshots,
    InsufficientFutureWindows,
    InvalidMeasurement,
    HeldoutErrorExceeded,
    CalibrationErrorExceeded,
    DriftExceeded,
    ConfidenceTooWide,
}

impl fmt::Display for WorldModelQualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WorldModelQualificationError {}

/// Compute the canonical identity of the qualification policy fields.
///
/// The caller-populated `profile_digest` field is deliberately excluded from
/// its own digest. Admission recomputes this value and rejects a profile whose
/// thresholds were changed while retaining an older reviewed identity.
#[must_use]
pub fn world_model_qualification_profile_digest(
    profile: &WorldModelQualificationProfileV1,
) -> Digest32 {
    let mut bytes = PROFILE_DOMAIN.to_vec();
    bytes.extend_from_slice(&profile.minimum_effective_samples.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_heldout_samples.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_independent_snapshots.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_future_windows.to_be_bytes());
    for value in [
        profile.maximum_heldout_mae,
        profile.maximum_temporal_calibration_error,
        profile.maximum_drift_score,
        profile.maximum_confidence_half_width,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

/// Admit frozen statistical evidence for continued shadow qualification.
///
/// A successful result is a deny-all source-level admission record. It is not
/// operator acceptance, activation, canary authorization, promotion, or release.
pub fn admit_world_model_qualification(
    assessment: WorldModelQualificationAssessmentV1,
) -> Result<WorldModelQualificationAdmissionV1, WorldModelQualificationError> {
    for digest in [
        assessment.model_digest,
        assessment.dataset_digest,
        assessment.profile.profile_digest,
        assessment.evaluator_credential_digest,
        assessment.evidence_digest,
    ] {
        if digest.is_zero() {
            return Err(WorldModelQualificationError::EmptyDigest);
        }
    }
    validate_profile(&assessment.profile)?;
    for value in [
        assessment.heldout_mae,
        assessment.temporal_calibration_error,
        assessment.drift_score,
        assessment.confidence_half_width,
    ] {
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&value) {
            return Err(WorldModelQualificationError::InvalidMeasurement);
        }
    }
    if assessment.effective_sample_size < assessment.profile.minimum_effective_samples {
        return Err(WorldModelQualificationError::InsufficientEffectiveSupport);
    }
    if assessment.heldout_sample_count < assessment.profile.minimum_heldout_samples {
        return Err(WorldModelQualificationError::InsufficientHoldout);
    }
    if assessment.independent_snapshot_count < assessment.profile.minimum_independent_snapshots {
        return Err(WorldModelQualificationError::InsufficientSnapshots);
    }
    if assessment.future_window_count < assessment.profile.minimum_future_windows {
        return Err(WorldModelQualificationError::InsufficientFutureWindows);
    }
    if assessment.heldout_mae > assessment.profile.maximum_heldout_mae {
        return Err(WorldModelQualificationError::HeldoutErrorExceeded);
    }
    if assessment.temporal_calibration_error > assessment.profile.maximum_temporal_calibration_error
    {
        return Err(WorldModelQualificationError::CalibrationErrorExceeded);
    }
    if assessment.drift_score > assessment.profile.maximum_drift_score {
        return Err(WorldModelQualificationError::DriftExceeded);
    }
    if assessment.confidence_half_width > assessment.profile.maximum_confidence_half_width {
        return Err(WorldModelQualificationError::ConfidenceTooWide);
    }

    let assessment_digest = digest_assessment(&assessment);
    Ok(WorldModelQualificationAdmissionV1 {
        model_id: assessment.model_id,
        model_digest: assessment.model_digest,
        profile_digest: assessment.profile.profile_digest,
        assessment_digest,
        effective_sample_size: assessment.effective_sample_size,
        independent_snapshot_count: assessment.independent_snapshot_count,
        future_window_count: assessment.future_window_count,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_profile(
    profile: &WorldModelQualificationProfileV1,
) -> Result<(), WorldModelQualificationError> {
    if profile.profile_digest != world_model_qualification_profile_digest(profile)
        || profile.minimum_effective_samples < CANONICAL_MIN_EFFECTIVE_SAMPLES
        || profile.minimum_heldout_samples < CANONICAL_MIN_EFFECTIVE_SAMPLES
        || profile.minimum_independent_snapshots < CANONICAL_MIN_INDEPENDENT_SNAPSHOTS
        || profile.minimum_future_windows < CANONICAL_MIN_FUTURE_WINDOWS
    {
        return Err(WorldModelQualificationError::InvalidProfile);
    }
    for limit in [
        profile.maximum_heldout_mae,
        profile.maximum_temporal_calibration_error,
        profile.maximum_drift_score,
        profile.maximum_confidence_half_width,
    ] {
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&limit) {
            return Err(WorldModelQualificationError::InvalidProfile);
        }
    }
    Ok(())
}

fn digest_assessment(assessment: &WorldModelQualificationAssessmentV1) -> Digest32 {
    let mut bytes = b"hepta.bellman-operator.world-model-qualification.v1".to_vec();
    push_id(&mut bytes, &assessment.model_id);
    for digest in [
        assessment.model_digest,
        assessment.dataset_digest,
        assessment.profile.profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&assessment.profile.minimum_effective_samples.to_be_bytes());
    bytes.extend_from_slice(&assessment.profile.minimum_heldout_samples.to_be_bytes());
    bytes.extend_from_slice(
        &assessment
            .profile
            .minimum_independent_snapshots
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&assessment.profile.minimum_future_windows.to_be_bytes());
    for value in [
        assessment.profile.maximum_heldout_mae,
        assessment.profile.maximum_temporal_calibration_error,
        assessment.profile.maximum_drift_score,
        assessment.profile.maximum_confidence_half_width,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&assessment.effective_sample_size.to_be_bytes());
    bytes.extend_from_slice(&assessment.heldout_sample_count.to_be_bytes());
    bytes.extend_from_slice(&assessment.independent_snapshot_count.to_be_bytes());
    bytes.extend_from_slice(&assessment.future_window_count.to_be_bytes());
    for value in [
        assessment.heldout_mae,
        assessment.temporal_calibration_error,
        assessment.drift_score,
        assessment.confidence_half_width,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    push_id(&mut bytes, &assessment.evaluator_id);
    bytes.extend_from_slice(assessment.evaluator_credential_digest.as_array());
    bytes.extend_from_slice(assessment.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn q32_ratio(numerator: i64, denominator: i64) -> FixedQ32 {
        FixedQ32::from_raw((FixedQ32::ONE.raw() / denominator) * numerator)
    }

    fn profile() -> WorldModelQualificationProfileV1 {
        let mut profile = WorldModelQualificationProfileV1 {
            profile_digest: Digest32::ZERO,
            minimum_effective_samples: 200,
            minimum_heldout_samples: 200,
            minimum_independent_snapshots: 3,
            minimum_future_windows: 2,
            maximum_heldout_mae: q32_ratio(1, 10),
            maximum_temporal_calibration_error: q32_ratio(1, 10),
            maximum_drift_score: q32_ratio(1, 5),
            maximum_confidence_half_width: q32_ratio(1, 20),
        };
        profile.profile_digest = world_model_qualification_profile_digest(&profile);
        profile
    }

    fn assessment() -> WorldModelQualificationAssessmentV1 {
        WorldModelQualificationAssessmentV1 {
            model_id: id("world-model"),
            model_digest: digest("model"),
            dataset_digest: digest("dataset"),
            profile: profile(),
            effective_sample_size: 240,
            heldout_sample_count: 240,
            independent_snapshot_count: 3,
            future_window_count: 2,
            heldout_mae: q32_ratio(1, 20),
            temporal_calibration_error: q32_ratio(1, 20),
            drift_score: q32_ratio(1, 10),
            confidence_half_width: q32_ratio(1, 40),
            evaluator_id: id("independent-evaluator"),
            evaluator_credential_digest: digest("credential"),
            evidence_digest: digest("frozen-evidence"),
        }
    }

    #[test]
    fn qualification_admission_requires_support_future_windows_and_bounds() {
        let admitted = admit_world_model_qualification(assessment()).expect("admission");
        assert_eq!(admitted.future_window_count, 2);
        assert!(!admitted.assessment_digest.is_zero());
        assert!(!admitted.authority.grants_any());
    }

    #[test]
    fn qualification_admission_fails_closed_without_future_window_support() {
        let mut value = assessment();
        value.future_window_count = 1;
        assert_eq!(
            admit_world_model_qualification(value),
            Err(WorldModelQualificationError::InsufficientFutureWindows)
        );
    }

    #[test]
    fn qualification_admission_rejects_drift_beyond_profile() {
        let mut value = assessment();
        value.drift_score = FixedQ32::ONE;
        assert_eq!(
            admit_world_model_qualification(value),
            Err(WorldModelQualificationError::DriftExceeded)
        );
    }

    #[test]
    fn qualification_admission_rejects_relabelled_profile_thresholds() {
        let mut value = assessment();
        value.profile.maximum_drift_score = FixedQ32::ONE;
        assert_eq!(
            admit_world_model_qualification(value),
            Err(WorldModelQualificationError::InvalidProfile)
        );
    }
}
