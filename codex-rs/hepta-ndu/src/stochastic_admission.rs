use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmittedCovarianceProfileV1;
use crate::ConditionalMomentsV1;
use crate::CovarianceError;
use crate::ZEstimateV1;
use crate::solve_backward_regression;

/// Owner-local binding of the evidence required before a stochastic NDU
/// coefficient/profile can leave shadow-only numeric use.
///
/// The digests identify externally authenticated artifacts and independent
/// evidence. This type does not authenticate those artifacts by itself and does
/// not select or activate a coefficient.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduStochasticEvidenceBindingV1 {
    pub artifact_id: StableId,
    pub objective_class_digest: Digest32,
    pub coefficient_manifest_digest: Digest32,
    pub normalization_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub conditioning_spec_digest: Digest32,
    pub q24_conversion_evidence_digest: Digest32,
    pub conditional_identification_evidence_digest: Digest32,
    pub well_posedness_certificate_digest: Digest32,
    pub independent_convergence_certificate_digest: Digest32,
    pub rollback_digest: Digest32,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedNduStochasticEvidenceV1 {
    pub binding: NduStochasticEvidenceBindingV1,
    pub covariance_profile_digest: Digest32,
    pub admission_digest: Digest32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BoundZEstimateV1 {
    pub estimate: ZEstimateV1,
    pub stochastic_admission_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduStochasticAdmissionError {
    MissingDigest(&'static str),
    ObjectiveClassMismatch,
    Expired,
    Covariance(CovarianceError),
}

impl fmt::Display for NduStochasticAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduStochasticAdmissionError {}

impl From<CovarianceError> for NduStochasticAdmissionError {
    fn from(value: CovarianceError) -> Self {
        Self::Covariance(value)
    }
}

/// Binds production-facing stochastic evidence to one admitted covariance
/// profile. Upstream remains responsible for authenticating every digest and
/// for proving that the independent certificates are current and applicable.
pub fn admit_stochastic_evidence_binding_v1(
    binding: NduStochasticEvidenceBindingV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    expected_objective_class_digest: Digest32,
    now_unix_ms: u64,
) -> Result<AdmittedNduStochasticEvidenceV1, NduStochasticAdmissionError> {
    require_digest(
        expected_objective_class_digest,
        "expected_objective_class",
    )?;
    for (digest, field) in [
        (binding.objective_class_digest, "objective_class"),
        (binding.coefficient_manifest_digest, "coefficient_manifest"),
        (binding.normalization_digest, "normalization"),
        (binding.runtime_tuple_digest, "runtime_tuple"),
        (binding.conditioning_spec_digest, "conditioning_spec"),
        (
            binding.q24_conversion_evidence_digest,
            "q24_conversion_evidence",
        ),
        (
            binding.conditional_identification_evidence_digest,
            "conditional_identification_evidence",
        ),
        (
            binding.well_posedness_certificate_digest,
            "well_posedness_certificate",
        ),
        (
            binding.independent_convergence_certificate_digest,
            "independent_convergence_certificate",
        ),
        (binding.rollback_digest, "rollback"),
    ] {
        require_digest(digest, field)?;
    }
    if binding.objective_class_digest != expected_objective_class_digest {
        return Err(NduStochasticAdmissionError::ObjectiveClassMismatch);
    }
    if binding.expires_unix_ms <= now_unix_ms {
        return Err(NduStochasticAdmissionError::Expired);
    }

    let covariance_profile_digest = covariance_profile.digest();
    let admission_digest = digest_admission(&binding, covariance_profile_digest);
    Ok(AdmittedNduStochasticEvidenceV1 {
        binding,
        covariance_profile_digest,
        admission_digest,
    })
}

/// Runs the existing bounded numeric kernel only while the evidence binding is
/// current and still names the exact admitted covariance profile.
pub fn solve_backward_regression_with_admission(
    moments: &ConditionalMomentsV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    admission: &AdmittedNduStochasticEvidenceV1,
    now_unix_ms: u64,
) -> Result<BoundZEstimateV1, NduStochasticAdmissionError> {
    if admission.binding.expires_unix_ms <= now_unix_ms {
        return Err(NduStochasticAdmissionError::Expired);
    }
    if admission.covariance_profile_digest != covariance_profile.digest() {
        return Err(NduStochasticAdmissionError::Covariance(
            CovarianceError::ProfileMismatch,
        ));
    }
    let estimate = solve_backward_regression(moments, covariance_profile)?;
    Ok(BoundZEstimateV1 {
        estimate,
        stochastic_admission_digest: admission.admission_digest,
    })
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduStochasticAdmissionError> {
    if digest.is_zero() {
        return Err(NduStochasticAdmissionError::MissingDigest(field));
    }
    Ok(())
}

fn digest_admission(
    binding: &NduStochasticEvidenceBindingV1,
    covariance_profile_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.stochastic-evidence-admission.v1".to_vec();
    push_id(&mut bytes, &binding.artifact_id);
    for digest in [
        binding.objective_class_digest,
        binding.coefficient_manifest_digest,
        binding.normalization_digest,
        binding.runtime_tuple_digest,
        binding.conditioning_spec_digest,
        binding.q24_conversion_evidence_digest,
        binding.conditional_identification_evidence_digest,
        binding.well_posedness_certificate_digest,
        binding.independent_convergence_certificate_digest,
        binding.rollback_digest,
        covariance_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&binding.expires_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::ConditionalMomentSampleV1;
    use crate::CovarianceConventionV1;
    use crate::NduCovarianceProfileV1;
    use crate::admit_covariance_profile;
    use crate::estimate_conditional_moments;

    fn id(value: &str) -> StableId {
        match StableId::new(value) {
            Ok(value) => value,
            Err(error) => panic!("invalid test id: {error:?}"),
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn profile() -> AdmittedCovarianceProfileV1 {
        match admit_covariance_profile(NduCovarianceProfileV1 {
            units_digest: digest("units"),
            driver_dimension: 1,
            utility_dimension: 1,
            convention: CovarianceConventionV1::Increment,
            minimum_increment_eigenvalue: 1e-9,
            maximum_condition: 1e6,
            maximum_absolute_sample: 1e6,
            maximum_absolute_z: 1e6,
            maximum_relative_residual: 1e-8,
        }) {
            Ok(value) => value,
            Err(error) => panic!("invalid test covariance profile: {error:?}"),
        }
    }

    fn binding() -> NduStochasticEvidenceBindingV1 {
        NduStochasticEvidenceBindingV1 {
            artifact_id: id("ndu-coefficient-1"),
            objective_class_digest: digest("objective-class"),
            coefficient_manifest_digest: digest("coefficient-manifest"),
            normalization_digest: digest("normalization"),
            runtime_tuple_digest: digest("runtime"),
            conditioning_spec_digest: digest("conditioning"),
            q24_conversion_evidence_digest: digest("q24-conversion"),
            conditional_identification_evidence_digest: digest("conditional-identification"),
            well_posedness_certificate_digest: digest("well-posedness"),
            independent_convergence_certificate_digest: digest("convergence"),
            rollback_digest: digest("rollback"),
            expires_unix_ms: 2_000,
        }
    }

    #[test]
    fn every_external_evidence_class_is_digest_bound() {
        let profile = profile();
        let admitted = match admit_stochastic_evidence_binding_v1(
            binding(),
            &profile,
            digest("objective-class"),
            1_000,
        ) {
            Ok(value) => value,
            Err(error) => panic!("unexpected admission error: {error:?}"),
        };
        assert!(!admitted.admission_digest.is_zero());

        let mut missing = binding();
        missing.conditional_identification_evidence_digest = Digest32::ZERO;
        assert_eq!(
            admit_stochastic_evidence_binding_v1(
                missing,
                &profile,
                digest("objective-class"),
                1_000,
            )
            .expect_err("missing identification evidence must reject"),
            NduStochasticAdmissionError::MissingDigest(
                "conditional_identification_evidence",
            )
        );
    }

    #[test]
    fn expired_or_wrong_objective_binding_rejects() {
        let profile = profile();
        assert_eq!(
            admit_stochastic_evidence_binding_v1(
                binding(),
                &profile,
                digest("wrong-objective"),
                1_000,
            )
            .expect_err("wrong objective must reject"),
            NduStochasticAdmissionError::ObjectiveClassMismatch
        );
        assert_eq!(
            admit_stochastic_evidence_binding_v1(
                binding(),
                &profile,
                digest("objective-class"),
                2_000,
            )
            .expect_err("expired evidence must reject"),
            NduStochasticAdmissionError::Expired
        );
    }

    #[test]
    fn admitted_evidence_is_bound_into_the_regression_result() {
        let profile = profile();
        let samples = [
            ConditionalMomentSampleV1 {
                conditioning_digest: digest("stratum"),
                duration_micros: 1_000_000,
                increment: vec![-1.0],
                utility: vec![-3.0],
            },
            ConditionalMomentSampleV1 {
                conditioning_digest: digest("stratum"),
                duration_micros: 1_000_000,
                increment: vec![1.0],
                utility: vec![3.0],
            },
        ];
        let moments = match estimate_conditional_moments(&samples, digest("source"), &profile) {
            Ok(value) => value,
            Err(error) => panic!("unexpected moment error: {error:?}"),
        };
        let admitted = match admit_stochastic_evidence_binding_v1(
            binding(),
            &profile,
            digest("objective-class"),
            1_000,
        ) {
            Ok(value) => value,
            Err(error) => panic!("unexpected admission error: {error:?}"),
        };
        let bound = match solve_backward_regression_with_admission(
            &moments,
            &profile,
            &admitted,
            1_500,
        ) {
            Ok(value) => value,
            Err(error) => panic!("unexpected regression error: {error:?}"),
        };
        assert_eq!(bound.stochastic_admission_digest, admitted.admission_digest);
        assert!((bound.estimate.z[0][0] - 3.0).abs() < 1e-12);
    }
}
