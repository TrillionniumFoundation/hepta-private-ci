//! Optional product completion at the existing authenticated ObjectiveStart.
//! The host must reuse the App Server spine and the sole learning writer. A
//! request cannot install this interface or acquire any authority through it.

use std::future::Future;
use std::pin::Pin;

use crate::AgentdError;
use crate::AgentdIntelligenceAdmittedOutcomeV1;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceExecutionSummaryV1 {
    pub run_id: String,
    pub terminal_observed: bool,
    pub outcome_acknowledged: bool,
    pub observation_digest: Digest32,
}

/// Installed only by an authorized embedding, never by daemon request bytes.
/// Completion must preserve uncertain physical outcomes and use exact recovery;
/// queue acceptance is not terminal success or permission to issue another run.
pub trait AgentdIntelligenceExecutionHostV1: Send + Sync {
    fn owner_generation(&self) -> u64;
    fn execute<'a>(
        &'a self,
        admitted: AgentdIntelligenceAdmittedOutcomeV1,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<AgentdIntelligenceExecutionSummaryV1, AgentdError>>
                + Send
                + 'a,
        >,
    >;
}
