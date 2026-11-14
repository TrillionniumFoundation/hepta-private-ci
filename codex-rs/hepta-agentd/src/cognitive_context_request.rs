use std::sync::Arc;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_contracts::AgentId;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveRetrievalLearningSink;
use crate::CurrentMemoryRetrievalContext;
use crate::PinnedCognitiveRanker;

pub(crate) struct CognitiveContextReadRequest<'a> {
    pub(crate) store: &'a DurableCognitiveStore,
    pub(crate) owner: &'a AgentId,
    pub(crate) body_generation: u64,
    pub(crate) query: &'a str,
    pub(crate) limit: u16,
    pub(crate) ranker: Option<&'a Arc<PinnedCognitiveRanker>>,
    pub(crate) current_retrieval: Option<&'a Arc<dyn CurrentMemoryRetrievalContext>>,
    pub(crate) learning_sink: Option<&'a Arc<CognitiveRetrievalLearningSink>>,
    pub(crate) request_id: Option<u64>,
}

pub(crate) struct CognitiveContextRevalidationRequest<'a> {
    pub(crate) store: &'a DurableCognitiveStore,
    pub(crate) owner: &'a AgentId,
    pub(crate) snapshot_digest: &'a str,
    pub(crate) read_digest: &'a str,
    pub(crate) omitted_records: u64,
    pub(crate) items: &'a [CognitiveContextItem],
    pub(crate) plan: Option<&'a CognitiveContextPlan>,
    pub(crate) ranker: Option<&'a Arc<PinnedCognitiveRanker>>,
    pub(crate) body_generation: u64,
    pub(crate) current_retrieval: Option<&'a Arc<dyn CurrentMemoryRetrievalContext>>,
}
