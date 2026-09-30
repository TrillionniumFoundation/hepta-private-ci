//! Exact-use admission for a sealed multi-outcome qualification.
//! A runtime snapshot is not an evaluation dataset snapshot. Their relationship
//! is attested for this actual use by the current evaluation owner; neither is
//! manufactured by hashing a replacement context into a fresh receipt.
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductOutcomeQualificationReceiptV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::AgentdEvaluationBindingV1;
use super::AgentdIntelligenceEvaluationError;

impl AgentdEvaluationBindingV1 {
    /// Bytes for the current evaluator's existing exact-use signing boundary.
    /// Qualification metadata comes from private-sealed native receipt fields.
    pub fn outcome_qualification_use_payload_v1(
        &self,
        receipt: &ProductOutcomeQualificationReceiptV1,
        current_owner: &CurrentOwnerStateV1,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<Vec<u8>, AgentdIntelligenceEvaluationError> {
        let decision = receipt.decision();
        let digests = [
            self.objective_digest,
            self.snapshot_digest,
            self.context_receipt_digest,
            self.candidate_set_digest,
            receipt.dataset_digest(),
            receipt.execution_digest(),
            receipt.publication_digest(),
            decision.decision.evidence_digest,
            decision.trust_digest,
            decision.authentication_digest,
            trust.distribution_digest(),
            current_owner.key_digest,
            current_owner.implementation_digest,
            current_owner.revocation_frontier_digest,
        ];
        if digests.iter().any(|value| value.is_zero())
            || self.objective_digest != receipt.objective_digest()
            || self.selected_candidate_id != decision.decision.candidate_id
            || current_owner.owner_id.as_str() != "learning.eval"
            || current_owner.key_digest != receipt.evaluator().signing_key_digest
            || current_owner.authority_epoch != receipt.evaluator().authority_epoch
            || decision.trust_digest != trust.verifier().trust_digest()
            || receipt.snapshot_ids().is_empty()
            || receipt.snapshot_ids().len() > 16_384
        {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        let mut bytes = b"hepta.agentd.outcome-qualification-use.v1\0".to_vec();
        for id in [
            &self.run_id,
            &self.selected_candidate_id,
            &decision.decision.evaluation_id,
            &decision.decision.baseline_id,
            &current_owner.owner_id,
            &receipt.evaluator().principal_id,
        ] {
            append_id(&mut bytes, id)?;
        }
        for digest in digests {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            current_owner.generation.get(),
            current_owner.key_epoch,
            current_owner.authority_epoch,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&(receipt.snapshot_ids().len() as u64).to_be_bytes());
        for id in receipt.snapshot_ids() {
            append_id(&mut bytes, id)?;
        }
        Ok(bytes)
    }

    /// Verify current signatures and the complete prepared use before returning
    /// a ledger-bound digest. This replaces the old context-rehash-only API.
    #[allow(clippy::too_many_arguments)]
    pub fn consume_outcome_qualification_v1(
        &self,
        receipt: &ProductOutcomeQualificationReceiptV1,
        expected_evaluation_id: &StableId,
        expected_execution_digest: Digest32,
        expected_publication_digest: Digest32,
        current_owner: &CurrentOwnerStateV1,
        use_attestation: &SignedLearningEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> Result<Digest32, AgentdIntelligenceEvaluationError> {
        let decision = receipt.decision();
        if !trust.is_current_at(now)
            || expected_execution_digest.is_zero()
            || expected_publication_digest.is_zero()
            || receipt.execution_digest() != expected_execution_digest
            || receipt.publication_digest() != expected_publication_digest
            || &decision.decision.evaluation_id != expected_evaluation_id
            || use_attestation.objective_digest != self.objective_digest
            || use_attestation.authority_epoch != current_owner.authority_epoch
        {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        let payload = self.outcome_qualification_use_payload_v1(receipt, current_owner, trust)?;
        let verified = trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                use_attestation,
                &payload,
                now,
            )
            .map_err(AgentdIntelligenceEvaluationError::Evidence)?;
        if verified.principal() != receipt.evaluator()
            || verified.principal().signing_key_digest != current_owner.key_digest
        {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        if receipt.authority().grants_any()
            || decision.decision.authority.grants_any()
            || decision.decision.disposition
                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(AgentdIntelligenceEvaluationError::Ineligible);
        }
        let mut bytes = b"hepta.agentd.outcome-qualification-consumption.v2\0".to_vec();
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&use_attestation.signing_bytes()).as_array());
        bytes.extend_from_slice(&use_attestation.signature);
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn append_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), AgentdIntelligenceEvaluationError> {
    let length =
        u64::try_from(id.as_str().len()).map_err(|_| AgentdIntelligenceEvaluationError::Binding)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
    Ok(())
}

#[cfg(test)]
#[path = "intelligence_outcome_evaluation_tests.rs"]
mod tests;
