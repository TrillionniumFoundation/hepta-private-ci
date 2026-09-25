//! Current authenticated intuition admission.
//!
//! V1/V2 receipts remain available for historical replay. V3 authenticates the
//! scorer-owned V2 commitment while the complete request and assignment remain
//! independently bound by the runtime observer evidence.

use codex_hepta_intuition::AssignmentCommitmentV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scoring_commitment_digest_v2;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_learning_ledger::verify_verified_role_separation;
use codex_hepta_types::Digest32;

use crate::intuition_qualification::IntuitionQualificationError;
use crate::intuition_qualification::IntuitionQualificationEvidenceV2;

const MAX_CANDIDATES: usize = 128;

/// Current authenticated decision receipt using the scorer/assignment split.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedIntuitionDecisionV3 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub profile_digest: Digest32,
    pub scoring_commitment_digest: Digest32,
    pub trust_digest: Digest32,
    pub completeness_payload_digest: Digest32,
    pub profile_qualification_payload_digest: Digest32,
    pub runtime_payload_digest: Digest32,
    pub authentication_digest: Digest32,
}

/// Authenticate one current intuition decision.
///
/// The host-owned verifier supplies the exact objective, scope, authority epoch,
/// signer registry and revocation state. Generator, evaluator and runtime
/// observer are independently verified before the pure V3 policy kernel runs.
pub fn decide_authenticated_intuition_v3(
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scoring: ScoringCommitmentV2,
    assignment: AssignmentCommitmentV1,
    evidence: IntuitionQualificationEvidenceV2<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedIntuitionDecisionV3, IntuitionQualificationError> {
    if request.objective_digest != verifier.objective_digest() {
        return Err(SignedEvidenceError::ContextMismatch.into());
    }
    if !(1..=MAX_CANDIDATES).contains(&request.candidates.len()) {
        return Err(
            QualifiedCalibratedError::Policy(CalibratedError::CandidateCountOutOfRange).into(),
        );
    }

    let completeness_payload = canonical_completeness_evidence_payload_v1(&request)?;
    let profile_qualification_payload = canonical_profile_qualification_payload_v1(&profile)?;
    let runtime_payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)?;

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
    verify_verified_role_separation(&evaluator, &observer, now)?;

    let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
    let scoring_commitment_digest = canonical_scoring_commitment_digest_v2(&scoring)?;
    let decision = decide_calibrated_v3(request, &profile)?;
    let completeness_payload_digest = Digest32::of_bytes(&completeness_payload);
    let profile_qualification_payload_digest = Digest32::of_bytes(&profile_qualification_payload);
    let runtime_payload_digest = Digest32::of_bytes(&runtime_payload);

    let mut bytes = b"hepta.intelligence.authenticated-intuition.v3\0".to_vec();
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

    Ok(AuthenticatedIntuitionDecisionV3 {
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
