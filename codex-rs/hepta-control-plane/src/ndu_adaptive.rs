use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence_eval::NduConvergenceCertificateV1;
use codex_hepta_intelligence_eval::NduConvergenceError;
use codex_hepta_intelligence_eval::NduConvergenceExpectationV1;
use codex_hepta_intelligence_eval::validate_ndu_convergence_certificate_v1;
use codex_hepta_ndu::AdmittedCovarianceProfileV1;
use codex_hepta_ndu::AdmittedNduStochasticProfileV1;
use codex_hepta_ndu::NduStochasticAdmissionError;
use codex_hepta_ndu::NduStochasticAdmissionEvidenceV1;
use codex_hepta_ndu::admit_stochastic_profile_v1;
use codex_hepta_types::Digest32;

pub struct NduAdaptiveAdmissionInputV1<'a> {
    pub convergence_certificate: &'a NduConvergenceCertificateV1,
    pub convergence_expectation: NduConvergenceExpectationV1,
    pub covariance_profile: &'a AdmittedCovarianceProfileV1,
    pub objective_digest: Digest32,
    pub coefficient_manifest_digest: Digest32,
    pub coordinate_conversion_receipt_digest: Digest32,
    pub conditional_identification_digest: Digest32,
    pub well_posedness_certificate_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduAdaptiveAdmissionError {
    Convergence(NduConvergenceError),
    Ndu(NduStochasticAdmissionError),
}

impl fmt::Display for NduAdaptiveAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduAdaptiveAdmissionError {}

/// Compose the independent learning.eval decision with NDU owner admission.
///
/// The convergence certificate is revalidated against the current frozen
/// subject/objective-class/solver/initialization context immediately before its
/// digest is consumed by the NDU stochastic admission boundary.
pub fn admit_adaptive_ndu_profile_v1(
    input: NduAdaptiveAdmissionInputV1<'_>,
) -> Result<AdmittedNduStochasticProfileV1, NduAdaptiveAdmissionError> {
    let convergence_digest = validate_ndu_convergence_certificate_v1(
        input.convergence_certificate,
        &input.convergence_expectation,
    )
    .map_err(NduAdaptiveAdmissionError::Convergence)?;

    admit_stochastic_profile_v1(
        &NduStochasticAdmissionEvidenceV1 {
            objective_digest: input.objective_digest,
            coefficient_manifest_digest: input.coefficient_manifest_digest,
            coordinate_conversion_receipt_digest: input.coordinate_conversion_receipt_digest,
            conditional_identification_digest: input.conditional_identification_digest,
            well_posedness_certificate_digest: input.well_posedness_certificate_digest,
            convergence_certificate_digest: convergence_digest,
        },
        input.covariance_profile,
    )
    .map_err(NduAdaptiveAdmissionError::Ndu)
}

#[cfg(test)]
#[path = "ndu_adaptive_tests.rs"]
mod tests;
