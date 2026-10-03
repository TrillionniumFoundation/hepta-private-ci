//! Concrete durable learning-ledger sink for retrieval assignment evidence.
//!
//! This adapter owns one host-authorized DurableLedger handle. Agentd never
//! invents a parallel file format or treats an in-memory callback as durable
//! causal evidence.

use std::sync::Mutex;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
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

    #[cfg(test)]
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

#[cfg(test)]
#[path = "cognitive_retrieval_learning_tests.rs"]
mod tests;
