//! Fresh independent evaluator admission over an exact V2 selection.

use super::*;
use codex_hepta_types::Generation;

#[derive(Clone, Debug)]
pub struct VerifiedSelfEvolutionRollbackV2 {
    selection: VerifiedSelfEvolutionSelectionV2,
    evaluator: VerifiedLearningEvidenceV1,
    regression_evidence_digest: Digest32,
    rollback_generation: Generation,
}

impl VerifiedSelfEvolutionRollbackV2 {
    pub fn selection(&self) -> &VerifiedSelfEvolutionSelectionV2 {
        &self.selection
    }
    pub const fn regression_evidence_digest(&self) -> Digest32 {
        self.regression_evidence_digest
    }
    pub const fn rollback_generation(&self) -> Generation {
        self.rollback_generation
    }
    pub fn revalidate_current(
        &self,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<(), SelfEvolutionSelectionError> {
        self.selection.revalidate_current(trust)?;
        let now = self.selection.prepared.current(trust)?;
        trust.verifier().revalidate(&self.evaluator, now)?;
        verify_verified_role_separation(&self.evaluator, &self.selection.selector, now)?;
        for participant in &self.selection.prepared.participants {
            if participant.role() != LearningEvidenceRoleV1::Evaluator {
                verify_verified_role_separation(&self.evaluator, participant, now)?;
            }
        }
        Ok(())
    }
}

pub fn rollback_signing_payload_v2(
    selection: &VerifiedSelfEvolutionSelectionV2,
    regression_evidence_digest: Digest32,
    rollback_generation: Generation,
) -> Result<Vec<u8>, SelfEvolutionSelectionError> {
    if regression_evidence_digest.is_zero() {
        return Err(SelfEvolutionSelectionError::EmptyDigest);
    }
    if selection.receipt().request.candidate_generation.next().ok() != Some(rollback_generation) {
        return Err(SelfEvolutionSelectionError::GenerationMismatch);
    }
    let mut bytes = b"hepta.intelligence-eval.self-evolution-rollback.v2\0".to_vec();
    bytes.extend_from_slice(selection.selection_digest().as_array());
    bytes.extend_from_slice(&selection_signing_payload_v2(selection.receipt())?);
    bytes.extend_from_slice(regression_evidence_digest.as_array());
    bytes.extend_from_slice(&rollback_generation.get().to_be_bytes());
    Ok(bytes)
}

pub fn admit_self_evolution_rollback_v2(
    selection: &VerifiedSelfEvolutionSelectionV2,
    regression_evidence_digest: Digest32,
    rollback_generation: Generation,
    evidence: &SignedLearningEvidenceV1,
    trust: &ActivatedLearningTrustV1,
) -> Result<VerifiedSelfEvolutionRollbackV2, SelfEvolutionSelectionError> {
    selection.revalidate_current(trust)?;
    let now = selection.prepared.current(trust)?;
    let payload =
        rollback_signing_payload_v2(selection, regression_evidence_digest, rollback_generation)?;
    let evaluator =
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, evidence, &payload, now)?;
    let token = VerifiedSelfEvolutionRollbackV2 {
        selection: selection.clone(),
        evaluator,
        regression_evidence_digest,
        rollback_generation,
    };
    token.revalidate_current(trust)?;
    Ok(token)
}
