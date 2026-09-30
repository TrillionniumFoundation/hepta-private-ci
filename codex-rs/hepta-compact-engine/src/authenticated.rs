//! Authenticated compaction observations over the authority-free structural proof.
//!
//! The host provisions trust independently of submitted evidence. Signatures
//! authenticate declarations, not their scientific truth, source completeness,
//! checkpoint publication, selection or permission to mutate any owner store.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompactionQualificationV2;
use crate::QualifiedCompactionCandidateV2;
use crate::QualifiedCompactionError;
use crate::prove_compaction;

/// Externally signed declarations from separate generator and evaluator actors.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCompactionEvidenceV1 {
    pub generator: SignedLearningEvidenceV1,
    pub evaluator: SignedLearningEvidenceV1,
}

/// Host-supplied source/authority context, independently obtained from its owners.
/// These fields are declarations; this type does not attest an owner read cut.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionSourceAuthorityBindingV1 {
    pub source_cut_digest: Digest32,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
}

/// Sealed observation admission. This value is never a publication/writer grant.
/// Revalidate against current host trust and source observations at every use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedCompactionProofV1 {
    proof: CompactionProofV1,
    candidate_digest: Digest32,
    source_snapshot: CognitiveSnapshotKeyV1,
    source_binding: CompactionSourceAuthorityBindingV1,
    policy_digest: Digest32,
    selection_input_digest: Digest32,
    qualification: CompactionQualificationV2,
    qualification_digest: Digest32,
    signed_evidence: SignedCompactionEvidenceV1,
    generator_receipt: VerifiedLearningEvidenceV1,
    evaluator_receipt: VerifiedLearningEvidenceV1,
    authentication_digest: Digest32,
}

impl AuthenticatedCompactionProofV1 {
    pub fn proof(&self) -> &CompactionProofV1 {
        &self.proof
    }

    pub fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    pub fn source_snapshot(&self) -> &CognitiveSnapshotKeyV1 {
        &self.source_snapshot
    }

    pub fn source_cut_digest(&self) -> Digest32 {
        self.source_binding.source_cut_digest
    }

    pub fn source_binding(&self) -> &CompactionSourceAuthorityBindingV1 {
        &self.source_binding
    }

    pub fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    pub fn selection_input_digest(&self) -> Digest32 {
        self.selection_input_digest
    }

    pub fn evaluator_id(&self) -> &StableId {
        &self.qualification.evaluator_id
    }

    pub fn qualification(&self) -> &CompactionQualificationV2 {
        &self.qualification
    }

    pub fn qualification_digest(&self) -> Digest32 {
        self.qualification_digest
    }

    pub fn signed_evidence(&self) -> &SignedCompactionEvidenceV1 {
        &self.signed_evidence
    }

    pub fn generator_receipt(&self) -> &VerifiedLearningEvidenceV1 {
        &self.generator_receipt
    }

    pub fn evaluator_receipt(&self) -> &VerifiedLearningEvidenceV1 {
        &self.evaluator_receipt
    }

    pub fn trust_digest(&self) -> Digest32 {
        self.evaluator_receipt.trust_digest()
    }

    pub fn authentication_digest(&self) -> Digest32 {
        self.authentication_digest
    }

    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }

    /// Reverify original signatures under the host's current trust snapshot.
    /// Source-cut identity is checked here; the source owner establishes freshness.
    pub fn revalidate_for(
        &self,
        candidate: &QualifiedCompactionCandidateV2,
        source_cut_digest: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<(), AuthenticatedCompactionError> {
        if candidate.candidate_digest != self.candidate_digest {
            return Err(AuthenticatedCompactionError::CandidateBinding);
        }
        if source_cut_digest != self.source_binding.source_cut_digest {
            return Err(AuthenticatedCompactionError::SourceCutBinding);
        }
        let current = prove_compaction_with_signed_evidence_v1(
            candidate,
            self.source_binding.clone(),
            self.qualification.clone(),
            &self.signed_evidence,
            verifier,
            now,
        )?;
        if *self != current {
            return Err(AuthenticatedCompactionError::ReceiptBinding);
        }
        Ok(())
    }
}

/// Canonical declaration payload for an external signer; no signing occurs here.
pub fn compaction_qualification_payload_v1(
    candidate: &QualifiedCompactionCandidateV2,
    source_binding: &CompactionSourceAuthorityBindingV1,
    qualification: &CompactionQualificationV2,
) -> Result<Vec<u8>, AuthenticatedCompactionError> {
    let proof = prove_compaction(candidate, qualification.clone())?;
    qualification_payload(candidate, source_binding, qualification, &proof)
}

fn qualification_payload(
    candidate: &QualifiedCompactionCandidateV2,
    source_binding: &CompactionSourceAuthorityBindingV1,
    qualification: &CompactionQualificationV2,
    proof: &CompactionProofV1,
) -> Result<Vec<u8>, AuthenticatedCompactionError> {
    if source_binding.source_cut_digest.is_zero() {
        return Err(AuthenticatedCompactionError::EmptySourceCut);
    }
    if source_binding.scope_digest.is_zero() || source_binding.objective_digest.is_zero() {
        return Err(AuthenticatedCompactionError::EmptySourceAuthority);
    }
    let mut bytes = b"hepta.compaction.signed-qualification.v1".to_vec();
    for digest in [
        candidate.candidate_digest,
        candidate.source_snapshot.vector_digest,
        source_binding.source_cut_digest,
        source_binding.scope_digest,
        source_binding.objective_digest,
        candidate.policy_digest,
        candidate.selection_input_digest,
        proof.proof_digest,
        qualification_digest(qualification),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&source_binding.authority_epoch.to_be_bytes());
    Ok(bytes)
}

/// Admits signed observations using host-provisioned trust, never evidence-owned keys.
/// Requires exact candidate/source/policy binding and independent protocol actors.
pub fn prove_compaction_with_signed_evidence_v1(
    candidate: &QualifiedCompactionCandidateV2,
    source_binding: CompactionSourceAuthorityBindingV1,
    qualification: CompactionQualificationV2,
    evidence: &SignedCompactionEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<AuthenticatedCompactionProofV1, AuthenticatedCompactionError> {
    let proof = prove_compaction(candidate, qualification.clone())?;
    let payload = qualification_payload(candidate, &source_binding, &qualification, &proof)?;
    if verifier.scope_digest() != source_binding.scope_digest {
        return Err(AuthenticatedCompactionError::TrustScopeBinding);
    }
    if verifier.objective_digest() != source_binding.objective_digest {
        return Err(AuthenticatedCompactionError::TrustObjectiveBinding);
    }
    if verifier.authority_epoch() != source_binding.authority_epoch
        || source_binding.authority_epoch != candidate.source_snapshot.vector.authority_epoch
    {
        return Err(AuthenticatedCompactionError::TrustEpochBinding);
    }
    let generator_receipt = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator,
        &payload,
        now,
    )?;
    let evaluator_receipt = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence.evaluator,
        &payload,
        now,
    )?;
    if evaluator_receipt.principal().principal_id != qualification.evaluator_id {
        return Err(AuthenticatedCompactionError::EvaluatorIdentityBinding);
    }
    verify_signed_role_separation(&generator_receipt, &evaluator_receipt, now)?;
    let mut bytes = b"hepta.compaction.authenticated-proof.v1".to_vec();
    bytes.extend_from_slice(verifier.trust_digest().as_array());
    bytes.extend_from_slice(&payload);
    for signed in [&evidence.generator, &evidence.evaluator] {
        bytes.extend_from_slice(Digest32::of_bytes(&signed.signing_bytes()).as_array());
        bytes.extend_from_slice(&signed.signature);
    }
    Ok(AuthenticatedCompactionProofV1 {
        proof,
        candidate_digest: candidate.candidate_digest,
        source_snapshot: candidate.source_snapshot.clone(),
        source_binding,
        policy_digest: candidate.policy_digest,
        selection_input_digest: candidate.selection_input_digest,
        qualification_digest: qualification_digest(&qualification),
        qualification,
        signed_evidence: evidence.clone(),
        generator_receipt,
        evaluator_receipt,
        authentication_digest: Digest32::of_bytes(&bytes),
    })
}

fn qualification_digest(qualification: &CompactionQualificationV2) -> Digest32 {
    let mut bytes = b"hepta.compaction.qualification-observation.v1".to_vec();
    push_id(&mut bytes, &qualification.evaluator_id);
    for digest in [
        qualification.candidate_digest,
        qualification.retained_query_suite_digest,
        qualification.reconstruction_obligation_digest,
        qualification.contradiction_holdout_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for passed in [
        qualification.retained_queries_passed,
        qualification.reconstruction_passed,
        qualification.contradictions_preserved,
        qualification.deletion_non_resurrection_passed,
    ] {
        bytes.push(u8::from(passed));
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedCompactionError {
    Compaction(QualifiedCompactionError),
    Evidence(SignedEvidenceError),
    EmptySourceCut,
    EmptySourceAuthority,
    CandidateBinding,
    SourceCutBinding,
    TrustScopeBinding,
    TrustObjectiveBinding,
    TrustEpochBinding,
    EvaluatorIdentityBinding,
    ReceiptBinding,
}

impl fmt::Display for AuthenticatedCompactionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AuthenticatedCompactionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Compaction(error) => Some(error),
            Self::Evidence(error) => Some(error),
            Self::EmptySourceCut
            | Self::EmptySourceAuthority
            | Self::CandidateBinding
            | Self::SourceCutBinding
            | Self::TrustScopeBinding
            | Self::TrustObjectiveBinding
            | Self::TrustEpochBinding
            | Self::EvaluatorIdentityBinding
            | Self::ReceiptBinding => None,
        }
    }
}

impl From<QualifiedCompactionError> for AuthenticatedCompactionError {
    fn from(error: QualifiedCompactionError) -> Self {
        Self::Compaction(error)
    }
}

impl From<SignedEvidenceError> for AuthenticatedCompactionError {
    fn from(error: SignedEvidenceError) -> Self {
        Self::Evidence(error)
    }
}

#[cfg(test)]
#[path = "authenticated_tests.rs"]
pub(crate) mod tests;
