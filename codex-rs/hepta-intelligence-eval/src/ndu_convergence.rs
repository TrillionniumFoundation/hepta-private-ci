use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_ITERATIONS: u32 = 64;
const MAXIMUM_RESIDUAL_RAW: i64 = 1_i64 << 12;
// ceil(0.95 * 2^32). Values at or above this raw integer are not < 0.95.
const SPECTRAL_RADIUS_UPPER_95_REJECT_AT_RAW: i64 = 4_080_218_932;
const CONSERVATION_RESIDUAL_LIMIT_RAW: i64 = 1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduSubjectClassV1 {
    System,
    Domain,
    Agent,
    Episode,
}

impl NduSubjectClassV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::System => 0,
            Self::Domain => 1,
            Self::Agent => 2,
            Self::Episode => 3,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduMultipleSolutionDispositionV1 {
    Unique,
    PredecessorNearestCertified,
    MultipleSolutionUnresolved,
    InvalidEvaluatorIdentity,
}

impl NduMultipleSolutionDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Unique => 0,
            Self::PredecessorNearestCertified => 1,
            Self::MultipleSolutionUnresolved => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConvergenceDecisionV1 {
    Accepted,
    Rejected,
    Unavailable,
}

impl NduConvergenceDecisionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Accepted => 0,
            Self::Rejected => 1,
            Self::Unavailable => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceCertificateV1 {
    pub certificate_id: StableId,
    pub subject_class: NduSubjectClassV1,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub iterations: u32,
    pub maximum_residual_raw: i64,
    pub spectral_radius_upper_95_raw: i64,
    pub conservation_residual_raw: i64,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    /// Canonical protocol permits bounded UTF-8 up to 256 bytes.
    pub evaluator_identity: String,
    pub decision: NduConvergenceDecisionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceAdmissionV1 {
    pub certificate: NduConvergenceCertificateV1,
    pub certificate_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceAdmissionContextV1 {
    pub expected_objective_class_digest: Digest32,
    pub expected_solver_digest: Digest32,
    pub candidate_producer_identity: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConvergenceAdmissionError {
    MissingDigest(&'static str),
    ObjectiveMismatch,
    SolverMismatch,
    SelfEvaluation,
    IterationBoundExceeded,
    NegativeDiagnostic,
    ResidualGate,
    SpectralRadiusGate,
    ConservationGate,
    MultipleSolutionUnresolved,
}

impl fmt::Display for NduConvergenceAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduConvergenceAdmissionError {}

/// Admit an independently issued NDU convergence certificate for consumption.
///
/// This validates the canonical safety gates but does not issue the certificate,
/// select an artifact, activate a runtime, or grant effect authority.
pub fn admit_ndu_convergence_certificate_v1(
    certificate: NduConvergenceCertificateV1,
    context: &NduConvergenceAdmissionContextV1,
) -> Result<NduConvergenceAdmissionV1, NduConvergenceAdmissionError> {
    require_digest(certificate.objective_class_digest, "objective_class")?;
    require_digest(certificate.solver_digest, "solver")?;
    require_digest(certificate.initialization_digest, "initialization")?;
    require_digest(
        context.expected_objective_class_digest,
        "expected_objective_class",
    )?;
    require_digest(context.expected_solver_digest, "expected_solver")?;

    if certificate.objective_class_digest != context.expected_objective_class_digest {
        return Err(NduConvergenceAdmissionError::ObjectiveMismatch);
    }
    if certificate.solver_digest != context.expected_solver_digest {
        return Err(NduConvergenceAdmissionError::SolverMismatch);
    }
    if certificate.evaluator_identity.is_empty() || certificate.evaluator_identity.len() > 256 {
        return Err(NduConvergenceAdmissionError::InvalidEvaluatorIdentity);
    }
    if certificate.evaluator_identity.as_str() == context.candidate_producer_identity.as_str() {
        return Err(NduConvergenceAdmissionError::SelfEvaluation);
    }
    if certificate.iterations > MAX_ITERATIONS {
        return Err(NduConvergenceAdmissionError::IterationBoundExceeded);
    }
    if certificate.maximum_residual_raw < 0
        || certificate.spectral_radius_upper_95_raw < 0
        || certificate.conservation_residual_raw < 0
    {
        return Err(NduConvergenceAdmissionError::NegativeDiagnostic);
    }

    if certificate.decision == NduConvergenceDecisionV1::Accepted {
        if certificate.maximum_residual_raw > MAXIMUM_RESIDUAL_RAW {
            return Err(NduConvergenceAdmissionError::ResidualGate);
        }
        if certificate.spectral_radius_upper_95_raw >= SPECTRAL_RADIUS_UPPER_95_REJECT_AT_RAW {
            return Err(NduConvergenceAdmissionError::SpectralRadiusGate);
        }
        if certificate.conservation_residual_raw > CONSERVATION_RESIDUAL_LIMIT_RAW {
            return Err(NduConvergenceAdmissionError::ConservationGate);
        }
        if certificate.multiple_solution_disposition
            == NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved
        {
            return Err(NduConvergenceAdmissionError::MultipleSolutionUnresolved);
        }
    }

    let certificate_digest = digest_certificate(&certificate);
    Ok(NduConvergenceAdmissionV1 {
        certificate,
        certificate_digest,
    })
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduConvergenceAdmissionError> {
    if digest.is_zero() {
        return Err(NduConvergenceAdmissionError::MissingDigest(field));
    }
    Ok(())
}

fn digest_certificate(certificate: &NduConvergenceCertificateV1) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-certificate.v1".to_vec();
    push_id(&mut bytes, &certificate.certificate_id);
    bytes.push(certificate.subject_class.tag());
    bytes.extend_from_slice(certificate.objective_class_digest.as_array());
    bytes.extend_from_slice(certificate.solver_digest.as_array());
    bytes.extend_from_slice(certificate.initialization_digest.as_array());
    bytes.extend_from_slice(&certificate.iterations.to_be_bytes());
    bytes.extend_from_slice(&certificate.maximum_residual_raw.to_be_bytes());
    bytes.extend_from_slice(&certificate.spectral_radius_upper_95_raw.to_be_bytes());
    bytes.extend_from_slice(&certificate.conservation_residual_raw.to_be_bytes());
    bytes.push(certificate.multiple_solution_disposition.tag());
    push_text(&mut bytes, &certificate.evaluator_identity);
    bytes.push(certificate.decision.tag());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_convergence_tests.rs"]
mod tests;
