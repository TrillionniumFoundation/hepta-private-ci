use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_ITERATIONS: u32 = 64;
const MAXIMUM_RESIDUAL_Q32_RAW: i64 = 1_i64 << 12;
const MAXIMUM_CONSERVATION_RESIDUAL_Q32_RAW: i64 = 1;
const Q32_ONE_RAW: i128 = 1_i128 << 32;

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

/// Independent evidence consumed by learning.eval. Support digests bind the
/// evaluator-owned operating region, perturbation suite, stability computation
/// and normalized conservation calculation; this function does not manufacture
/// those observations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceEvidenceV1 {
    pub certificate_id: StableId,
    pub subject_class: NduSubjectClassV1,
    pub objective_class_digest: Digest32,
    pub current_objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub iterations: u32,
    pub maximum_residual_q32: i64,
    pub spectral_radius_upper95_q32: i64,
    pub conservation_residual_q32: i64,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    pub operating_region_digest: Digest32,
    pub perturbation_support_digest: Digest32,
    pub stability_support_digest: Digest32,
    pub conservation_support_digest: Digest32,
}

/// Native representation of the canonical NduConvergenceCertificateV1 fields.
/// It is eligibility evidence only and carries no selection or activation
/// authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceCertificateV1 {
    pub certificate_id: StableId,
    pub subject_class: NduSubjectClassV1,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub iterations: u32,
    pub maximum_residual_q32: i64,
    pub spectral_radius_upper95_q32: i64,
    pub conservation_residual_q32: i64,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    pub evaluator_identity: StableId,
    pub decision: NduConvergenceDecisionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduConvergenceError {
    SelfEvaluation,
    MissingDigest(&'static str),
    IterationLimit,
    NegativeDiagnostic(&'static str),
}

impl fmt::Display for NduConvergenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduConvergenceError {}

/// Applies the canonical repository-controlled NDU convergence gates. Real
/// independence, perturbation observations and target-host evidence remain
/// external evidence obligations.
pub fn evaluate_ndu_convergence_v1(
    evidence: &NduConvergenceEvidenceV1,
) -> Result<NduConvergenceCertificateV1, NduConvergenceError> {
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduConvergenceError::SelfEvaluation);
    }
    for (name, digest) in [
        ("objective class", evidence.objective_class_digest),
        ("current objective class", evidence.current_objective_class_digest),
        ("solver", evidence.solver_digest),
        ("initialization", evidence.initialization_digest),
        ("operating region", evidence.operating_region_digest),
    ] {
        require_digest(name, digest)?;
    }
    if evidence.iterations > MAX_ITERATIONS {
        return Err(NduConvergenceError::IterationLimit);
    }
    for (name, value) in [
        ("maximum residual", evidence.maximum_residual_q32),
        ("spectral radius upper 95", evidence.spectral_radius_upper95_q32),
        ("conservation residual", evidence.conservation_residual_q32),
    ] {
        if value < 0 {
            return Err(NduConvergenceError::NegativeDiagnostic(name));
        }
    }

    let support_available = [
        evidence.perturbation_support_digest,
        evidence.stability_support_digest,
        evidence.conservation_support_digest,
    ]
    .iter()
    .all(|digest| !digest.is_zero());

    let stale_objective =
        evidence.objective_class_digest != evidence.current_objective_class_digest;
    let residual_failed = evidence.maximum_residual_q32 > MAXIMUM_RESIDUAL_Q32_RAW;
    let conservation_failed =
        evidence.conservation_residual_q32 > MAXIMUM_CONSERVATION_RESIDUAL_Q32_RAW;
    let spectral_failed = !spectral_radius_below_095(evidence.spectral_radius_upper95_q32);

    let decision = if !support_available
        || evidence.multiple_solution_disposition
            == NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved
    {
        NduConvergenceDecisionV1::Unavailable
    } else if stale_objective || residual_failed || conservation_failed || spectral_failed {
        NduConvergenceDecisionV1::Rejected
    } else {
        NduConvergenceDecisionV1::Accepted
    };

    Ok(NduConvergenceCertificateV1 {
        certificate_id: evidence.certificate_id.clone(),
        subject_class: evidence.subject_class,
        objective_class_digest: evidence.objective_class_digest,
        solver_digest: evidence.solver_digest,
        initialization_digest: evidence.initialization_digest,
        iterations: evidence.iterations,
        maximum_residual_q32: evidence.maximum_residual_q32,
        spectral_radius_upper95_q32: evidence.spectral_radius_upper95_q32,
        conservation_residual_q32: evidence.conservation_residual_q32,
        multiple_solution_disposition: evidence.multiple_solution_disposition,
        evaluator_identity: evidence.evaluator_identity.clone(),
        decision,
    })
}

pub fn canonical_ndu_convergence_certificate_digest_v1(
    certificate: &NduConvergenceCertificateV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-certificate.v1".to_vec();
    push_id(&mut bytes, &certificate.certificate_id);
    bytes.push(certificate.subject_class.tag());
    bytes.extend_from_slice(certificate.objective_class_digest.as_array());
    bytes.extend_from_slice(certificate.solver_digest.as_array());
    bytes.extend_from_slice(certificate.initialization_digest.as_array());
    bytes.extend_from_slice(&certificate.iterations.to_be_bytes());
    bytes.extend_from_slice(&certificate.maximum_residual_q32.to_be_bytes());
    bytes.extend_from_slice(&certificate.spectral_radius_upper95_q32.to_be_bytes());
    bytes.extend_from_slice(&certificate.conservation_residual_q32.to_be_bytes());
    bytes.push(certificate.multiple_solution_disposition.tag());
    push_id(&mut bytes, &certificate.evaluator_identity);
    bytes.push(certificate.decision.tag());
    Digest32::of_bytes(&bytes)
}

fn spectral_radius_below_095(raw: i64) -> bool {
    i128::from(raw) * 100 < 95 * Q32_ONE_RAW
}

fn require_digest(name: &'static str, digest: Digest32) -> Result<(), NduConvergenceError> {
    if digest.is_zero() {
        return Err(NduConvergenceError::MissingDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_convergence_tests.rs"]
mod tests;
