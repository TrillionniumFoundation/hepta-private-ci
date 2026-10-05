//! A distinct durable preparation fact. Preparation is not publication,
//! consumer acceptance, native start, or outcome evidence. The legacy tag-9
//! assignment codec retains its original exposure meaning; this event uses 10.

use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::LedgerError;
use crate::LedgerEvent;
use crate::RetrievalAssignmentBridgeError;
use crate::RetrievalAssignmentFact;
use crate::retrieval_assignment_event_with_delivery_policy;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalPreparationFactV1 {
    /// Assignment evidence only: exposure fields must be false, empty and None.
    pub assignment: RetrievalAssignmentFact,
    /// Candidate identities in prepared response order. Offset is the position;
    /// normalization remaps indices but never sorts this sequence.
    pub prepared_candidate_indices: Vec<u32>,
    pub prepared_context_digest: Option<Digest32>,
}

impl RetrievalPreparationFactV1 {
    /// Validate the same bounded shape, provenance digests and index relations
    /// as the owner ledger without appending a fact or granting authority.
    pub fn validate(&self) -> Result<(), LedgerError> {
        self.validate_unexposed()?;
        crate::LearningLedger::new()
            .prepare(LedgerEvent::RetrievalPrepared(self.clone()))
            .map(|_| ())
    }

    pub(crate) fn from_wire_assignment(mut assignment: RetrievalAssignmentFact) -> Self {
        let prepared_candidate_indices =
            std::mem::take(&mut assignment.delivered_candidate_indices);
        let prepared_context_digest = assignment.published_context_digest.take();
        assignment.context_exposed = false;
        Self {
            assignment,
            prepared_candidate_indices,
            prepared_context_digest,
        }
    }

    pub(crate) fn validate_unexposed(&self) -> Result<(), LedgerError> {
        // Check all attacker-sized vectors before cloning into the canonical
        // assignment shape used by the existing bounded normalization code.
        if self.assignment.enumerated_candidate_digests.len() > 512
            || self.assignment.legal_candidate_indices.len() > 512
            || self.assignment.selected_candidate_indices.len() > 16
            || self.prepared_candidate_indices.len() > 16
        {
            return Err(LedgerError::RetrievalCandidateLimitExceeded);
        }
        if self.assignment.context_exposed
            || !self.assignment.delivered_candidate_indices.is_empty()
            || self.assignment.published_context_digest.is_some()
        {
            return Err(LedgerError::RetrievalExposureStateMismatch);
        }
        Ok(())
    }

    /// Private encoding/normalization shape only. It must never be appended as
    /// a legacy RetrievalAssignment. The event discriminator stays 10.
    pub(crate) fn wire_assignment(&self) -> RetrievalAssignmentFact {
        let mut assignment = self.assignment.clone();
        assignment.delivered_candidate_indices = self.prepared_candidate_indices.clone();
        assignment.context_exposed = !self.prepared_candidate_indices.is_empty();
        assignment.published_context_digest = self.prepared_context_digest;
        assignment
    }
}

#[allow(clippy::too_many_arguments)]
pub fn retrieval_preparation_event_v1(
    record_id: StableId,
    episode_id: StableId,
    observation: &RetrievalAssignmentObservationV1,
    prepared_candidates: &[RetrievalCandidateIdentityV1],
    prepared_context_digest: Option<Digest32>,
    downstream_policy_digest: Option<Digest32>,
    delivery_propensity: ProbabilityQ32,
) -> Result<LedgerEvent, RetrievalAssignmentBridgeError> {
    let shape = retrieval_assignment_event_with_delivery_policy(
        record_id,
        episode_id,
        observation,
        prepared_candidates,
        !prepared_candidates.is_empty(),
        prepared_context_digest,
        downstream_policy_digest,
        delivery_propensity,
    )?;
    let LedgerEvent::RetrievalAssignment(assignment) = shape else {
        return Err(RetrievalAssignmentBridgeError::InvalidObservation(
            "assignment bridge returned an unexpected event kind".to_string(),
        ));
    };
    Ok(LedgerEvent::RetrievalPrepared(
        RetrievalPreparationFactV1::from_wire_assignment(assignment),
    ))
}

#[cfg(test)]
#[path = "retrieval_preparation_tests.rs"]
mod tests;
