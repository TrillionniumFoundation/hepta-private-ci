//! Commit existing exposure facts after private issuance and currentness checks.
//! A later fence/transport failure can still misrecord publication: retaining
//! durable-before-response ordering requires a future two-phase delivery protocol.

use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore as CognitiveStore;
use codex_hepta_cognitive_store::DurableCognitiveStoreError as CognitiveStoreError;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory_retrieval::RetrievalAssignmentObservationV1;
use codex_hepta_memory_retrieval::RetrievalCandidateIdentityV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;

use crate::CognitiveContextSnapshot;
use crate::CognitiveRetrievalLearningSink;
use crate::cognitive_context::CognitiveContextError;
use crate::cognitive_context_issuer::ContextPlanIssuer;
use crate::cognitive_context_issuer::PlannedContextRead;

pub(crate) struct PendingContextDelivery {
    pub(crate) sink: Arc<CognitiveRetrievalLearningSink>,
    pub(crate) owner: AgentId,
    pub(crate) body_generation: u64,
    pub(crate) request_id: u64,
    pub(crate) assignment: RetrievalAssignmentObservationV1,
    pub(crate) delivered_candidates: Vec<RetrievalCandidateIdentityV1>,
    pub(crate) context_exposed: bool,
    pub(crate) published_context_digest: Option<Digest32>,
    pub(crate) downstream_policy_digest: Option<Digest32>,
    pub(crate) delivery_propensity: ProbabilityQ32,
}

pub(crate) struct CompletedContextRead {
    pub(crate) planned: PlannedContextRead,
    pub(crate) delivery: Option<PendingContextDelivery>,
    pub(crate) observed_at_unix_seconds: i64,
}

impl CompletedContextRead {
    /// Issuance/currentness failures precede the existing exposure fact. Later
    /// failures retract private issuance but cannot retract an appended fact.
    pub(crate) async fn publish(
        self,
        store: &CognitiveStore,
        owner: &AgentId,
        body_generation: u64,
        issuer: &ContextPlanIssuer,
        ranker: Option<&Arc<crate::PinnedCognitiveRanker>>,
        current_retrieval: Option<&Arc<dyn crate::CurrentMemoryRetrievalContext>>,
    ) -> Result<CognitiveContextSnapshot, CognitiveContextError> {
        if crate::cognitive_context::now_seconds()? < self.observed_at_unix_seconds {
            return Err(
                CognitiveStoreError::Invalid("snapshot clock regressed".to_string()).into(),
            );
        }
        let snapshot = issuer
            .issue(self.planned)
            .map_err(CognitiveContextError::ReadUnavailable)?;
        let result = async {
            crate::cognitive_context::revalidate_issued_context(
                store,
                owner,
                body_generation,
                &snapshot,
                ranker,
                current_retrieval,
                issuer,
            )
            .await?;
            if let Some(delivery) = self.delivery {
                tokio::task::spawn_blocking(move || {
                    delivery.sink.append_with_delivery_policy(
                        &delivery.owner,
                        delivery.body_generation,
                        delivery.request_id,
                        &delivery.assignment,
                        &delivery.delivered_candidates,
                        delivery.context_exposed,
                        delivery.published_context_digest,
                        delivery.downstream_policy_digest,
                        delivery.delivery_propensity,
                    )
                })
                .await
                .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?
                .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;
            }
            crate::cognitive_context::revalidate_issued_context(
                store,
                owner,
                body_generation,
                &snapshot,
                ranker,
                current_retrieval,
                issuer,
            )
            .await?;
            if crate::cognitive_context::now_seconds()? < self.observed_at_unix_seconds {
                return Err(
                    CognitiveStoreError::Invalid("snapshot clock regressed".to_string()).into(),
                );
            }
            issuer
                .validate(owner.as_str(), body_generation, &snapshot)
                .map_err(CognitiveContextError::ReadUnavailable)
        }
        .await;
        if let Err(error) = result {
            issuer.retract(&snapshot);
            return Err(error);
        }
        Ok(snapshot)
    }
}
