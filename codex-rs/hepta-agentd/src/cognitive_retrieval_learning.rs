//! Concrete durable learning-ledger sink for retrieval assignment evidence.
//!
//! This adapter owns one host-authorized DurableLedger handle. Agentd never
//! invents a parallel file format or treats an in-memory callback as durable
//! causal evidence.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[cfg(test)]
use codex_hepta_contracts::AgentId;
#[cfg(test)]
use codex_hepta_learning_ledger::AppendReceipt;
#[cfg(test)]
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::RetrievalAssignmentIntentV2;
#[cfg(test)]
use codex_hepta_learning_ledger::retrieval_assignment_event_with_delivery_policy;
use codex_hepta_learning_ledger::retrieval_publication_confirmation_v2;
#[cfg(test)]
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
#[cfg(test)]
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
#[cfg(test)]
use codex_hepta_types::ProbabilityQ32;
#[cfg(test)]
use codex_hepta_types::StableId;

pub struct CognitiveRetrievalLearningSink {
    writer: Mutex<LedgerWriter>,
    failed: AtomicBool,
    publications: Arc<tokio::sync::Semaphore>,
}

/// A durable intent bound to one exact control frame. Only the transport path
/// may consume this handle after its complete `write_all` succeeds.
pub(crate) struct PendingTransportConfirmation {
    sink: Arc<CognitiveRetrievalLearningSink>,
    intent: RetrievalAssignmentIntentV2,
    intent_event_digest: Digest32,
    _reservation: tokio::sync::OwnedSemaphorePermit,
}

impl PendingTransportConfirmation {
    pub(crate) fn validate_frame(&self, frame: &[u8]) -> Result<(), String> {
        if u32::try_from(frame.len()).ok() != Some(self.intent.response_frame_bytes)
            || Digest32::of_bytes(frame) != self.intent.response_frame_digest
        {
            return Err("transport frame differs from its durable intent".to_string());
        }
        Ok(())
    }

    pub(crate) async fn host_write_completed(self) -> Result<(), String> {
        let sink = Arc::clone(&self.sink);
        tokio::task::spawn_blocking(move || {
            let _reservation = self._reservation;
            let confirmation =
                retrieval_publication_confirmation_v2(&self.intent, self.intent_event_digest)
                    .map_err(|error| error.to_string())?;
            self.sink.with_writer(|writer| {
                writer.append_retrieval_publication_confirmed_current(confirmation)
            })?;
            Ok(())
        })
        .await
        .map_err(|_| {
            sink.failed.store(true, Ordering::Release);
            "retrieval publication confirmation worker unavailable".to_string()
        })?
        .inspect_err(|_error| {
            sink.failed.store(true, Ordering::Release);
        })
    }
}

impl CognitiveRetrievalLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self {
            writer: Mutex::new(writer),
            failed: AtomicBool::new(false),
            publications: Arc::new(tokio::sync::Semaphore::new(32)),
        }
    }

    pub(crate) fn append_intent(
        self: &Arc<Self>,
        intent: RetrievalAssignmentIntentV2,
        reservation: tokio::sync::OwnedSemaphorePermit,
    ) -> Result<PendingTransportConfirmation, String> {
        let receipt = self.with_writer(|writer| {
            writer.append_retrieval_assignment_intent_current(intent.clone())
        })?;
        Ok(PendingTransportConfirmation {
            sink: Arc::clone(self),
            intent,
            intent_event_digest: receipt.event_digest,
            _reservation: reservation,
        })
    }

    pub(crate) async fn append_prepared_intent(
        self: &Arc<Self>,
        intent: RetrievalAssignmentIntentV2,
    ) -> Result<PendingTransportConfirmation, String> {
        let reservation = self.reserve_publication()?;
        let worker = Arc::clone(self);
        tokio::task::spawn_blocking(move || worker.append_intent(intent, reservation))
            .await
            .map_err(|_| {
                self.failed.store(true, Ordering::Release);
                "retrieval publication intent worker unavailable".to_string()
            })?
    }

    pub(crate) fn reserve_publication(&self) -> Result<tokio::sync::OwnedSemaphorePermit, String> {
        if self.failed.load(Ordering::Acquire) {
            return Err("retrieval learning owner requires explicit recovery".to_string());
        }
        Arc::clone(&self.publications)
            .try_acquire_owned()
            .map_err(|_| "retrieval publication workers are at capacity".to_string())
    }

    fn with_writer<T>(
        &self,
        append: impl FnOnce(
            &mut LedgerWriter,
        ) -> Result<T, codex_hepta_learning_ledger::ProductionLedgerError>,
    ) -> Result<T, String> {
        if self.failed.load(Ordering::Acquire) {
            return Err("retrieval learning owner requires explicit recovery".to_string());
        }
        let mut writer = self.writer.lock().map_err(|_| {
            self.failed.store(true, Ordering::Release);
            "retrieval learning ledger writer lock poisoned".to_string()
        })?;
        if self.failed.load(Ordering::Acquire) {
            return Err("retrieval learning owner requires explicit recovery".to_string());
        }
        append(&mut writer).map_err(|error| {
            self.failed.store(true, Ordering::Release);
            error.to_string()
        })
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

    #[cfg(test)]
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

    #[cfg(test)]
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
