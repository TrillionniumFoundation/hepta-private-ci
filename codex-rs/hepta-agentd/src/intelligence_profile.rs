//! Atomic host composition for canonical intelligence.
//!
//! The standard configuration surface deliberately has no ambient/default
//! provider. A trusted embedding host must construct the bounded runner and the
//! seven-owner invocation provider together, then attach this profile in one
//! consuming operation. Partial configuration never escapes on error and the
//! daemon still performs the independent startup fail-closed check.

use std::sync::Arc;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceProductRunnerV1;

pub struct AgentdCanonicalIntelligenceProfileV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
}

impl AgentdCanonicalIntelligenceProfileV1 {
    #[must_use]
    pub fn new(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    ) -> Self {
        Self { runner, provider }
    }

    fn into_parts(
        self,
    ) -> (
        Arc<AgentdIntelligenceProductRunnerV1>,
        Arc<dyn AgentdIntelligenceInvocationProviderV1>,
    ) {
        (self.runner, self.provider)
    }
}

impl AgentdConfig {
    /// Attach the all-or-none canonical product profile. Objective/AuthBus files
    /// remain independently required by `require_intelligence_composition` so a
    /// caller cannot use this convenience operation to bypass trust/bootstrap
    /// prerequisites.
    pub fn with_canonical_intelligence_profile(
        self,
        profile: AgentdCanonicalIntelligenceProfileV1,
    ) -> Result<Self, AgentdError> {
        let (runner, provider) = profile.into_parts();
        let config = self.with_intelligence_product_runner(runner)?;
        config.with_intelligence_invocation_provider(provider)
    }
}
