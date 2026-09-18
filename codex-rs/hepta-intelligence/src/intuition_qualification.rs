//! Cryptographic admission for current-generation intuition qualification.
//!
//! `codex-hepta-intuition` intentionally remains a pure policy kernel and cannot
//! depend on the learning ledger without creating an ownership/dependency cycle.
//! This consumer layer owns the trust snapshot and verifies four distinct facts:
//! legal-set completeness, scorer output provenance, long-lived profile
//! qualification, and (when randomized) the exact random-source draw.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::canonical_calibrated_request_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_evidence_payload_v1;
use codex_hepta_intuition::canonical_random_assignment_evidence_payload_v1;
use codex_hepta_intuition::canonical_scoring_evidence_payload_v1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_evidence_independence;
use codex_hepta_types::Digest32;

use crate::EvaluatedShadowError;
use crate::EvaluatedShadowReceiptV1;
use crate::EvaluatedShadowRequestV1;
use crate::LaneFShadowPortsV1;
use crate::run_evaluated_shadow_v1;

pub struct IntuitionQualificationEvidenceV1<'a> {
    /// Generator signature over candidate identity + completeness facts.
    pub completeness: &'a SignedLearningEvidenceV1,
    /// Scorer signature over model/feature snapshot + exact scored outputs.
    pub scoring: &'a SignedLearningEvidenceV1,
    /// Evaluator signature over the long-lived canonical policy profile.
    pub profile_qualification: &'a SignedLearningEvidenceV1,
    /// Random-source signature over exact stream/sequence/draw/distribution.
    /// Required for CounterBased assignment and forbidden for deterministic mode.
    pub assignment: Option<&'a SignedLearningEvidenceV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedIntuitionDecisionV1 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub exact_request_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub scoring_payload_digest: Digest32,
    pub profile_qualification_payload_digest: Digest32,
    pub assignment_payload_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntuitionQualificationError {
    Evidence(SignedEvidenceError),
    Policy(QualifiedCalibratedError),
    MissingRandomSourceEvidence,
    UnexpectedRandomSourceEvidence,
}

impl fmt::Display for IntuitionQualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for IntuitionQualificationError {}

impl From<SignedEvidenceError> for IntuitionQualificationError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}

impl From<QualifiedCalibratedError> for IntuitionQualificationError {
    fn from(value: QualifiedCalibratedError) -> Self {
        Self::Policy(value)
    }
}

fn verify_independence_set(
    evidence: &[&VerifiedLearningEvidenceV1],
    now: u64,
) -> Result<(), SignedEvidenceError> {
    for left in 0..evidence.len() {
        for right in (left + 1)..evidence.len() {
            verify_signed_evidence_independence(evidence[left], evidence[right], now)?;
        }
    }
    Ok(())
}

/// Verify current-generation policy admission against the host-owned immutable
/// trust snapshot. The evaluator qualifies the reusable profile. Per-decision
/// generator/scorer/random-source commitments then cover the exact request
/// without requiring the evaluator to sign every decision.
pub fn decide_authenticated_intuition_v1(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    evidence: IntuitionQualificationEvidenceV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV1, IntuitionQualificationError> {
    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)?;
    let scoring_payload = canonical_scoring_evidence_payload_v1(&scoring)?;
    let profile_qualification_payload =
        canonical_profile_qualification_evidence_payload_v1(&profile)?;
    let assignment_payload = canonical_random_assignment_evidence_payload_v1(&request)?;

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        evidence.completeness,
        &completeness_payload,
        now,
    )?;
    let scorer = verifier.verify(
        LearningEvidenceRoleV1::Scorer,
        evidence.scoring,
        &scoring_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evidence.profile_qualification,
        &profile_qualification_payload,
        now,
    )?;

    let random_source = match (
        &request.assignment,
        assignment_payload.as_deref(),
        evidence.assignment,
    ) {
        (AssignmentModeV1::Deterministic, None, None) => None,
        (AssignmentModeV1::Deterministic, None, Some(_)) => {
            return Err(IntuitionQualificationError::UnexpectedRandomSourceEvidence);
        }
        (AssignmentModeV1::CounterBased { .. }, Some(payload), Some(signed)) => Some(
            verifier.verify(LearningEvidenceRoleV1::RandomSource, signed, payload, now)?,
        ),
        (AssignmentModeV1::CounterBased { .. }, Some(_), None) => {
            return Err(IntuitionQualificationError::MissingRandomSourceEvidence);
        }
        _ => return Err(IntuitionQualificationError::MissingRandomSourceEvidence),
    };

    let mut independent = vec![&generator, &scorer, &evaluator];
    if let Some(random_source) = &random_source {
        independent.push(random_source);
    }
    verify_independence_set(&independent, now)?;

    let exact_request_digest = canonical_calibrated_request_digest_v1(&request)
        .map_err(QualifiedCalibratedError::from)?;
    let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
    let decision = decide_calibrated_v3(request, &profile, &scoring)?;

    let completeness_payload_digest = Digest32::of_bytes(&completeness_payload);
    let scoring_payload_digest = Digest32::of_bytes(&scoring_payload);
    let profile_qualification_payload_digest = Digest32::of_bytes(&profile_qualification_payload);
    let assignment_payload_digest = assignment_payload
        .as_deref()
        .map(Digest32::of_bytes)
        .unwrap_or(Digest32::ZERO);

    let mut bytes = b"hepta.intelligence.authenticated-intuition.v2\0".to_vec();
    for digest in [
        verifier.trust_digest(),
        exact_request_digest,
        profile_digest,
        completeness_payload_digest,
        scoring_payload_digest,
        profile_qualification_payload_digest,
        assignment_payload_digest,
        Digest32::of_bytes(&evidence.completeness.signing_bytes()),
        Digest32::of_bytes(&evidence.scoring.signing_bytes()),
        Digest32::of_bytes(&evidence.profile_qualification.signing_bytes()),
        decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&evidence.completeness.signature);
    bytes.extend_from_slice(&evidence.scoring.signature);
    bytes.extend_from_slice(&evidence.profile_qualification.signature);
    if let Some(assignment) = evidence.assignment {
        bytes.extend_from_slice(
            Digest32::of_bytes(&assignment.signing_bytes()).as_array(),
        );
        bytes.extend_from_slice(&assignment.signature);
    }

    Ok(AuthenticatedIntuitionDecisionV1 {
        decision,
        profile_digest,
        trust_digest: verifier.trust_digest(),
        exact_request_digest,
        completeness_payload_digest,
        scoring_payload_digest,
        profile_qualification_payload_digest,
        assignment_payload_digest,
        authentication_digest: Digest32::of_bytes(&bytes),
    })
}

pub struct QualifiedEvaluatedShadowRequestV2<'a> {
    pub shadow: EvaluatedShadowRequestV1<'a>,
    pub profile: CanonicalPolicyProfileV1,
    pub scoring: ScoringCommitmentV1,
    pub evidence: IntuitionQualificationEvidenceV1<'a>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedEvaluatedShadowReceiptV2 {
    pub intuition: AuthenticatedIntuitionDecisionV1,
    pub shadow: EvaluatedShadowReceiptV1,
}

#[derive(Debug)]
pub enum QualifiedEvaluatedShadowError {
    Qualification(IntuitionQualificationError),
    LegacyPolicy(CalibratedError),
    Shadow(EvaluatedShadowError),
    UnsupportedLegacyRiskRule,
    DecisionParity,
}

impl fmt::Display for QualifiedEvaluatedShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualifiedEvaluatedShadowError {}

/// Current-generation Lane-F compatibility wrapper. Authentication is performed
/// before any host port is called. Stricter V3 risk rules remain unavailable on
/// the legacy V2 coordinator and therefore fail closed here.
pub fn run_qualified_evaluated_shadow_v2<P: LaneFShadowPortsV1>(
    mut request: QualifiedEvaluatedShadowRequestV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    ledger: &mut dyn DurableLearningJournal,
    ports: &mut P,
    now: u64,
) -> Result<QualifiedEvaluatedShadowReceiptV2, QualifiedEvaluatedShadowError> {
    if request.profile.risk_rule != CanonicalRiskRuleV1::HighOnlySlowPath {
        return Err(QualifiedEvaluatedShadowError::UnsupportedLegacyRiskRule);
    }

    let authenticated = decide_authenticated_intuition_v1(
        request.shadow.intuition.clone(),
        request.profile,
        request.scoring,
        request.evidence,
        verifier,
        now,
    )
    .map_err(QualifiedEvaluatedShadowError::Qualification)?;

    let mut legacy = decide_calibrated_v2(request.shadow.intuition.clone())
        .map_err(QualifiedEvaluatedShadowError::LegacyPolicy)?;
    let qualified_for_parity = authenticated.decision.clone();
    legacy.receipt_digest = qualified_for_parity.receipt_digest;
    if legacy != qualified_for_parity {
        return Err(QualifiedEvaluatedShadowError::DecisionParity);
    }

    let mut bytes = b"hepta.intelligence.qualified-shadow.v2\0".to_vec();
    for digest in [
        request.shadow.run.request_digest,
        authenticated.profile_digest,
        authenticated.authentication_digest,
        authenticated.decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    request.shadow.run.request_digest = Digest32::of_bytes(&bytes);
    let shadow = run_evaluated_shadow_v1(request.shadow, verifier, ledger, ports, now)
        .map_err(QualifiedEvaluatedShadowError::Shadow)?;
    Ok(QualifiedEvaluatedShadowReceiptV2 {
        intuition: authenticated,
        shadow,
    })
}
