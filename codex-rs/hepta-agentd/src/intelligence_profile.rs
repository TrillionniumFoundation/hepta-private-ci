//! All-or-none canonical intelligence product composition.

use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdIntelligenceObservabilityV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::RegisteredAgentdIntelligenceOutcomeProviderV1;

/// Complete product profile required before Agentd advertises or executes
/// `intelligence.canonical_v1`. A runner or provider on its own is diagnostic
/// source presence only and never enables the capability.
pub struct AgentdCanonicalIntelligenceProfileV1 {
    profile_digest: Digest32,
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    invocation: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    learning: Arc<AgentdIntelligenceLearningHostV1>,
    observability: Arc<AgentdIntelligenceObservabilityV1>,
    outcomes: Arc<RegisteredAgentdIntelligenceOutcomeProviderV1>,
}

impl AgentdCanonicalIntelligenceProfileV1 {
    pub fn new(
        profile_digest: Digest32,
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        invocation: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        learning: Arc<AgentdIntelligenceLearningHostV1>,
        observability: Arc<AgentdIntelligenceObservabilityV1>,
        outcomes: Arc<RegisteredAgentdIntelligenceOutcomeProviderV1>,
    ) -> Result<Self, AgentdError> {
        if profile_digest.is_zero() || observability.capability_profile_digest() != profile_digest {
            return Err(AgentdError::Invalid(
                "canonical intelligence profile identity is invalid".to_string(),
            ));
        }
        Ok(Self {
            profile_digest,
            runner,
            invocation,
            learning,
            observability,
            outcomes,
        })
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        Arc<AgentdIntelligenceProductRunnerV1>,
        Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        Arc<AgentdIntelligenceLearningHostV1>,
        Arc<AgentdIntelligenceObservabilityV1>,
        Arc<RegisteredAgentdIntelligenceOutcomeProviderV1>,
    ) {
        (
            self.runner,
            self.invocation,
            self.learning,
            self.observability,
            self.outcomes,
        )
    }
}
