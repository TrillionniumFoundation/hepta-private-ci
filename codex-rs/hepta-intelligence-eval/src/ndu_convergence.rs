use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

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

/// Registered independent convergence thresholds. These are frozen before
/// candidate evidence is evaluated.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergencePolicyV1 {
    pub policy_id: StableId,
    pub maximum_iterations: u32,
    pub maximum_residual_q32: FixedQ32,
    /// Accepted evidence must be strictly below this upper confidence bound.
    pub maximum_spectral_radius_upper95_q32: FixedQ32,
    pub maximum_conservation_residual_q32: FixedQ32,
}

/// Evidence supplied to the independent evaluator. The candidate producer
/// identity is deliberately separate from evaluator identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceEvidenceV1 {
    pub certificate_id: StableId,
    pub subject_class: NduSubjectClassV1,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub iterations: u32,
    pub maximum_residual_q32: FixedQ32,
    pub spectral_radius_upper95_q32: FixedQ32,
    pub conservation_residual_q32: FixedQ32,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    /// Independent evidence bundle identity. Zero means evidence is unavailable.
    pub support_digest: Digest32,
}

/// Owner-issued representation of readiness protocol
/// `NduConvergenceCertificateV1`. Fields are private so external crates cannot
/// fabricate an accepted certificate with a struct literal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceCertificateV1 {
    certificate_id: StableId,
    subject_class: NduSubjectClassV1,
    objective_class_digest: Digest32,
    solver_digest: Digest32,
    initialization_digest: Digest32,
    iterations: u32,
    maximum_residual_q32: FixedQ32,
    spectral_radius_upper95_q32: FixedQ32,
    conservation_residual_q32: FixedQ32,
    multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    evaluator_identity: StableId,
    decision: NduConvergenceDecisionV1,
    certificate_digest: Digest32,
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
    pub const fn maximum_residual_q32(&self) -> FixedQ32 {
        self.maximum_residual_q32
    }

    #[must_use]
    pub const fn spectral_radius_upper95_q32(&self) -> FixedQ32 {
        self.spectral_radius_upper95_q32
    }

    #[must_use]
    pub const fn conservation_residual_q32(&self) -> FixedQ32 {
        self.conservation_residual_q32
    }

    #[must_use]
    pub const fn multiple_solution_disposition(
        &self,
    ) -> NduMultipleSolutionDispositionV1 {
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceExpectationV1 {
    pub subject_class: NduSubjectClassV1,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduConvergenceError {
    SelfEvaluation,
    MissingDigest(&'static str),
    InvalidPolicy,
    InvalidMetric(&'static str),
    ContextMismatch(&'static str),
    NotAccepted,
    DigestMismatch,
}

impl fmt::Display for NduConvergenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduConvergenceError {}

pub fn issue_ndu_convergence_certificate_v1(
    evidence: NduConvergenceEvidenceV1,
    policy: &NduConvergencePolicyV1,
) -> Result<NduConvergenceCertificateV1, NduConvergenceError> {
    validate_policy(policy)?;
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduConvergenceError::SelfEvaluation);
    }
    require_digest(evidence.objective_class_digest, "objective_class")?;
    require_digest(evidence.solver_digest, "solver")?;
    require_digest(evidence.initialization_digest, "initialization")?;
    validate_nonnegative(evidence.maximum_residual_q32, "maximum_residual")?;
    validate_nonnegative(
        evidence.spectral_radius_upper95_q32,
        "spectral_radius_upper95",
    )?;
    validate_nonnegative(
        evidence.conservation_residual_q32,
        "conservation_residual",
    )?;

    let decision = if evidence.support_digest.is_zero()
        || evidence.iterations == 0
        || evidence.iterations > policy.maximum_iterations
    {
        NduConvergenceDecisionV1::Unavailable
    } else if evidence.maximum_residual_q32 > policy.maximum_residual_q32
        || evidence.spectral_radius_upper95_q32
            >= policy.maximum_spectral_radius_upper95_q32
        || evidence.conservation_residual_q32 > policy.maximum_conservation_residual_q32
        || evidence.multiple_solution_disposition
            == NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved
    {
        NduConvergenceDecisionV1::Rejected
    } else {
        NduConvergenceDecisionV1::Accepted
    };

    let mut certificate = NduConvergenceCertificateV1 {
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
        certificate_digest: Digest32::ZERO,
    };
    certificate.certificate_digest = digest_certificate(&certificate);
    Ok(certificate)
}

/// Consumer-side admission for a current frozen context. An accepted decision
/// alone is insufficient: all context digests and the canonical certificate
/// digest are revalidated at the point of use.
pub fn validate_ndu_convergence_certificate_v1(
    certificate: &NduConvergenceCertificateV1,
    expectation: &NduConvergenceExpectationV1,
) -> Result<Digest32, NduConvergenceError> {
    if certificate.certificate_digest != digest_certificate(certificate) {
        return Err(NduConvergenceError::DigestMismatch);
    }
    if certificate.decision != NduConvergenceDecisionV1::Accepted {
        return Err(NduConvergenceError::NotAccepted);
    }
    if certificate.subject_class != expectation.subject_class {
        return Err(NduConvergenceError::ContextMismatch("subject_class"));
    }
    if certificate.objective_class_digest != expectation.objective_class_digest {
        return Err(NduConvergenceError::ContextMismatch("objective_class"));
    }
    if certificate.solver_digest != expectation.solver_digest {
        return Err(NduConvergenceError::ContextMismatch("solver"));
    }
    if certificate.initialization_digest != expectation.initialization_digest {
        return Err(NduConvergenceError::ContextMismatch("initialization"));
    }
    Ok(certificate.certificate_digest)
}

fn validate_policy(policy: &NduConvergencePolicyV1) -> Result<(), NduConvergenceError> {
    if policy.maximum_iterations == 0
        || policy.maximum_residual_q32 < FixedQ32::ZERO
        || policy.maximum_spectral_radius_upper95_q32 <= FixedQ32::ZERO
        || policy.maximum_spectral_radius_upper95_q32 > FixedQ32::ONE
        || policy.maximum_conservation_residual_q32 < FixedQ32::ZERO
    {
        return Err(NduConvergenceError::InvalidPolicy);
    }
    Ok(())
}

fn validate_nonnegative(
    value: FixedQ32,
    field: &'static str,
) -> Result<(), NduConvergenceError> {
    if value < FixedQ32::ZERO {
        Err(NduConvergenceError::InvalidMetric(field))
    } else {
        Ok(())
    }
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduConvergenceError> {
    if value.is_zero() {
        Err(NduConvergenceError::MissingDigest(field))
    } else {
        Ok(())
    }
}

fn digest_certificate(certificate: &NduConvergenceCertificateV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.convergence-certificate.v1".to_vec();
    push_id(&mut bytes, &certificate.certificate_id);
    bytes.push(certificate.subject_class.tag());
    bytes.extend_from_slice(certificate.objective_class_digest.as_array());
    bytes.extend_from_slice(certificate.solver_digest.as_array());
    bytes.extend_from_slice(certificate.initialization_digest.as_array());
    bytes.extend_from_slice(&certificate.iterations.to_be_bytes());
    bytes.extend_from_slice(&certificate.maximum_residual_q32.raw().to_be_bytes());
    bytes.extend_from_slice(
        &certificate
            .spectral_radius_upper95_q32
            .raw()
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &certificate
            .conservation_residual_q32
            .raw()
            .to_be_bytes(),
    );
    bytes.push(certificate.multiple_solution_disposition.tag());
    push_id(&mut bytes, &certificate.evaluator_identity);
    bytes.push(certificate.decision.tag());
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
