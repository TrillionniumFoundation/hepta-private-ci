use std::error::Error;
use std::fmt;

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
    pub manifest_digest: Digest32,
    pub operating_domain_digest: Digest32,
    pub square_integrability: NduAssumptionEvidenceV1,
    pub conditional_mean: NduConditionalMeanEvidenceV1,
    pub coefficient_bounds: NduAssumptionEvidenceV1,
    pub lipschitz: NduAssumptionEvidenceV1,
    pub generator_monotonicity: NduAssumptionEvidenceV1,
    pub terminal_lipschitz: NduAssumptionEvidenceV1,
    pub continuity_scope: NduContinuityScopeV1,
    pub solver_stability: NduAssumptionEvidenceV1,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduWellPosednessCertificateV1 {
    certificate_id: StableId,
    manifest_digest: Digest32,
    operating_domain_digest: Digest32,
    square_integrability: NduAssumptionEvidenceV1,
    conditional_mean: NduConditionalMeanEvidenceV1,
    coefficient_bounds: NduAssumptionEvidenceV1,
    lipschitz: NduAssumptionEvidenceV1,
    generator_monotonicity: NduAssumptionEvidenceV1,
    terminal_lipschitz: NduAssumptionEvidenceV1,
    continuity_scope: NduContinuityScopeV1,
    solver_stability: NduAssumptionEvidenceV1,
    evaluator_identity: StableId,
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
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn operating_domain_digest(&self) -> Digest32 {
        self.operating_domain_digest
    }

    #[must_use]
    pub fn square_integrability(&self) -> &NduAssumptionEvidenceV1 {
        &self.square_integrability
    }

    #[must_use]
    pub fn conditional_mean(&self) -> &NduConditionalMeanEvidenceV1 {
        &self.conditional_mean
    }

    #[must_use]
    pub fn coefficient_bounds(&self) -> &NduAssumptionEvidenceV1 {
        &self.coefficient_bounds
    }

    #[must_use]
    pub fn lipschitz(&self) -> &NduAssumptionEvidenceV1 {
        &self.lipschitz
    }

    #[must_use]
    pub fn generator_monotonicity(&self) -> &NduAssumptionEvidenceV1 {
        &self.generator_monotonicity
    }

    #[must_use]
    pub fn terminal_lipschitz(&self) -> &NduAssumptionEvidenceV1 {
        &self.terminal_lipschitz
    }

    #[must_use]
    pub const fn continuity_scope(&self) -> NduContinuityScopeV1 {
        self.continuity_scope
    }

    #[must_use]
    pub fn solver_stability(&self) -> &NduAssumptionEvidenceV1 {
        &self.solver_stability
    }

    #[must_use]
    pub fn evaluator_identity(&self) -> &StableId {
        &self.evaluator_identity
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduWellPosednessError {
    EmptyDigest(&'static str),
    SelfEvaluation,
    InvalidConditionalMean,
    Expired,
    InvalidExpiry,
    Arithmetic,
}

impl fmt::Display for NduWellPosednessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduWellPosednessError {}

/// Independently evaluates the registered well-posedness/identification evidence
/// required by the NDU FBSDE candidate. It does not fit coefficients, select an
/// artifact, or issue activation authority.
pub fn decide_ndu_well_posedness_v1(
    evidence: NduWellPosednessEvidenceV1,
    now_unix_ms: u64,
) -> Result<NduWellPosednessCertificateV1, NduWellPosednessError> {
    require_digest(evidence.manifest_digest, "manifest")?;
    require_digest(evidence.operating_domain_digest, "operating_domain")?;
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduWellPosednessError::SelfEvaluation);
    }
    if evidence.expires_unix_ms == 0 {
        return Err(NduWellPosednessError::InvalidExpiry);
    }
    if now_unix_ms >= evidence.expires_unix_ms {
        return Err(NduWellPosednessError::Expired);
    }
    if evidence.conditional_mean.standardized_absolute_mean_q32 < 0 {
        return Err(NduWellPosednessError::InvalidConditionalMean);
    }

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
    let certificate_digest = digest_certificate(&evidence, decision);
    Ok(NduWellPosednessCertificateV1 {
        certificate_id: evidence.certificate_id,
        manifest_digest: evidence.manifest_digest,
        operating_domain_digest: evidence.operating_domain_digest,
        square_integrability: evidence.square_integrability,
        conditional_mean: evidence.conditional_mean,
        coefficient_bounds: evidence.coefficient_bounds,
        lipschitz: evidence.lipschitz,
        generator_monotonicity: evidence.generator_monotonicity,
        terminal_lipschitz: evidence.terminal_lipschitz,
        continuity_scope: evidence.continuity_scope,
        solver_stability: evidence.solver_stability,
        evaluator_identity: evidence.evaluator_identity,
        decision,
        expires_unix_ms: evidence.expires_unix_ms,
        certificate_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), NduWellPosednessError> {
    if value.is_zero() {
        Err(NduWellPosednessError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

fn digest_certificate(
    evidence: &NduWellPosednessEvidenceV1,
    decision: NduWellPosednessDecisionV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-well-posedness-certificate.v1".to_vec();
    push_id(&mut bytes, &evidence.certificate_id);
    bytes.extend_from_slice(evidence.manifest_digest.as_array());
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
    push_id(&mut bytes, &evidence.evaluator_identity);
    push_id(&mut bytes, &evidence.candidate_producer_identity);
    bytes.push(decision.tag());
    bytes.extend_from_slice(&evidence.expires_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
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
