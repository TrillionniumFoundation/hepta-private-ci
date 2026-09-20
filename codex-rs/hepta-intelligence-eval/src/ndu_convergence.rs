use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
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
    candidate_producer_identity: StableId,
    trust_digest: Digest32,
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
    pub fn candidate_producer_identity(&self) -> &StableId {
        &self.candidate_producer_identity
    }
    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduConvergenceError {
    EmptyDigest(&'static str),
    ObjectiveContextMismatch,
    InvalidResidual,
    InvalidSpectralRadius,
    SignedEvidence(SignedEvidenceError),
    Arithmetic,
}

impl fmt::Display for NduConvergenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for NduConvergenceError {}

impl From<SignedEvidenceError> for NduConvergenceError {
    fn from(error: SignedEvidenceError) -> Self {
        Self::SignedEvidence(error)
    }
}

/// Learning evaluation independently decides convergence from signed producer
/// and evaluator evidence admitted against one host-owned trust snapshot. The
/// resulting certificate grants no selection, activation or effect authority.
pub fn decide_ndu_convergence_v1(
    evidence: NduConvergenceEvidenceV1,
    producer: &SignedLearningEvidenceV1,
    evaluator: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<NduConvergenceCertificateV1, NduConvergenceError> {
    require_digest(evidence.objective_class_digest, "objective_class")?;
    require_digest(evidence.solver_digest, "solver")?;
    require_digest(evidence.initialization_digest, "initialization")?;
    if evidence.objective_class_digest != verifier.objective_digest() {
        return Err(NduConvergenceError::ObjectiveContextMismatch);
    }
    if evidence.maximum_residual_q32 < 0 {
        return Err(NduConvergenceError::InvalidResidual);
    }
    if evidence.spectral_radius_upper95_q32 < 0 {
        return Err(NduConvergenceError::InvalidSpectralRadius);
    }

    let producer_payload = producer_payload(&evidence);
    let evaluator_payload = evaluator_payload(&evidence);
    let producer_verified =
        verifier.verify(LearningEvidenceRoleV1::Generator, producer, &producer_payload, now)?;
    let evaluator_verified =
        verifier.verify(LearningEvidenceRoleV1::Evaluator, evaluator, &evaluator_payload, now)?;
    verify_signed_role_separation(&producer_verified, &evaluator_verified, now)?;

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

    let evaluator_identity = evaluator_verified.principal().principal_id.clone();
    let candidate_producer_identity = producer_verified.principal().principal_id.clone();
    let trust_digest = verifier.trust_digest();
    let certificate_digest = digest_certificate(
        &evidence,
        decision,
        &candidate_producer_identity,
        &evaluator_identity,
        trust_digest,
        producer_verified.payload_digest(),
        evaluator_verified.payload_digest(),
    );
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
        evaluator_identity,
        candidate_producer_identity,
        trust_digest,
        decision,
        certificate_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn producer_payload(evidence: &NduConvergenceEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-producer.v1\0".to_vec();
    bytes.extend_from_slice(evidence.objective_class_digest.as_array());
    bytes.extend_from_slice(evidence.solver_digest.as_array());
    bytes.extend_from_slice(evidence.initialization_digest.as_array());
    bytes
}

fn evaluator_payload(evidence: &NduConvergenceEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-evaluator.v1\0".to_vec();
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
    bytes.extend_from_slice(evidence.perturbation_evidence_digest.as_array());
    bytes.extend_from_slice(evidence.stability_evidence_digest.as_array());
    bytes.extend_from_slice(evidence.conservation_evidence_digest.as_array());
    bytes
}

fn require_digest(value: Digest32, name: &'static str) -> Result<(), NduConvergenceError> {
    if value.is_zero() {
        Err(NduConvergenceError::EmptyDigest(name))
    } else {
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
fn digest_certificate(
    evidence: &NduConvergenceEvidenceV1,
    decision: NduConvergenceDecisionV1,
    producer: &StableId,
    evaluator: &StableId,
    trust_digest: Digest32,
    producer_payload_digest: Digest32,
    evaluator_payload_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-convergence-certificate.v2\0".to_vec();
    bytes.extend_from_slice(&evaluator_payload(evidence));
    push_id(&mut bytes, producer);
    push_id(&mut bytes, evaluator);
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(producer_payload_digest.as_array());
    bytes.extend_from_slice(evaluator_payload_digest.as_array());
    bytes.push(decision.tag());
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
