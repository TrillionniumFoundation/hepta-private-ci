//! Concrete durable learning-ledger sink for unexposed retrieval preparations.
//!
//! This adapter owns one host-authorized DurableLedger handle. Agentd never
//! invents a parallel file format or treats an in-memory callback as durable
//! causal evidence.

use std::sync::Mutex;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::retrieval_preparation_event_v1;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

pub struct CognitiveRetrievalLearningSink {
    writer: Mutex<LedgerWriter>,
    admission: Option<RetrievalLearningAdmission>,
}

pub(crate) struct RetrievalLearningAdmission {
    pub(crate) owner: AgentId,
    pub(crate) body_generation: u64,
    pub(crate) expires_at_unix_s: u64,
    pub(crate) expires_at: std::time::Instant,
}

impl CognitiveRetrievalLearningSink {
    #[must_use]
    pub fn new(writer: LedgerWriter) -> Self {
        Self {
            writer: Mutex::new(writer),
            admission: None,
        }
    }

    pub(crate) fn with_admission(
        writer: LedgerWriter,
        admission: RetrievalLearningAdmission,
    ) -> Self {
        Self {
            writer: Mutex::new(writer),
            admission: Some(admission),
        }
    }

    fn require_current_admission(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(), String> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_secs();
        if self.admission.as_ref().is_some_and(|admission| {
            admission.owner != *owner
                || admission.body_generation != body_generation
                || now > admission.expires_at_unix_s
                || std::time::Instant::now() >= admission.expires_at
        }) {
            return Err(
                "retrieval learning host admission expired or identity changed".to_string(),
            );
        }
        Ok(())
    }

    /// Read-only reconciliation across the two existing durable owners. This
    /// does not create a second delivery journal or upgrade prepared events.
    /// The host must supply its expected native binding, not one copied from an
    /// untrusted receipt. A missing/revoked preparation fails closed.
    pub fn native_delivery_receipt(
        &self,
        preparation_record_id: &StableId,
        binding: &crate::retrieval_delivery::RetrievalNativeBindingV1,
        native_owner: &codex_hepta_infer_core::durable_control::DurableInferenceControl,
    ) -> Result<crate::retrieval_delivery::RetrievalDeliveryReceiptV1, String> {
        let writer = self
            .writer
            .lock()
            .map_err(|_| "retrieval learning ledger writer lock poisoned".to_string())?;
        // This is an offline reconciliation port, not the latency-sensitive
        // append path. Replay reuses the canonical correction/revocation rules.
        let ledger = codex_hepta_learning_ledger::LearningLedger::from_snapshot(
            writer.snapshot().map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        let record = ledger
            .active_records()
            .into_iter()
            .find(|record| record.event.record_id() == preparation_record_id)
            .ok_or_else(|| "retrieval preparation is absent or inactive".to_string())?;
        let LedgerEvent::RetrievalPrepared(preparation) = &record.event else {
            return Err("record is not a tag-10 retrieval preparation".to_string());
        };
        crate::retrieval_delivery::verify_retrieval_delivery_v1(
            preparation,
            binding,
            native_owner.native_record(&binding.request_id),
        )
        .map_err(|error| error.to_string())
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
    #[allow(clippy::too_many_arguments)]
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
        if context_exposed == delivered_candidates.is_empty() {
            return Err("preparation shape mismatch".to_string());
        }
        self.append_preparation(
            owner,
            body_generation,
            request_id,
            observation,
            delivered_candidates,
            published_context_digest,
            downstream_policy_digest,
            delivery_propensity,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn append_preparation(
        &self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        observation: &RetrievalAssignmentObservationV1,
        prepared_candidates: &[RetrievalCandidateIdentityV1],
        prepared_context_digest: Option<Digest32>,
        downstream_policy_digest: Option<Digest32>,
        delivery_propensity: ProbabilityQ32,
    ) -> Result<AppendReceipt, String> {
        self.require_current_admission(owner, body_generation)?;
        let episode_id = StableId::new(format!(
            "retrieval-episode:{}:{body_generation}:{request_id}",
            owner.as_str()
        ))
        .map_err(|error| error.to_string())?;

        let mut identity_bytes = b"hepta.agentd.retrieval-preparation.v1".to_vec();
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
            "retrieval-preparation:{}",
            Digest32::of_bytes(&identity_bytes)
        ))
        .map_err(|error| error.to_string())?;

        let event = retrieval_preparation_event_v1(
            record_id,
            episode_id,
            observation,
            prepared_candidates,
            prepared_context_digest,
            downstream_policy_digest,
            delivery_propensity,
        )
        .map_err(|error| error.to_string())?;
        let mut writer = self.writer.try_lock().map_err(|_| {
            "retrieval learning ledger busy or poisoned; retry only while current".to_string()
        })?;
        self.require_current_admission(owner, body_generation)?;
        let LedgerEvent::RetrievalPrepared(assignment) = event else {
            return Err("retrieval assignment bridge emitted wrong event kind".to_string());
        };
        writer
            .append_retrieval_preparation_current(assignment)
            .map_err(|error| error.to_string())
    }
}

#[cfg(test)]
#[path = "cognitive_retrieval_learning_tests.rs"]
mod tests;
