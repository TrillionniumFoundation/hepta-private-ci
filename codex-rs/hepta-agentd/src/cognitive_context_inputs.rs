//! Borrowed inputs for the existing cognitive read/revalidation operations.
//! Naming the original parameters does not change their gates or data flow.
use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveRetrievalLearningSink;
use crate::CurrentMemoryRetrievalContext;
use crate::PinnedCognitiveRanker;
use codex_hepta_contracts::AgentId;
use std::sync::Arc;

pub(crate) struct CognitiveReadInput<'a> {
    pub owner: &'a AgentId,
    pub body_generation: u64,
    pub query: &'a str,
    pub limit: u16,
    pub ranker: Option<&'a Arc<PinnedCognitiveRanker>>,
    pub current_retrieval: Option<&'a Arc<dyn CurrentMemoryRetrievalContext>>,
    pub learning_sink: Option<&'a Arc<CognitiveRetrievalLearningSink>>,
    pub request_id: Option<u64>,
}
pub(crate) struct CognitiveRevalidationInput<'a> {
    pub owner: &'a AgentId,
    pub snapshot_digest: &'a str,
    pub read_digest: &'a str,
    pub omitted_records: u64,
    pub items: &'a [CognitiveContextItem],
    pub plan: Option<&'a CognitiveContextPlan>,
    pub ranker: Option<&'a Arc<PinnedCognitiveRanker>>,
    pub body_generation: u64,
    pub current_retrieval: Option<&'a Arc<dyn CurrentMemoryRetrievalContext>>,
}
