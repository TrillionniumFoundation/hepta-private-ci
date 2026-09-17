//! Explicit trust boundary for production plasticity composition.
//!
//! The legacy V2 API remains an integrity-only constructor. Production callers
//! must first obtain verified evidence and evaluator contexts from host-owned
//! verifiers. This crate never treats a non-zero digest or unequal role label as
//! authentication by itself.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::ParameterProposalRequestV2;
use crate::ParameterProposalV2;
use crate::propose_v2;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum EvidenceKindV1 {
    SelectedArtifact,
    Window,
    Dataset,
    UpdateRule,
    Modulator,
    ModulatorBroadcast,
    Eligibility,
    Evaluation,
    Parameter,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceClaimV1 {
    pub kind: EvidenceKindV1,
    pub subject_digest: Digest32,
    pub producer_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window_digest: Digest32,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluatorClaimV1 {
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub attestation_digest: Digest32,
}

/// Host boundary that authenticates provenance, freshness, scope and revocation.
///
/// Implementations are expected to verify signatures/keys or another registered
/// authority mechanism outside this crate. Returning `Ok(())` is the trust grant.
pub trait EvidenceVerifier {
    fn verify_evidence(&self, claim: &EvidenceClaimV1, now_ms: u64) -> Result<(), Error>;
}

/// Host boundary that proves evaluator identity and independence from proposer.
pub trait IndependentEvaluatorVerifier {
    fn verify_independent_evaluator(
        &self,
        claim: &EvaluatorClaimV1,
        now_ms: u64,
    ) -> Result<(), Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedParameterProposalRequestV1 {
    pub request: ParameterProposalRequestV2,
    pub evidence: Vec<EvidenceClaimV1>,
    pub evaluator: EvaluatorClaimV1,
    pub now_ms: u64,
}

pub fn propose_authenticated_v1(
    authenticated: AuthenticatedParameterProposalRequestV1,
    evidence_verifier: &impl EvidenceVerifier,
    evaluator_verifier: &impl IndependentEvaluatorVerifier,
) -> Result<ParameterProposalV2, Error> {
    validate_evaluator_claim(&authenticated.request, &authenticated.evaluator)?;
    evaluator_verifier.verify_independent_evaluator(&authenticated.evaluator, authenticated.now_ms)?;
    validate_evidence_set(
        &authenticated.request,
        &authenticated.evidence,
        authenticated.now_ms,
        evidence_verifier,
    )?;
    propose_v2(authenticated.request)
}

fn validate_evaluator_claim(
    request: &ParameterProposalRequestV2,
    claim: &EvaluatorClaimV1,
) -> Result<(), Error> {
    if claim.proposer_id != request.proposer_id
        || claim.evaluator_id != request.evaluator_id
        || claim.selected_artifact_digest != request.selected_artifact_digest
        || claim.window_digest != request.window.window_digest
        || claim.evaluation_digest != request.evaluation_digest
    {
        return Err(Error::EvaluatorAttestationMismatch);
    }
    validate_time_window(claim.issued_at_ms, claim.expires_at_ms)?;
    if claim.attestation_digest.is_zero() {
        return Err(Error::EmptyDigest("evaluator attestation"));
    }
    Ok(())
}

fn validate_evidence_set(
    request: &ParameterProposalRequestV2,
    claims: &[EvidenceClaimV1],
    now_ms: u64,
    verifier: &impl EvidenceVerifier,
) -> Result<(), Error> {
    let required = [
        (EvidenceKindV1::SelectedArtifact, request.selected_artifact_digest),
        (EvidenceKindV1::Window, request.window.window_digest),
        (EvidenceKindV1::Dataset, request.dataset_digest),
        (EvidenceKindV1::UpdateRule, request.update_rule_digest),
        (EvidenceKindV1::Modulator, request.modulator_digest),
        (
            EvidenceKindV1::ModulatorBroadcast,
            request.modulator_broadcast_digest,
        ),
        (EvidenceKindV1::Eligibility, request.eligibility_digest),
        (EvidenceKindV1::Evaluation, request.evaluation_digest),
    ];

    for (kind, digest) in required {
        let mut matches = claims
            .iter()
            .filter(|claim| claim.kind == kind && claim.subject_digest == digest);
        let Some(claim) = matches.next() else {
            return Err(Error::MissingAuthenticatedEvidence(format!("{kind:?}")));
        };
        if matches.next().is_some() {
            return Err(Error::DuplicateAuthenticatedEvidence(format!("{kind:?}")));
        }
        validate_claim_scope(request, claim)?;
        validate_time_window(claim.issued_at_ms, claim.expires_at_ms)?;
        if now_ms < claim.issued_at_ms || now_ms > claim.expires_at_ms {
            return Err(Error::StaleAuthenticatedEvidence(format!("{kind:?}")));
        }
        if claim.receipt_digest.is_zero() {
            return Err(Error::EmptyDigest("evidence receipt"));
        }
        verifier.verify_evidence(claim, now_ms)?;
    }

    for candidate in &request.candidates {
        for delta in &candidate.parameter_deltas {
            let mut matches = claims.iter().filter(|claim| {
                claim.kind == EvidenceKindV1::Parameter
                    && claim.subject_digest == delta.evidence_digest
            });
            let Some(claim) = matches.next() else {
                return Err(Error::MissingAuthenticatedEvidence(format!(
                    "parameter:{}",
                    delta.parameter_id
                )));
            };
            if matches.next().is_some() {
                return Err(Error::DuplicateAuthenticatedEvidence(format!(
                    "parameter:{}",
                    delta.parameter_id
                )));
            }
            validate_claim_scope(request, claim)?;
            validate_time_window(claim.issued_at_ms, claim.expires_at_ms)?;
            if now_ms < claim.issued_at_ms || now_ms > claim.expires_at_ms {
                return Err(Error::StaleAuthenticatedEvidence(format!(
                    "parameter:{}",
                    delta.parameter_id
                )));
            }
            if claim.receipt_digest.is_zero() {
                return Err(Error::EmptyDigest("evidence receipt"));
            }
            verifier.verify_evidence(claim, now_ms)?;
        }
    }
    Ok(())
}

fn validate_claim_scope(
    request: &ParameterProposalRequestV2,
    claim: &EvidenceClaimV1,
) -> Result<(), Error> {
    if claim.selected_artifact_digest != request.selected_artifact_digest
        || claim.window_digest != request.window.window_digest
    {
        return Err(Error::AuthenticatedEvidenceScopeMismatch);
    }
    if claim.producer_id.as_str().is_empty() {
        return Err(Error::InvalidAuthenticatedEvidenceProducer);
    }
    Ok(())
}

fn validate_time_window(issued_at_ms: u64, expires_at_ms: u64) -> Result<(), Error> {
    if issued_at_ms == 0 || expires_at_ms < issued_at_ms {
        return Err(Error::InvalidAuthenticatedEvidenceWindow);
    }
    Ok(())
}
