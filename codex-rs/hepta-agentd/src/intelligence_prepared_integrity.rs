//! Revalidate a retained product result against its private frozen attachment.
//!
//! Public DTO fields remain inspectable for source compatibility. They are not
//! proof of validity after mutation. The private attachment pins the original
//! envelope; rehashing a changed DTO cannot change that attachment.

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_types::Digest32;

use super::super::PreparedAgentdIntelligenceRunV1;

impl PreparedAgentdIntelligenceRunV1 {
    pub(crate) fn validate_integrity(&self) -> Result<(), CanonicalIntelligenceError> {
        let envelope = &self.envelope;
        let decision = &envelope.decision;
        let run = self.run_snapshot();
        let attachment = self.context_attachment();
        let snapshot = self.canonical_snapshot();
        if envelope.authority.grants_any() || decision.authority.grants_any() {
            return Err(CanonicalIntelligenceError::AuthorityWidening);
        }
        if envelope.run_id.as_str() != run.run_id
            || decision.run_id != envelope.run_id
            || envelope.snapshot_digest != snapshot.digest()
            || envelope.objective_digest != snapshot.objective_digest()
            || envelope.objective_digest.to_string() != run.objective_digest
            || envelope.candidate_set_digest != decision.candidate_set_digest
            || envelope.context_receipt_digest.to_string() != attachment.context_digest
            || envelope.envelope_digest.to_string() != attachment.compilation_receipt_digest
        {
            return Err(CanonicalIntelligenceError::SnapshotMismatch);
        }
        let AdvisoryDecisionV1::Selected {
            candidate_id,
            propensity,
        } = &decision.decision
        else {
            return Err(CanonicalIntelligenceError::UnexpectedDecision);
        };
        if propensity.raw() == 0 || !self.candidate_ids().contains(candidate_id) {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "selected canonical decision",
            ));
        }
        let mut bytes = b"hepta.intelligence.advisory-decision.v1\0".to_vec();
        push_id(&mut bytes, envelope.run_id.as_str())?;
        bytes.extend_from_slice(envelope.candidate_set_digest.as_array());
        bytes.extend_from_slice(decision.intuition_receipt_digest.as_array());
        bytes.push(0);
        push_id(&mut bytes, candidate_id.as_str())?;
        bytes.extend_from_slice(&propensity.raw().to_be_bytes());
        if Digest32::of_bytes(&bytes) != decision.decision_digest {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "decision digest",
            ));
        }
        let mut bytes = b"hepta.intelligence.context-boundary.v1\0".to_vec();
        push_id(&mut bytes, envelope.run_id.as_str())?;
        bytes.extend_from_slice(decision.decision_digest.as_array());
        bytes.extend_from_slice(envelope.context_receipt_digest.as_array());
        if Digest32::of_bytes(&bytes) != envelope.context_binding_digest {
            return Err(CanonicalIntelligenceError::PredecessorMismatch);
        }
        let digests = [
            envelope.snapshot_digest,
            envelope.objective_digest,
            envelope.candidate_set_digest,
            envelope.utility_receipt_digest,
            envelope.neural_receipt_digest,
            envelope.prompt_receipt_digest,
            decision.decision_digest,
            envelope.context_receipt_digest,
            envelope.context_binding_digest,
            envelope.evaluation_receipt_digest,
            envelope.trace_digest,
        ];
        if decision.intuition_receipt_digest.is_zero()
            || digests.iter().any(|value| value.is_zero())
        {
            return Err(CanonicalIntelligenceError::EmptyDigest(
                "prepared dependency",
            ));
        }
        let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
        push_id(&mut bytes, envelope.run_id.as_str())?;
        for digest in digests {
            bytes.extend_from_slice(digest.as_array());
        }
        if Digest32::of_bytes(&bytes) != envelope.envelope_digest {
            return Err(CanonicalIntelligenceError::InvalidCandidateSet(
                "envelope digest",
            ));
        }
        let request_digest: Digest32 = run
            .request_digest
            .parse()
            .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("request digest"))?;
        let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
        bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
        bytes.extend_from_slice(request_digest.as_array());
        if Digest32::of_bytes(&bytes) != self.dispatch_proposal_digest {
            return Err(CanonicalIntelligenceError::InvalidSnapshot(
                "dispatch proposal digest",
            ));
        }
        if let Some(delivery) = self.prompt_delivery() {
            let binding = super::super::prompt_binding::validate_prompt_delivery_v1(delivery)?;
            if envelope.prompt_receipt_digest != binding.prompt_stage_digest
                || envelope.context_receipt_digest != binding.context_attachment_digest
            {
                return Err(CanonicalIntelligenceError::InvalidSnapshot(
                    "prompt delivery binding",
                ));
            }
        }
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &str) -> Result<(), CanonicalIntelligenceError> {
    let length = u32::try_from(value.len()).map_err(|_| CanonicalIntelligenceError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}
