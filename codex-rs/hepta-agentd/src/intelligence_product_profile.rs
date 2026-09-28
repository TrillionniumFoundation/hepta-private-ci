//! Atomic host composition for the complete canonical intelligence product loop.
//!
//! The returned `AgentdConfig` contains the runner, bounded seven-owner input
//! provider and the physical/learning continuation together. Intermediate
//! partial configuration is consumed and dropped on error, so it cannot be
//! advertised by the daemon.

use std::sync::Arc;

use codex_hepta_learning_ledger::RunStartRecordV1;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceProductContinuationV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::HostOwnedAgentdIntelligenceInvocationProviderV1;

pub fn compose_canonical_intelligence_product_profile<F>(
    config: AgentdConfig,
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    factory: F,
    continuation: Arc<dyn AgentdIntelligenceProductContinuationV1>,
) -> Result<AgentdConfig, AgentdError>
where
    F: Fn(&AgentdIdentity, &RunStartRecordV1) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send
        + Sync
        + 'static,
{
    let provider = HostOwnedAgentdIntelligenceInvocationProviderV1::new(factory)
        .with_product_continuation(continuation)?;
    runner.telemetry().set_provider_configured(true);
    config
        .with_intelligence_product_runner(runner)?
        .with_intelligence_invocation_provider(Arc::new(provider))
}
