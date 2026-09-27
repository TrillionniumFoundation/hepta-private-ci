//! Concrete host-owned provider for canonical intelligence invocations.
//!
//! The provider is a bounded registry of one-shot builders installed by the
//! product composition owner. Request bytes can select only a previously
//! registered durable run id; they cannot inject owner profiles, model state,
//! trust material, learning authority or currentness facts.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::AgentdIntelligenceRuntimeMetricsV1;

const MAX_PENDING_CANONICAL_INVOCATIONS: usize = 256;

type InvocationFactory = Box<
    dyn FnOnce(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send,
>;

/// Bounded concrete implementation of the canonical invocation-provider seam.
///
/// A factory is consumed exactly once for the matching durable run. Retries
/// after publication therefore require the composition owner to re-register
/// freshly derived owner inputs; stale in-memory material is never reused.
pub struct AgentdIntelligenceInvocationRegistryV1 {
    profile_digest: Digest32,
    learning_host: Option<Arc<AgentdIntelligenceLearningHostV1>>,
    metrics: Arc<AgentdIntelligenceRuntimeMetricsV1>,
    pending: Mutex<BTreeMap<StableId, InvocationFactory>>,
}

impl AgentdIntelligenceInvocationRegistryV1 {
    /// Compatibility/source-test registry. It cannot advertise the canonical
    /// product capability because no product learning owner is attached.
    pub fn new(profile_digest: Digest32) -> Result<Self, AgentdError> {
        Self::construct(profile_digest, None)
    }

    /// Complete product registry with restart-reconciled Decision/Outcome owner.
    pub fn new_product(
        profile_digest: Digest32,
        learning_host: Arc<AgentdIntelligenceLearningHostV1>,
    ) -> Result<Self, AgentdError> {
        Self::construct(profile_digest, Some(learning_host))
    }

    fn construct(
        profile_digest: Digest32,
        learning_host: Option<Arc<AgentdIntelligenceLearningHostV1>>,
    ) -> Result<Self, AgentdError> {
        if profile_digest.is_zero() {
            return Err(AgentdError::Invalid(
                "canonical intelligence provider profile digest must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            profile_digest,
            learning_host,
            metrics: Arc::new(AgentdIntelligenceRuntimeMetricsV1::new()),
            pending: Mutex::new(BTreeMap::new()),
        })
    }

    pub fn register<F>(&self, run_id: StableId, factory: F) -> Result<(), AgentdError>
    where
        F: FnOnce(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
            + Send
            + 'static,
    {
        let mut pending = self.pending.lock().map_err(|_| {
            AgentdError::Protocol(
                "canonical intelligence invocation registry is poisoned".to_string(),
            )
        })?;
        if pending.contains_key(&run_id) {
            return Err(AgentdError::Invalid(format!(
                "canonical intelligence invocation already registered for {run_id}"
            )));
        }
        if pending.len() >= MAX_PENDING_CANONICAL_INVOCATIONS {
            return Err(AgentdError::Protocol(format!(
                "canonical intelligence invocation registry reached {} entries",
                MAX_PENDING_CANONICAL_INVOCATIONS
            )));
        }
        pending.insert(run_id, Box::new(factory));
        Ok(())
    }

    pub fn remove(&self, run_id: &StableId) -> Result<bool, AgentdError> {
        Ok(self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .remove(run_id)
            .is_some())
    }

    pub fn pending_len(&self) -> Result<usize, AgentdError> {
        Ok(self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .len())
    }

    #[must_use]
    pub fn product_ready(&self) -> bool {
        self.learning_host.is_some() && !self.profile_digest.is_zero()
    }

    #[must_use]
    pub fn metrics(&self) -> Arc<AgentdIntelligenceRuntimeMetricsV1> {
        Arc::clone(&self.metrics)
    }
}

impl AgentdIntelligenceInvocationProviderV1 for AgentdIntelligenceInvocationRegistryV1 {
    fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    fn learning_host(&self) -> Option<Arc<AgentdIntelligenceLearningHostV1>> {
        self.learning_host.clone()
    }

    fn runtime_metrics(&self) -> Option<Arc<AgentdIntelligenceRuntimeMetricsV1>> {
        Some(Arc::clone(&self.metrics))
    }

    fn pending_invocations(&self) -> Result<Option<usize>, AgentdError> {
        self.pending_len().map(Some)
    }

    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let factory = self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .remove(&record.snapshot.run_id)
            .ok_or_else(|| {
                AgentdError::Invalid(format!(
                    "no host-owned canonical invocation is registered for {}",
                    record.snapshot.run_id
                ))
            })?;
        let mut invocation = factory(identity, record)?;
        invocation.attach_runtime_metrics(Arc::clone(&self.metrics));
        invocation.validate(identity, record)?;
        Ok(invocation)
    }
}

/// Install the canonical intelligence product as an all-or-none profile.
///
/// Callers cannot attach only the runner and later advertise a half-composed
/// capability through this API.
pub fn compose_canonical_intelligence_profile_v1(
    config: AgentdConfig,
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    provider: Arc<AgentdIntelligenceInvocationRegistryV1>,
) -> Result<AgentdConfig, AgentdError> {
    if !provider.product_ready() {
        return Err(AgentdError::Invalid(
            "canonical intelligence product profile requires a durable learning owner"
                .to_string(),
        ));
    }
    let config = config.with_intelligence_product_runner(runner)?;
    config.with_intelligence_invocation_provider(provider)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_profile_and_registration_fail_closed() {
        assert!(AgentdIntelligenceInvocationRegistryV1::new(Digest32::ZERO).is_err());
        let registry = AgentdIntelligenceInvocationRegistryV1::new(Digest32::of_bytes(b"profile"))
            .expect("registry");
        assert!(!registry.product_ready());
        assert!(registry.runtime_metrics().is_some());
        assert_eq!(registry.pending_invocations().unwrap(), Some(0));
        let run_id = StableId::new("run.provider").expect("run id");
        registry
            .register(run_id.clone(), |_, _| {
                Err(AgentdError::Invalid("unused fixture".to_string()))
            })
            .expect("register");
        assert_eq!(registry.pending_len().unwrap(), 1);
        assert!(
            registry
                .register(run_id.clone(), |_, _| {
                    Err(AgentdError::Invalid("duplicate fixture".to_string()))
                })
                .is_err()
        );
        assert!(registry.remove(&run_id).unwrap());
        assert_eq!(registry.pending_len().unwrap(), 0);
    }
}
