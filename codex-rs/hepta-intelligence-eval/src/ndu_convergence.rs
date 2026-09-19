use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_ITERATIONS: u32 = 64;
const MAX_RESIDUAL_Q32_RAW: i64 = 1_i64 << 12;
const SPECTRAL_RADIUS_LIMIT_Q32_RAW: i64 = (95_i64 * (1_i64 << 32)) / 100;
const MAX_CONSERVATION_RESIDUAL_Q32_RAW: i64 = 1;

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

/// Evaluator-owned evidence needed to issue an NDU convergence decision.
///
/// The producer identity and support digests are evaluator inputs rather than
/// fields of the canonical readiness certificate. They are nevertheless bound
/// into the owner-local certificate digest so a decision cannot be replayed
/// after substituting the independent evidence used to make it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceEvidenceV1 {
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
    pub candidate_producer_identity: StableId,
    pub perturbation_evidence_digest: Digest32,
    pub stability_evidence_digest: Digest32,
    pub conservation_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceCertificateV1 {
    certificate_id: StableId,
    subject_class: NduSubjectClassV1,
    objective_class_digest: Digest32,
    solver_digest: Digest32,
    initialization_digest: Digest32,
    iterations: u32,
    maximum_residual_q32: i64,
    spectral_radius_upper95_q32: i64,
    conservation_residual_q32: i64,
    multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    evaluator_identity: StableId,
    decision: NduConvergenceDecisionV1,
    certificate_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduConvergenceCertificateV1 {
    #[must_use]
    pub fn certificate_id(&self) -> &StableId {
        &self.certificate_id
    }

    #[must_use]
    pub const fn subject_class(&self) -> NduSubjectClassV1 {
        self.subject_class
    }

    #[must_use]
    pub const fn objective_class_digest(&self) -> Digest32 {
        self.objective_class_digest
    }

    #[must_use]
    pub const fn solver_digest(&self) -> Digest32 {
        self.solver_digest
    }

    #[must_use]
    pub const fn initialization_digest(&self) -> Digest32 {
        self.initialization_digest
    }

    #[must_use]
    pub const fn iterations(&self) -> u32 {
        self.iterations
    }

    #[must_use]
    pub const fn maximum_residual_q32(&self) -> i64 {
        self.maximum_residual_q32
    }

    #[must_use]
    pub const fn spectral_radius_upper95_q32(&self) -> i64 {
        self.spectral_radius_upper95_q32
    }

    #[must_use]
    pub const fn conservation_residual_q32(&self) -> i64 {
        self.conservation_residual_q32
    }

    #[must_use]
    pub const fn multiple_solution_disposition(&self) -> NduMultipleSolutionDispositionV1 {
        self.multiple_solution_disposition
    }

    #[must_use]
    pub fn evaluator_identity(&self) -> &StableId {
        &self.evaluator_identity
    }

    #[must_use]
    pub const fn decision(&self) -> NduConvergenceDecisionV1 {
        self.decision
    }

    #[must_use]
    pub const fn certificate_digest(&self) -> Digest32 {
        self.certificate_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConvergenceError {
    EmptyDigest(&'static str),
    SelfEvaluation,
    InvalidResidual,
    InvalidSpectralRadius,
    Arithmetic,
}

impl fmt::Display for NduConvergenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduConvergenceError {}

/// Issues the owner-local representation of NduConvergenceCertificateV1.
///
/// This function can reject or mark evidence unavailable, but it grants no
/// selection, activation, promotion or effect authority. Product activation
/// must still consume the certificate through its separately governed gate.
pub fn decide_ndu_convergence_v1(
    evidence: NduConvergenceEvidenceV1,
) -> Result<NduConvergenceCertificateV1, NduConvergenceError> {
    require_digest(evidence.objective_class_digest, "objective_class")?;
    require_digest(evidence.solver_digest, "solver")?;
    require_digest(evidence.initialization_digest, "initialization")?;
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduConvergenceError::SelfEvaluation);
    }
    if evidence.maximum_residual_q32 < 0 {
        return Err(NduConvergenceError::InvalidResidual);
    }
    if evidence.spectral_radius_upper95_q32 < 0 {
        return Err(NduConvergenceError::InvalidSpectralRadius);
    }

    let support_complete = !evidence.perturbation_evidence_digest.is_zero()
        && !evidence.stability_evidence_digest.is_zero()
        && !evidence.conservation_evidence_digest.is_zero();
    let unresolved = evidence.multiple_solution_disposition
        == NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved;
    let conservation = evidence
        .conservation_residual_q32
        .checked_abs()
        .ok_or(NduConvergenceError::Arithmetic)?;
    let thresholds_pass = evidence.iterations <= MAX_ITERATIONS
        && evidence.maximum_residual_q32 <= MAX_RESIDUAL_Q32_RAW
        && evidence.spectral_radius_upper95_q32 < SPECTRAL_RADIUS_LIMIT_Q32_RAW
        && conservation <= MAX_CONSERVATION_RESIDUAL_Q32_RAW;

    let decision = if !support_complete || unresolved {
        NduConvergenceDecisionV1::Unavailable
    } else if thresholds_pass {
        NduConvergenceDecisionV1::Accepted
    } else {
        NduConvergenceDecisionV1::Rejected
    };
    let certificate_digest = digest_certificate(&evidence, decision);
    Ok(NduConvergenceCertificateV1 {
        certificate_id: evidence.certificate_id,
        subject_class: evidence.subject_class,
        objective_class_digest: evidence.objective_class_digest,
        solver_digest: evidence.solver_digest,
        initialization_digest: evidence.initialization_digest,
        iterations: evidence.iterations,
        maximum_residual_q32: evidence.maximum_residual_q32,
        spectral_radius_upper95_q32: evidence.spectral_radius_upper95_q32,
        conservation_residual_q32: evidence.conservation_residual_q32,
        multiple_solution_disposition: evidence.multiple_solution_disposition,
        evaluator_identity: evidence.evaluator_identity,
        decision,
        certificate_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(value: Digest32, name: &'static str) -> Result<(), NduConvergenceError> {
    if value.is_zero() {
        Err(NduConvergenceError::EmptyDigest(name))
    } else {
        Ok(())
    }
}

fn digest_certificate(
    evidence: &NduConvergenceEvidenceV1,
    decision: NduConvergenceDecisionV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-certificate.v1".to_vec();
    push_id(&mut bytes, &evidence.certificate_id);
    bytes.push(evidence.subject_class.tag());
    bytes.extend_from_slice(evidence.objective_class_digest.as_array());
    bytes.extend_from_slice(evidence.solver_digest.as_array());
    bytes.extend_from_slice(evidence.initialization_digest.as_array());
    bytes.extend_from_slice(&evidence.iterations.to_be_bytes());
    bytes.extend_from_slice(&evidence.maximum_residual_q32.to_be_bytes());
    bytes.extend_from_slice(&evidence.spectral_radius_upper95_q32.to_be_bytes());
    bytes.extend_from_slice(&evidence.conservation_residual_q32.to_be_bytes());
    bytes.push(evidence.multiple_solution_disposition.tag());
    push_id(&mut bytes, &evidence.evaluator_identity);
    bytes.push(decision.tag());
    push_id(&mut bytes, &evidence.candidate_producer_identity);
    bytes.extend_from_slice(evidence.perturbation_evidence_digest.as_array());
    bytes.extend_from_slice(evidence.stability_evidence_digest.as_array());
    bytes.extend_from_slice(evidence.conservation_evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_convergence_tests.rs"]
mod tests;
