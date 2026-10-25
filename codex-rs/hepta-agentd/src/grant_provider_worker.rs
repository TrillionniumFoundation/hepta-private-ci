//! One outstanding blocking issuer request per original writer host.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use tokio::sync::Semaphore;

use crate::AgentdError;
use crate::AgentdFinalUseGrantProvider;

pub(crate) struct GrantProviderWorker {
    provider: Arc<dyn AgentdFinalUseGrantProvider>,
    gate: Arc<Semaphore>,
}

impl GrantProviderWorker {
    pub(crate) fn new(provider: Arc<dyn AgentdFinalUseGrantProvider>) -> Self {
        Self {
            provider,
            gate: Arc::new(Semaphore::new(1)),
        }
    }

    pub(crate) async fn signed_grant(
        &self,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, AgentdError> {
        let runtime = tokio::runtime::Handle::try_current().map_err(|_| {
            AgentdError::Protocol("grant provider requires the Agentd runtime".to_string())
        })?;
        let permit = Arc::clone(&self.gate)
            .try_acquire_owned()
            .map_err(|_| AgentdError::Overloaded { retry_after_ms: 25 })?;
        let provider = Arc::clone(&self.provider);
        let binding = binding.clone();
        runtime
            .spawn_blocking(move || {
                // Cancellation of the waiting future cannot release capacity while
                // the provider is still running, or authorize a replacement effect.
                let _permit = permit;
                provider.signed_grant(&binding)
            })
            .await
            .map_err(|_| AgentdError::Protocol("grant provider worker failed".to_string()))?
    }
}

#[cfg(test)]
#[path = "grant_provider_worker_tests.rs"]
mod tests;
