//! Authority-free composition of an NDU stochastic candidate with independent
//! evaluator evidence.
//!
//! This adapter proves source-level semantic compatibility only. It does not
//! select, activate, promote, dispatch or release the candidate.

use std::error::Error;
use std::fmt;

use codex_hepta_intelligence_eval::NduConvergenceCertificateV1;
use codex_hepta_intelligence_eval::NduConvergenceDecisionV1;
use codex_hepta_intelligence_eval::NduWellPosednessCertificateV1;
use codex_hepta_intelligence_eval::NduWellPosednessDecisionV1;
use codex_hepta_ndu::AdmittedNduCoefficientProfileV1;
use codex_hepta_ndu::NduZQ24ProjectionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug)]
pub struct NduStochasticAdmissionRequestV1<'a> {
    pub coefficient_profile: &'a AdmittedNduCoefficientProfileV1,
    pub z_projection: &'a NduZQ24ProjectionV1,
    pub convergence: &'a NduConvergenceCertificateV1,
    pub well_posedness: &'a NduWellPosednessCertificateV1,
    pub objective_class_digest: Digest32,
    pub operating_domain_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduStochasticAdmissionReceiptV1 {
    pub objective_class_digest: Digest32,
    pub operating_domain_digest: Digest32,
    pub coefficient_profile_digest: Digest32,
    pub z_output_digest: Digest32,
    pub solver_digest: Digest32,
    pub convergence_certificate_digest: Digest32,
    pub well_posedness_certificate_digest: Digest32,
    pub admission_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduStochasticAdmissionError {
    EmptyDigest(&'static str),
    AuthorityEscalation(&'static str),
    Expired(&'static str),
    CoefficientProfileMismatch,
    ObjectiveClassMismatch,
    OperatingDomainMismatch,
    SolverMismatch,
    ConvergenceNotAccepted,
    WellPosednessNotAccepted,
}

impl fmt::Display for NduStochasticAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduStochasticAdmissionError {}

/// Canonical source-level identity of the exact stochastic solver output being
/// independently evaluated. A convergence certificate must bind this digest.
pub fn canonical_ndu_stochastic_solver_digest_v1(
    coefficient_profile: &AdmittedNduCoefficientProfileV1,
    z_projection: &NduZQ24ProjectionV1,
) -> Result<Digest32, NduStochasticAdmissionError> {
    require_digest(coefficient_profile.digest(), "coefficient_profile")?;
    require_digest(coefficient_profile.manifest_digest(), "coefficient_manifest")?;
    require_digest(coefficient_profile.coordinate_digest(), "coordinate")?;
    require_digest(z_projection.source_evidence_digest(), "z_source_evidence")?;
    require_digest(z_projection.output_digest(), "z_output")?;
    require_digest(
        z_projection.conversion_evidence_digest(),
        "z_conversion_evidence",
    )?;
    if z_projection.coefficient_profile_digest() != coefficient_profile.digest() {
        return Err(NduStochasticAdmissionError::CoefficientProfileMismatch);
    }
    if z_projection.authority().grants_any() {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "z_projection",
        ));
    }

    let mut bytes = b"hepta.intelligence.ndu-stochastic-solver.v1".to_vec();
    bytes.extend_from_slice(coefficient_profile.digest().as_array());
    bytes.extend_from_slice(coefficient_profile.manifest_digest().as_array());
    bytes.extend_from_slice(coefficient_profile.coordinate_digest().as_array());
    bytes.extend_from_slice(z_projection.source_evidence_digest().as_array());
    bytes.extend_from_slice(z_projection.output_digest().as_array());
    bytes.extend_from_slice(z_projection.conversion_evidence_digest().as_array());
    Ok(Digest32::of_bytes(&bytes))
}

/// Requires both evaluator-owned decisions to accept the exact source-level
/// solver identity before producing an authority-free admission receipt.
pub fn admit_ndu_stochastic_candidate_v1(
    request: NduStochasticAdmissionRequestV1<'_>,
    now_unix_ms: u64,
) -> Result<NduStochasticAdmissionReceiptV1, NduStochasticAdmissionError> {
    require_digest(request.objective_class_digest, "objective_class")?;
    require_digest(request.operating_domain_digest, "operating_domain")?;
    if now_unix_ms >= request.coefficient_profile.expires_unix_ms() {
        return Err(NduStochasticAdmissionError::Expired(
            "coefficient_profile",
        ));
    }
    if request.z_projection.authority().grants_any() {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "z_projection",
        ));
    }
    if request.convergence.authority().grants_any() {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "convergence",
        ));
    }
    if request.well_posedness.authority().grants_any() {
        return Err(NduStochasticAdmissionError::AuthorityEscalation(
            "well_posedness",
        ));
    }
    if request.convergence.decision() != NduConvergenceDecisionV1::Accepted {
        return Err(NduStochasticAdmissionError::ConvergenceNotAccepted);
    }
    if request.well_posedness.decision() != NduWellPosednessDecisionV1::Accepted {
        return Err(NduStochasticAdmissionError::WellPosednessNotAccepted);
    }
    if now_unix_ms >= request.well_posedness.expires_unix_ms() {
        return Err(NduStochasticAdmissionError::Expired("well_posedness"));
    }
    if request.well_posedness.manifest_digest()
        != request.coefficient_profile.manifest_digest()
    {
        return Err(NduStochasticAdmissionError::CoefficientProfileMismatch);
    }
    if request.convergence.objective_class_digest() != request.objective_class_digest {
        return Err(NduStochasticAdmissionError::ObjectiveClassMismatch);
    }
    if request.well_posedness.operating_domain_digest() != request.operating_domain_digest {
        return Err(NduStochasticAdmissionError::OperatingDomainMismatch);
    }

    let solver_digest = canonical_ndu_stochastic_solver_digest_v1(
        request.coefficient_profile,
        request.z_projection,
    )?;
    if request.convergence.solver_digest() != solver_digest {
        return Err(NduStochasticAdmissionError::SolverMismatch);
    }

    let convergence_certificate_digest = request.convergence.certificate_digest();
    let well_posedness_certificate_digest = request.well_posedness.certificate_digest();
    require_digest(convergence_certificate_digest, "convergence_certificate")?;
    require_digest(
        well_posedness_certificate_digest,
        "well_posedness_certificate",
    )?;

    let mut bytes = b"hepta.intelligence.ndu-stochastic-admission.v1".to_vec();
    bytes.extend_from_slice(request.objective_class_digest.as_array());
    bytes.extend_from_slice(request.operating_domain_digest.as_array());
    bytes.extend_from_slice(request.coefficient_profile.digest().as_array());
    bytes.extend_from_slice(request.z_projection.output_digest().as_array());
    bytes.extend_from_slice(solver_digest.as_array());
    bytes.extend_from_slice(convergence_certificate_digest.as_array());
    bytes.extend_from_slice(well_posedness_certificate_digest.as_array());

    Ok(NduStochasticAdmissionReceiptV1 {
        objective_class_digest: request.objective_class_digest,
        operating_domain_digest: request.operating_domain_digest,
        coefficient_profile_digest: request.coefficient_profile.digest(),
        z_output_digest: request.z_projection.output_digest(),
        solver_digest,
        convergence_certificate_digest,
        well_posedness_certificate_digest,
        admission_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduStochasticAdmissionError> {
    if value.is_zero() {
        Err(NduStochasticAdmissionError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

#[cfg(test)]
#[path = "ndu_stochastic_admission_tests.rs"]
mod tests;
