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

const CONDITIONAL_MEAN_LIMIT_Q32_RAW: i64 = (2_i64 * (1_i64 << 32)) / 100;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduWellPosednessDecisionV1 {
    Accepted,
    Rejected,
    Unavailable,
}

impl NduWellPosednessDecisionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Accepted => 0,
            Self::Rejected => 1,
            Self::Unavailable => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduContinuityScopeV1 {
    DeclaredOperatingDomain,
}

impl NduContinuityScopeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::DeclaredOperatingDomain => 0,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAssumptionEvidenceV1 {
    pub evidence_digest: Digest32,
    pub satisfied: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConditionalMeanEvidenceV1 {
    pub evidence_digest: Digest32,
    pub standardized_absolute_mean_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduWellPosednessEvidenceV1 {
    pub certificate_id: StableId,
    pub artifact_manifest_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub operating_domain_digest: Digest32,
    pub square_integrability: NduAssumptionEvidenceV1,
    pub conditional_mean: NduConditionalMeanEvidenceV1,
    pub coefficient_bounds: NduAssumptionEvidenceV1,
    pub lipschitz: NduAssumptionEvidenceV1,
    pub generator_monotonicity: NduAssumptionEvidenceV1,
    pub terminal_lipschitz: NduAssumptionEvidenceV1,
    pub continuity_scope: NduContinuityScopeV1,
    pub solver_stability: NduAssumptionEvidenceV1,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduWellPosednessCertificateV1 {
    certificate_id: StableId,
    artifact_manifest_digest: Digest32,
    objective_class_digest: Digest32,
    operating_domain_digest: Digest32,
    evaluator_identity: StableId,
    candidate_producer_identity: StableId,
    trust_digest: Digest32,
    decision: NduWellPosednessDecisionV1,
    expires_unix_ms: u64,
    certificate_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduWellPosednessCertificateV1 {
    #[must_use]
    pub fn certificate_id(&self) -> &StableId {
        &self.certificate_id
    }
    #[must_use]
    pub const fn artifact_manifest_digest(&self) -> Digest32 {
        self.artifact_manifest_digest
    }
    #[must_use]
    pub const fn objective_class_digest(&self) -> Digest32 {
        self.objective_class_digest
    }
    #[must_use]
    pub const fn operating_domain_digest(&self) -> Digest32 {
        self.operating_domain_digest
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
    pub const fn decision(&self) -> NduWellPosednessDecisionV1 {
        self.decision
    }
    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
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
pub enum NduWellPosednessError {
    EmptyDigest(&'static str),
    ObjectiveContextMismatch,
    InvalidConditionalMean,
    Expired,
    InvalidExpiry,
    SignedEvidence(SignedEvidenceError),
}

impl fmt::Display for NduWellPosednessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for NduWellPosednessError {}

impl From<SignedEvidenceError> for NduWellPosednessError {
    fn from(error: SignedEvidenceError) -> Self {
        Self::SignedEvidence(error)
    }
}

/// Independently evaluates well-posedness evidence under signed producer and
/// evaluator roles. The certificate is evidence only and always DENY_ALL.
pub fn decide_ndu_well_posedness_v1(
    evidence: NduWellPosednessEvidenceV1,
    producer: &SignedLearningEvidenceV1,
    evaluator: &SignedLearningEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<NduWellPosednessCertificateV1, NduWellPosednessError> {
    require_digest(evidence.artifact_manifest_digest, "artifact_manifest")?;
    require_digest(evidence.objective_class_digest, "objective_class")?;
    require_digest(evidence.operating_domain_digest, "operating_domain")?;
    if evidence.objective_class_digest != verifier.objective_digest() {
        return Err(NduWellPosednessError::ObjectiveContextMismatch);
    }
    if evidence.expires_unix_ms == 0 {
        return Err(NduWellPosednessError::InvalidExpiry);
    }
    if now >= evidence.expires_unix_ms {
        return Err(NduWellPosednessError::Expired);
    }
    if evidence.conditional_mean.standardized_absolute_mean_q32 < 0 {
        return Err(NduWellPosednessError::InvalidConditionalMean);
    }

    let producer_payload = producer_payload(&evidence);
    let evaluator_payload = evaluator_payload(&evidence);
    let producer_verified =
        verifier.verify(LearningEvidenceRoleV1::Generator, producer, &producer_payload, now)?;
    let evaluator_verified =
        verifier.verify(LearningEvidenceRoleV1::Evaluator, evaluator, &evaluator_payload, now)?;
    verify_signed_role_separation(&producer_verified, &evaluator_verified, now)?;

    let assumptions = [
        &evidence.square_integrability,
        &evidence.coefficient_bounds,
        &evidence.lipschitz,
        &evidence.generator_monotonicity,
        &evidence.terminal_lipschitz,
        &evidence.solver_stability,
    ];
    let support_complete = !evidence.conditional_mean.evidence_digest.is_zero()
        && assumptions
            .iter()
            .all(|assumption| !assumption.evidence_digest.is_zero());
    let assumptions_pass = assumptions.iter().all(|assumption| assumption.satisfied);
    let conditional_mean_pass =
        evidence.conditional_mean.standardized_absolute_mean_q32
            < CONDITIONAL_MEAN_LIMIT_Q32_RAW;
    let decision = if !support_complete {
        NduWellPosednessDecisionV1::Unavailable
    } else if assumptions_pass && conditional_mean_pass {
        NduWellPosednessDecisionV1::Accepted
    } else {
        NduWellPosednessDecisionV1::Rejected
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
    Ok(NduWellPosednessCertificateV1 {
        certificate_id: evidence.certificate_id,
        artifact_manifest_digest: evidence.artifact_manifest_digest,
        objective_class_digest: evidence.objective_class_digest,
        operating_domain_digest: evidence.operating_domain_digest,
        evaluator_identity,
        candidate_producer_identity,
        trust_digest,
        decision,
        expires_unix_ms: evidence.expires_unix_ms,
        certificate_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn producer_payload(evidence: &NduWellPosednessEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-eval.ndu-well-posedness-producer.v1\0".to_vec();
    bytes.extend_from_slice(evidence.artifact_manifest_digest.as_array());
    bytes.extend_from_slice(evidence.objective_class_digest.as_array());
    bytes.extend_from_slice(evidence.operating_domain_digest.as_array());
    bytes
}

fn evaluator_payload(evidence: &NduWellPosednessEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.learning-eval.ndu-well-posedness-evaluator.v1\0".to_vec();
    push_id(&mut bytes, &evidence.certificate_id);
    bytes.extend_from_slice(evidence.artifact_manifest_digest.as_array());
    bytes.extend_from_slice(evidence.objective_class_digest.as_array());
    bytes.extend_from_slice(evidence.operating_domain_digest.as_array());
    push_assumption(&mut bytes, &evidence.square_integrability);
    bytes.extend_from_slice(evidence.conditional_mean.evidence_digest.as_array());
    bytes.extend_from_slice(
        &evidence
            .conditional_mean
            .standardized_absolute_mean_q32
            .to_be_bytes(),
    );
    push_assumption(&mut bytes, &evidence.coefficient_bounds);
    push_assumption(&mut bytes, &evidence.lipschitz);
    push_assumption(&mut bytes, &evidence.generator_monotonicity);
    push_assumption(&mut bytes, &evidence.terminal_lipschitz);
    bytes.push(evidence.continuity_scope.tag());
    push_assumption(&mut bytes, &evidence.solver_stability);
    bytes.extend_from_slice(&evidence.expires_unix_ms.to_be_bytes());
    bytes
}

#[allow(clippy::too_many_arguments)]
fn digest_certificate(
    evidence: &NduWellPosednessEvidenceV1,
    decision: NduWellPosednessDecisionV1,
    producer: &StableId,
    evaluator: &StableId,
    trust_digest: Digest32,
    producer_payload_digest: Digest32,
    evaluator_payload_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-well-posedness-certificate.v2\0".to_vec();
    bytes.extend_from_slice(&evaluator_payload(evidence));
    push_id(&mut bytes, producer);
    push_id(&mut bytes, evaluator);
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(producer_payload_digest.as_array());
    bytes.extend_from_slice(evaluator_payload_digest.as_array());
    bytes.push(decision.tag());
    Digest32::of_bytes(&bytes)
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduWellPosednessError> {
    if value.is_zero() {
        Err(NduWellPosednessError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

fn push_assumption(bytes: &mut Vec<u8>, evidence: &NduAssumptionEvidenceV1) {
    bytes.extend_from_slice(evidence.evidence_digest.as_array());
    bytes.push(u8::from(evidence.satisfied));
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_well_posedness_tests.rs"]
mod tests;
