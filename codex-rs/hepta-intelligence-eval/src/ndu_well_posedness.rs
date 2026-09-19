use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const Q32_ONE_RAW: i128 = 1_i128 << 32;

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
    QualifiedOperatingRegion,
    DeclaredOperatingDomain,
}

impl NduContinuityScopeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::QualifiedOperatingRegion => 0,
            Self::DeclaredOperatingDomain => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAssumptionCheckV1 {
    pub support_digest: Digest32,
    pub satisfied: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConditionalMeanCheckV1 {
    pub support_digest: Digest32,
    pub maximum_abs_standardized_q32: i64,
}

/// learning.eval-owned evidence for the canonical well-posedness certificate.
/// Support digests identify independently produced analyses; the evaluator
/// applies deterministic gates and does not infer missing mathematics.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduWellPosednessEvidenceV1 {
    pub certificate_id: StableId,
    pub manifest_digest: Digest32,
    pub operating_domain_digest: Digest32,
    pub square_integrability: NduAssumptionCheckV1,
    pub conditional_mean: NduConditionalMeanCheckV1,
    pub coefficient_bounds: NduAssumptionCheckV1,
    pub lipschitz: NduAssumptionCheckV1,
    pub generator_monotonicity: NduAssumptionCheckV1,
    pub terminal_lipschitz: NduAssumptionCheckV1,
    pub continuity_scope: NduContinuityScopeV1,
    pub solver_stability: NduAssumptionCheckV1,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    pub expires_unix_ms: u64,
}

/// Native representation of the canonical NduWellPosednessCertificateV1.
/// It is independent eligibility evidence and grants no selection/activation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduWellPosednessCertificateV1 {
    certificate_id: StableId,
    manifest_digest: Digest32,
    operating_domain_digest: Digest32,
    square_integrability: NduAssumptionCheckV1,
    conditional_mean: NduConditionalMeanCheckV1,
    coefficient_bounds: NduAssumptionCheckV1,
    lipschitz: NduAssumptionCheckV1,
    generator_monotonicity: NduAssumptionCheckV1,
    terminal_lipschitz: NduAssumptionCheckV1,
    continuity_scope: NduContinuityScopeV1,
    solver_stability: NduAssumptionCheckV1,
    evaluator_identity: StableId,
    decision: NduWellPosednessDecisionV1,
    expires_unix_ms: u64,
}

impl NduWellPosednessCertificateV1 {
    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduWellPosednessError {
    SelfEvaluation,
    MissingDigest(&'static str),
    NegativeConditionalMean,
    Expired,
}

impl fmt::Display for NduWellPosednessError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduWellPosednessError {}

pub fn evaluate_ndu_well_posedness_v1(
    evidence: &NduWellPosednessEvidenceV1,
    now_unix_ms: u64,
) -> Result<NduWellPosednessCertificateV1, NduWellPosednessError> {
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduWellPosednessError::SelfEvaluation);
    }
    require_digest("manifest", evidence.manifest_digest)?;
    require_digest("operating domain", evidence.operating_domain_digest)?;
    if evidence.conditional_mean.maximum_abs_standardized_q32 < 0 {
        return Err(NduWellPosednessError::NegativeConditionalMean);
    }
    if evidence.expires_unix_ms <= now_unix_ms {
        return Err(NduWellPosednessError::Expired);
    }

    let assumption_checks = [
        &evidence.square_integrability,
        &evidence.coefficient_bounds,
        &evidence.lipschitz,
        &evidence.generator_monotonicity,
        &evidence.terminal_lipschitz,
        &evidence.solver_stability,
    ];
    let support_available = assumption_checks
        .iter()
        .all(|check| !check.support_digest.is_zero())
        && !evidence.conditional_mean.support_digest.is_zero();
    let assumptions_satisfied = assumption_checks.iter().all(|check| check.satisfied);
    let conditional_mean_ok =
        conditional_mean_below_002(evidence.conditional_mean.maximum_abs_standardized_q32);

    let decision = if !support_available {
        NduWellPosednessDecisionV1::Unavailable
    } else if !assumptions_satisfied || !conditional_mean_ok {
        NduWellPosednessDecisionV1::Rejected
    } else {
        NduWellPosednessDecisionV1::Accepted
    };

    Ok(NduWellPosednessCertificateV1 {
        certificate_id: evidence.certificate_id.clone(),
        manifest_digest: evidence.manifest_digest,
        operating_domain_digest: evidence.operating_domain_digest,
        square_integrability: evidence.square_integrability.clone(),
        conditional_mean: evidence.conditional_mean.clone(),
        coefficient_bounds: evidence.coefficient_bounds.clone(),
        lipschitz: evidence.lipschitz.clone(),
        generator_monotonicity: evidence.generator_monotonicity.clone(),
        terminal_lipschitz: evidence.terminal_lipschitz.clone(),
        continuity_scope: evidence.continuity_scope,
        solver_stability: evidence.solver_stability.clone(),
        evaluator_identity: evidence.evaluator_identity.clone(),
        decision,
        expires_unix_ms: evidence.expires_unix_ms,
    })
}

pub fn canonical_ndu_well_posedness_certificate_digest_v1(
    certificate: &NduWellPosednessCertificateV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-well-posedness-certificate.v1".to_vec();
    push_id(&mut bytes, &certificate.certificate_id);
    bytes.extend_from_slice(certificate.manifest_digest.as_array());
    bytes.extend_from_slice(certificate.operating_domain_digest.as_array());
    push_assumption(&mut bytes, &certificate.square_integrability);
    push_conditional_mean(&mut bytes, &certificate.conditional_mean);
    push_assumption(&mut bytes, &certificate.coefficient_bounds);
    push_assumption(&mut bytes, &certificate.lipschitz);
    push_assumption(&mut bytes, &certificate.generator_monotonicity);
    push_assumption(&mut bytes, &certificate.terminal_lipschitz);
    bytes.push(certificate.continuity_scope.tag());
    push_assumption(&mut bytes, &certificate.solver_stability);
    push_id(&mut bytes, &certificate.evaluator_identity);
    bytes.push(certificate.decision.tag());
    bytes.extend_from_slice(&certificate.expires_unix_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_assumption(bytes: &mut Vec<u8>, check: &NduAssumptionCheckV1) {
    bytes.extend_from_slice(check.support_digest.as_array());
    bytes.push(u8::from(check.satisfied));
}

fn push_conditional_mean(bytes: &mut Vec<u8>, check: &NduConditionalMeanCheckV1) {
    bytes.extend_from_slice(check.support_digest.as_array());
    bytes.extend_from_slice(&check.maximum_abs_standardized_q32.to_be_bytes());
}

fn conditional_mean_below_002(raw: i64) -> bool {
    i128::from(raw) * 100 < 2 * Q32_ONE_RAW
}

fn require_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), NduWellPosednessError> {
    if digest.is_zero() {
        return Err(NduWellPosednessError::MissingDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_well_posedness_tests.rs"]
mod tests;
