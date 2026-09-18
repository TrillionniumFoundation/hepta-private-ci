use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduStochasticAdmissionEvidenceV1 {
    pub objective_digest: Digest32,
    pub coefficient_manifest_digest: Digest32,
    pub coordinate_conversion_receipt_digest: Digest32,
    pub conditional_identification_digest: Digest32,
    pub well_posedness_certificate_digest: Digest32,
    pub convergence_certificate_digest: Digest32,
}

/// A bounded stochastic profile whose numerical covariance convention and every
/// repository/external evidence gate are digest-bound.
///
/// This does not authenticate arbitrary digest bytes. The composition host must
/// obtain each digest from its authoritative owner; in particular the
/// convergence digest must come from an accepted `learning.eval` certificate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedNduStochasticProfileV1 {
    covariance_profile_digest: Digest32,
    admission_digest: Digest32,
    authority: AuthorityPosture,
}

impl AdmittedNduStochasticProfileV1 {
    #[must_use]
    pub const fn covariance_profile_digest(&self) -> Digest32 {
        self.covariance_profile_digest
    }

    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 {
        self.admission_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduStochasticAdmissionError {
    MissingEvidence(&'static str),
}

impl fmt::Display for NduStochasticAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduStochasticAdmissionError {}

pub fn admit_stochastic_profile_v1(
    evidence: &NduStochasticAdmissionEvidenceV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
) -> Result<AdmittedNduStochasticProfileV1, NduStochasticAdmissionError> {
    for (name, digest) in [
        ("objective", evidence.objective_digest),
        ("coefficient_manifest", evidence.coefficient_manifest_digest),
        (
            "coordinate_conversion",
            evidence.coordinate_conversion_receipt_digest,
        ),
        (
            "conditional_identification",
            evidence.conditional_identification_digest,
        ),
        (
            "well_posedness",
            evidence.well_posedness_certificate_digest,
        ),
        ("convergence", evidence.convergence_certificate_digest),
        ("covariance_profile", covariance_profile.digest()),
    ] {
        if digest.is_zero() {
            return Err(NduStochasticAdmissionError::MissingEvidence(name));
        }
    }

    let mut bytes = b"hepta.ndu.stochastic-admission.v1".to_vec();
    for digest in [
        evidence.objective_digest,
        evidence.coefficient_manifest_digest,
        covariance_profile.digest(),
        evidence.coordinate_conversion_receipt_digest,
        evidence.conditional_identification_digest,
        evidence.well_posedness_certificate_digest,
        evidence.convergence_certificate_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }

    Ok(AdmittedNduStochasticProfileV1 {
        covariance_profile_digest: covariance_profile.digest(),
        admission_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "stochastic_admission_tests.rs"]
mod tests;
