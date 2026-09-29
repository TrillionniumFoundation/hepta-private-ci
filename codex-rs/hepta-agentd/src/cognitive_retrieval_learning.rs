//! Concrete durable learning-ledger sink for retrieval assignment evidence.
//!
//! This adapter owns one host-authorized DurableLedger handle. Agentd never
//! invents a parallel file format or treats an in-memory callback as durable
//! causal evidence.

use std::sync::Mutex;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::RetrievalAssignmentFact;
use codex_hepta_learning_ledger::retrieval_assignment_event_with_delivery_policy;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub struct CognitiveRetrievalLearningSink {
    writer: Mutex<LedgerWriter>,
}

impl CognitiveRetrievalLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self {
            writer: Mutex::new(writer),
        }
    }

    /// Inspect one preparation while retaining the existing ledger-owner lock.
    ///
    /// The host supplies its authenticated owner/generation and the exact read
    /// RPC identity; a context digest alone cannot select a different episode.
    /// The callback must not re-enter this sink or perform external effects.
    /// It may synchronously correlate an existing native-journal observation.
    /// No callback result is a training grant, a lease, or proof of socket
    /// delivery. Later training admission must reacquire its own current owners.
    pub fn with_prepared_assignment<T>(
        &self,
        owner: &AgentId,
        body_generation: u64,
        read_request_id: u64,
        expected_context_digest: Digest32,
        inspect: impl FnOnce(&RetrievalAssignmentFact, &LedgerRecord) -> Result<T, String>,
    ) -> Result<T, String> {
        if body_generation == 0 || expected_context_digest.is_zero() {
            return Err("invalid cognitive preparation identity".to_string());
        }
        let (record_id, episode_id) = assignment_identity(owner, body_generation, read_request_id)?;
        let writer = self
            .writer
            .lock()
            .map_err(|_| "retrieval learning ledger writer lock poisoned".to_string())?;
        let record = writer
            .read_current_retrieval_assignment(&record_id, &episode_id)
            .map_err(|error| error.to_string())?;
        let LedgerEvent::RetrievalAssignment(assignment) = &record.event else {
            return Err("retrieval preparation has wrong event kind".to_string());
        };
        if !assignment.context_exposed
            || assignment.delivered_candidate_indices.is_empty()
            || assignment.published_context_digest != Some(expected_context_digest)
        {
            return Err("retrieval preparation context binding mismatch".to_string());
        }
        inspect(assignment, record)
    }

    pub(crate) fn append(
        &self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        observation: &RetrievalAssignmentObservationV1,
    ) -> Result<AppendReceipt, String> {
        self.append_with_delivery_policy(
            owner,
            body_generation,
            request_id,
            observation,
            &[],
            false,
            None,
            None,
            ProbabilityQ32::ONE,
        )
    }

    pub(crate) fn append_with_delivery(
        &self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        observation: &RetrievalAssignmentObservationV1,
        delivered_candidates: &[RetrievalCandidateIdentityV1],
        context_exposed: bool,
        published_context_digest: Option<Digest32>,
    ) -> Result<AppendReceipt, String> {
        self.append_with_delivery_policy(
            owner,
            body_generation,
            request_id,
            observation,
            delivered_candidates,
            context_exposed,
            published_context_digest,
            None,
            ProbabilityQ32::ONE,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn append_with_delivery_policy(
        &self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        observation: &RetrievalAssignmentObservationV1,
        delivered_candidates: &[RetrievalCandidateIdentityV1],
        context_exposed: bool,
        published_context_digest: Option<Digest32>,
        downstream_policy_digest: Option<Digest32>,
        delivery_propensity: ProbabilityQ32,
    ) -> Result<AppendReceipt, String> {
        let (record_id, episode_id) = assignment_identity(owner, body_generation, request_id)?;
        let event = retrieval_assignment_event_with_delivery_policy(
            record_id,
            episode_id,
            observation,
            delivered_candidates,
            context_exposed,
            published_context_digest,
            downstream_policy_digest,
            delivery_propensity,
        )
        .map_err(|error| error.to_string())?;
        let mut writer = self
            .writer
            .lock()
            .map_err(|_| "retrieval learning ledger writer lock poisoned".to_string())?;
        let LedgerEvent::RetrievalAssignment(assignment) = event else {
            return Err("retrieval assignment bridge emitted wrong event kind".to_string());
        };
        writer
            .append_retrieval_assignment_current(assignment)
            .map_err(|error| error.to_string())
    }
}

// Keep the historical V1 identities byte-identical. Both append and lookup use
// this function so reads cannot silently correlate by content digest alone.
fn assignment_identity(
    owner: &AgentId,
    body_generation: u64,
    request_id: u64,
) -> Result<(StableId, StableId), String> {
    let episode_id = StableId::new(format!(
        "retrieval-episode:{}:{body_generation}:{request_id}",
        owner.as_str()
    ))
    .map_err(|error| error.to_string())?;
    let mut identity_bytes = b"hepta.agentd.retrieval-assignment.v1".to_vec();
    let owner_bytes = owner.as_str().as_bytes();
    identity_bytes.extend_from_slice(
        &u64::try_from(owner_bytes.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    identity_bytes.extend_from_slice(owner_bytes);
    identity_bytes.extend_from_slice(&body_generation.to_be_bytes());
    identity_bytes.extend_from_slice(&request_id.to_be_bytes());
    let record_id = StableId::new(format!(
        "retrieval-assignment:{}",
        Digest32::of_bytes(&identity_bytes)
    ))
    .map_err(|error| error.to_string())?;
    Ok((record_id, episode_id))
}

#[cfg(test)]
#[path = "cognitive_retrieval_learning_tests.rs"]
mod tests;

