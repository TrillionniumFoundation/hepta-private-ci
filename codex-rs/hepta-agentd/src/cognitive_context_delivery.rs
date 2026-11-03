//! Prepare a private context publication and bind its durable intent to the
//! exact control frame. Only a completed transport write can confirm delivery.

use std::io;
use std::io::Write;
use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2;
use codex_hepta_learning_ledger::RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2;
use codex_hepta_learning_ledger::retrieval_assignment_intent_v2;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Serialize;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;

use crate::CognitiveContextSnapshot;
use crate::CognitiveRetrievalLearningSink;
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context_issuer::ContextEnvelope;
use crate::cognitive_context_issuer::ContextPlanIssuer;
use crate::cognitive_context_issuer::PlannedContextRead;
use crate::cognitive_retrieval_learning::PendingTransportConfirmation;

pub(crate) struct ContextDeliveryPlan {
    pub(crate) sink: Arc<CognitiveRetrievalLearningSink>,
    pub(crate) owner: AgentId,
    pub(crate) body_generation: u64,
    pub(crate) request_id: u64,
    pub(crate) assignment: RetrievalAssignmentObservationV1,
    pub(crate) planned_candidates: Vec<RetrievalCandidateIdentityV1>,
    pub(crate) downstream_policy_digest: Option<Digest32>,
    pub(crate) delivery_propensity: ProbabilityQ32,
}

pub(crate) struct PendingContextDelivery(ContextDeliveryPlan);

impl PendingContextDelivery {
    pub(crate) fn new(plan: ContextDeliveryPlan) -> Self {
        Self(plan)
    }
}

pub(crate) struct CompletedContextRead {
    pub(crate) planned: PlannedContextRead,
    pub(crate) delivery: Option<PendingContextDelivery>,
    pub(crate) observed_at_unix_seconds: i64,
}

pub(crate) struct PreparedContextRead {
    pub(crate) snapshot: CognitiveContextSnapshot,
    pub(crate) publication: PreparedContextPublication,
}

/// Holds no context text. The private digest prevents a pending assignment from
/// being paired with another snapshot or another request's serialized frame.
pub(crate) struct PreparedContextPublication {
    snapshot_digest: Digest32,
    observed_at_unix_seconds: i64,
    delivery: Option<PendingContextDelivery>,
}

impl CompletedContextRead {
    pub(crate) async fn prepare(
        self,
        store: &CognitiveStore,
        owner: &AgentId,
        body_generation: u64,
        issuer: &ContextPlanIssuer,
        ranker: Option<&Arc<crate::PinnedCognitiveRanker>>,
        current_retrieval: Option<&Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    ) -> Result<PreparedContextRead, CognitiveContextError> {
        check_clock(self.observed_at_unix_seconds)?;
        let snapshot = issuer
            .issue(self.planned)
            .map_err(CognitiveContextError::ReadUnavailable)?;
        let validation = crate::cognitive_context::revalidate_issued_context(
            store,
            owner,
            body_generation,
            &snapshot,
            ranker,
            current_retrieval,
            issuer,
        )
        .await;
        if let Err(error) = validation {
            issuer.retract(&snapshot);
            return Err(error);
        }
        let snapshot_digest = ContextEnvelope::from(&snapshot)
            .digest()
            .map_err(CognitiveContextError::ReadUnavailable)?;
        Ok(PreparedContextRead {
            snapshot,
            publication: PreparedContextPublication {
                snapshot_digest,
                observed_at_unix_seconds: self.observed_at_unix_seconds,
                delivery: self.delivery,
            },
        })
    }

    /// A test read has no transport boundary and therefore writes no intent or
    /// confirmation. Production control exclusively uses `prepare`.
    #[cfg(test)]
    pub(crate) async fn publish(
        self,
        store: &CognitiveStore,
        owner: &AgentId,
        body_generation: u64,
        issuer: &ContextPlanIssuer,
        ranker: Option<&Arc<crate::PinnedCognitiveRanker>>,
        current_retrieval: Option<&Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    ) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
        self.prepare(
            store,
            owner,
            body_generation,
            issuer,
            ranker,
            current_retrieval,
        )
        .await
        .map(|prepared| prepared.snapshot)
    }
}

impl PreparedContextPublication {
    pub(crate) fn validate_snapshot(
        &self,
        snapshot: &CognitiveContextSnapshot,
    ) -> Result<(), CognitiveContextError> {
        check_clock(self.observed_at_unix_seconds)?;
        if ContextEnvelope::from(snapshot)
            .digest()
            .map_err(CognitiveContextError::ReadUnavailable)?
            != self.snapshot_digest
        {
            return Err(CognitiveContextError::ReadUnavailable(
                "prepared context differs from its private publication".to_string(),
            ));
        }
        Ok(())
    }

    /// Durable intent and its independent witness precede the first socket byte.
    /// Cancellation while the worker runs can leave only an unconfirmed intent.
    pub(crate) async fn begin_intent(
        &mut self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        frame: &[u8],
    ) -> Result<Option<PendingTransportConfirmation>, CognitiveContextError> {
        let snapshot = snapshot_from_frame(owner, body_generation, request_id, frame)
            .map_err(CognitiveContextError::ReadUnavailable)?;
        self.validate_snapshot(&snapshot)?;
        let Some(PendingContextDelivery(plan)) = self.delivery.take() else {
            return Ok(None);
        };
        if plan.owner != *owner
            || plan.body_generation != body_generation
            || plan.request_id != request_id
        {
            return Err(CognitiveContextError::ReadUnavailable(
                "pending assignment belongs to another control request".to_string(),
            ));
        }
        let intent = retrieval_assignment_intent_v2(
            StableId::new(owner.as_str())
                .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?,
            body_generation,
            request_id,
            &plan.assignment,
            &plan.planned_candidates,
            self.snapshot_digest,
            RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2,
            Digest32::of_bytes(frame),
            u32::try_from(frame.len())
                .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?,
            plan.downstream_policy_digest,
            plan.delivery_propensity,
        )
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;
        plan.sink
            .append_prepared_intent(intent)
            .await
            .map(Some)
            .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)
    }
}

fn check_clock(observed_at_unix_seconds: i64) -> Result<(), CognitiveContextError> {
    if crate::cognitive_context::now_seconds()? < observed_at_unix_seconds {
        return Err(CognitiveStoreError::Invalid("snapshot clock regressed".to_string()).into());
    }
    Ok(())
}

fn snapshot_from_frame(
    owner: &AgentId,
    body_generation: u64,
    request_id: u64,
    frame: &[u8],
) -> Result<CognitiveContextSnapshot, String> {
    if frame.len() > RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2 as usize || !frame.ends_with(b"\n") {
        return Err("context requires one bounded complete control frame".to_string());
    }
    let value: serde_json::Value =
        serde_json::from_slice(&frame[..frame.len() - 1]).map_err(|error| error.to_string())?;
    if value["schema_version"].as_u64()
        != Some(u64::from(RETRIEVAL_PUBLICATION_CONTROL_SCHEMA_VERSION_V2))
        || value["request_id"].as_u64() != Some(request_id)
        || value["agent_id"].as_str() != Some(owner.as_str())
        || value["spawn_generation"].as_u64() != Some(body_generation)
    {
        return Err("serialized control frame belongs to another request".to_string());
    }
    let mut payload = value["payload"].clone();
    let fields = payload
        .as_object_mut()
        .ok_or_else(|| "invalid cognitive response payload".to_string())?;
    if fields
        .remove("type")
        .and_then(|kind| kind.as_str().map(str::to_owned))
        .as_deref()
        != Some("cognitive_context")
    {
        return Err("pending context requires a cognitive response frame".to_string());
    }
    serde_json::from_value(payload).map_err(|error| error.to_string())
}

/// Serialize the actual wire response while bounding allocation, then append
/// exactly one newline before any ledger or transport operation begins.
pub(crate) fn encode_control_frame<T: Serialize>(response: &T) -> Result<Vec<u8>, String> {
    let mut writer = BoundedFrameWriter(Vec::new());
    serde_json::to_writer(&mut writer, response).map_err(|error| error.to_string())?;
    writer.0.push(b'\n');
    Ok(writer.0)
}

struct BoundedFrameWriter(Vec<u8>);

impl Write for BoundedFrameWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let limit = RETRIEVAL_PUBLICATION_MAX_FRAME_BYTES_V2 as usize - 1;
        if bytes.len() > limit - self.0.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "control frame byte limit",
            ));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// A successful complete write is the host boundary; it does not assert client
/// parsing, model attachment, or exposure. Confirmation precedes shutdown, so a
/// later shutdown failure cannot erase the true completed-write observation.
pub(crate) async fn write_control_frame<W: AsyncWrite + Unpin>(
    writer: &mut W,
    frame: &[u8],
    confirmation: Option<PendingTransportConfirmation>,
) -> Result<(), String> {
    if let Some(confirmation) = &confirmation {
        confirmation.validate_frame(frame)?;
    }
    writer
        .write_all(frame)
        .await
        .map_err(|error| error.to_string())?;
    if let Some(confirmation) = confirmation {
        confirmation.host_write_completed().await?;
    }
    writer.shutdown().await.map_err(|error| error.to_string())
}
