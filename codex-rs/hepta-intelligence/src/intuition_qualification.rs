//! Cryptographic admission for current-generation intuition qualification.
//!
//! `codex-hepta-intuition` intentionally remains a pure policy kernel and cannot
//! depend on the learning ledger without creating an ownership/dependency cycle.
//! This consumer layer owns the trust snapshot, verifies independent signed
//! evidence over exact canonical payload bytes, and only then invokes V3.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::RuntimeCommitmentError;
use codex_hepta_intuition::ScoringCommitmentV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v1;
use codex_hepta_intuition::canonical_scoring_commitment_digest_v1;
use codex_hepta_intuition::canonical_qualification_evidence_payload_v1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;

use crate::EvaluatedShadowError;
use crate::EvaluatedShadowReceiptV1;
use crate::EvaluatedShadowRequestV1;
use crate::LaneFShadowPortsV1;
use crate::run_evaluated_shadow_v1;

pub struct IntuitionQualificationEvidenceV1<'a> {
    /// Generator signature over the exact candidate-set completeness payload.
    pub completeness: &'a SignedLearningEvidenceV1,
    /// Independent evaluator signature over profile + exact calibrated request.
    pub qualification: &'a SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedIntuitionDecisionV1 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub qualification_payload_digest: Digest32,
    pub authentication_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntuitionQualificationError {
    Evidence(SignedEvidenceError),
    Independence(CausalV2Error),
    Policy(QualifiedCalibratedError),
    Runtime(RuntimeCommitmentError),
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

impl From<CausalV2Error> for IntuitionQualificationError {
    fn from(value: CausalV2Error) -> Self {
        Self::Independence(value)
    }
}

impl From<QualifiedCalibratedError> for IntuitionQualificationError {
    fn from(value: QualifiedCalibratedError) -> Self {
        Self::Policy(value)
    }
}

impl From<RuntimeCommitmentError> for IntuitionQualificationError {
    fn from(value: RuntimeCommitmentError) -> Self {
        Self::Runtime(value)
    }
}

/// Verify both roles against the host-owned immutable trust snapshot, including
/// signer revocation, authority epoch, objective/scope, validity windows and the
/// exact canonical payload bytes. Only verified evidence can reach V3.
pub fn decide_authenticated_intuition_v1(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    evidence: IntuitionQualificationEvidenceV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV1, IntuitionQualificationError> {
    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)?;
    let qualification_payload = canonical_qualification_evidence_payload_v1(&request, &profile)?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        evidence.completeness,
        &completeness_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evidence.qualification,
        &qualification_payload,
        now,
    )?;
    verify_signed_role_separation(&generator, &evaluator, now)?;

    let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
    let decision = decide_calibrated_v3(request, &profile)?;
    let completeness_payload_digest = Digest32::of_bytes(&completeness_payload);
    let qualification_payload_digest = Digest32::of_bytes(&qualification_payload);
    let mut bytes = b"hepta.intelligence.authenticated-intuition.v1\0".to_vec();
    for digest in [
        verifier.trust_digest(),
        profile_digest,
        completeness_payload_digest,
        qualification_payload_digest,
        Digest32::of_bytes(&evidence.completeness.signing_bytes()),
        Digest32::of_bytes(&evidence.qualification.signing_bytes()),
        decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&evidence.completeness.signature);
    bytes.extend_from_slice(&evidence.qualification.signature);

    Ok(AuthenticatedIntuitionDecisionV1 {
        decision,
        profile_digest,
        trust_digest: verifier.trust_digest(),
        completeness_payload_digest,
        qualification_payload_digest,
        authentication_digest: Digest32::of_bytes(&bytes),
    })
}


pub struct IntuitionQualificationEvidenceV2<'a> {
    /// Generator attestation over the exact complete candidate set.
    pub completeness: &'a SignedLearningEvidenceV1,
    /// Longer-lived evaluator attestation over the canonical profile/model/data.
    pub profile_qualification: &'a SignedLearningEvidenceV1,
    /// Per-decision observer attestation over exact request, scores and RNG draw.
    pub runtime: &'a SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedIntuitionDecisionV2 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub profile_digest: Digest32,
    pub scoring_commitment_digest: Digest32,
    pub trust_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub profile_qualification_payload_digest: Digest32,
    pub runtime_payload_digest: Digest32,
    pub authentication_digest: Digest32,
}

/// Production-oriented authenticated admission. Heavy model/calibration
/// qualification is signed by an Evaluator over the canonical profile, while
/// every decision is independently bound by Generator completeness evidence and
/// an Observer runtime commitment covering the exact request, score provenance,
/// RNG owner, stream, sequence counter and draw.
pub fn decide_authenticated_intuition_v2(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV1,
    assignment: AssignmentCommitmentV1,
    evidence: IntuitionQualificationEvidenceV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV2, IntuitionQualificationError> {
    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)?;
    let profile_qualification_payload = canonical_profile_qualification_payload_v1(&profile)?;
    let runtime_payload =
        canonical_runtime_commitment_payload_v1(&request, &profile, &scoring, &assignment)?;

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        evidence.completeness,
        &completeness_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        evidence.profile_qualification,
        &profile_qualification_payload,
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        evidence.runtime,
        &runtime_payload,
        now,
    )?;

    verify_signed_role_separation(&generator, &evaluator, now)?;
    verify_signed_role_separation(&generator, &observer, now)?;
    verify_independent_roles(evaluator.principal(), observer.principal(), now)?;

    let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
    let scoring_commitment_digest = canonical_scoring_commitment_digest_v1(&scoring)?;
    let decision = decide_calibrated_v3(request, &profile)?;
    let completeness_payload_digest = Digest32::of_bytes(&completeness_payload);
    let profile_qualification_payload_digest =
        Digest32::of_bytes(&profile_qualification_payload);
    let runtime_payload_digest = Digest32::of_bytes(&runtime_payload);

    let mut bytes = b"hepta.intelligence.authenticated-intuition.v2\0".to_vec();
    for digest in [
        verifier.trust_digest(),
        profile_digest,
        scoring_commitment_digest,
        completeness_payload_digest,
        profile_qualification_payload_digest,
        runtime_payload_digest,
        Digest32::of_bytes(&evidence.completeness.signing_bytes()),
        Digest32::of_bytes(&evidence.profile_qualification.signing_bytes()),
        Digest32::of_bytes(&evidence.runtime.signing_bytes()),
        decision.receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&evidence.completeness.signature);
    bytes.extend_from_slice(&evidence.profile_qualification.signature);
    bytes.extend_from_slice(&evidence.runtime.signature);

    Ok(AuthenticatedIntuitionDecisionV2 {
        decision,
        profile_digest,
        scoring_commitment_digest,
        trust_digest: verifier.trust_digest(),
        completeness_payload_digest,
        profile_qualification_payload_digest,
        runtime_payload_digest,
        authentication_digest: Digest32::of_bytes(&bytes),
    })
}

pub struct QualifiedEvaluatedShadowRequestV2<'a> {
    pub shadow: EvaluatedShadowRequestV1<'a>,
    pub profile: CanonicalPolicyProfileV1,
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

/// Current-generation Lane-F wrapper. Authentication is performed before any
/// host port is called. The legacy shadow coordinator is retained as a bounded
/// execution adapter, but its request digest is rebound to the authenticated
/// qualification receipt so replay/substitution cannot detach the two.
pub fn run_qualified_evaluated_shadow_v2<P: LaneFShadowPortsV1>(
    mut request: QualifiedEvaluatedShadowRequestV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    ledger: &mut dyn DurableLearningJournal,
    ports: &mut P,
    now: u64,
) -> Result<QualifiedEvaluatedShadowReceiptV2, QualifiedEvaluatedShadowError> {
    // The legacy coordinator's V2 decision kernel implements exactly this risk
    // rule. Stricter V3 profiles are supported by the policy API but require a
    // native V3 host port before they can be composed into this compatibility
    // wrapper without semantic drift.
    if request.profile.risk_rule != CanonicalRiskRuleV1::HighOnlySlowPath {
        return Err(QualifiedEvaluatedShadowError::UnsupportedLegacyRiskRule);
    }

    let authenticated = decide_authenticated_intuition_v1(
        request.shadow.intuition.clone(),
        request.profile,
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
