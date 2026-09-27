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
use crate::AgentdIntelligenceRuntimeMetricsSnapshotV1;
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
    pub fn is_product_ready(&self) -> bool {
        self.learning_host.is_some()
            && !self.profile_digest.is_zero()
            && self.pending_len().is_ok()
    }

    #[must_use]
    pub fn metrics(&self) -> Arc<AgentdIntelligenceRuntimeMetricsV1> {
        Arc::clone(&self.metrics)
    }
}

impl crate::intelligence_ingress::provider_sealed::Sealed
    for AgentdIntelligenceInvocationRegistryV1
{
}

impl AgentdIntelligenceInvocationProviderV1 for AgentdIntelligenceInvocationRegistryV1 {
    fn profile_digest(&self) -> Digest32 {
        if self.is_product_ready() {
            self.profile_digest
        } else {
            Digest32::ZERO
        }
    }

    fn learning_host(&self) -> Option<Arc<AgentdIntelligenceLearningHostV1>> {
        if self.is_product_ready() {
            self.learning_host.as_ref().map(Arc::clone)
        } else {
            None
        }
    }

    fn runtime_metrics(&self) -> Option<Arc<AgentdIntelligenceRuntimeMetricsV1>> {
        self.is_product_ready()
            .then(|| Arc::clone(&self.metrics))
    }

    fn pending_invocations(&self) -> Result<Option<usize>, AgentdError> {
        self.pending_len().map(Some)
    }

    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        if !self.product_ready()? {
            return Err(AgentdError::Invalid(
                "canonical intelligence provider is not product-ready".to_string(),
            ));
        }
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdCanonicalIntelligenceStatusV1 {
    pub profile_digest: Digest32,
    pub pending_invocations: usize,
    pub learning_backlog: usize,
    pub worker_capacity: usize,
    pub worker_available: usize,
    pub metrics: AgentdIntelligenceRuntimeMetricsSnapshotV1,
}

/// Retainable host handle for one atomically composed canonical product profile.
/// It is the single operational source for profile identity, bounded queue,
/// learning reconciliation backlog, worker saturation and stage metrics.
#[derive(Clone)]
pub struct AgentdCanonicalIntelligenceRuntimeProfileV1 {
    runner: Arc<AgentdIntelligenceProductRunnerV1>,
    provider: Arc<AgentdIntelligenceInvocationRegistryV1>,
}

impl AgentdCanonicalIntelligenceRuntimeProfileV1 {
    pub fn new(
        runner: Arc<AgentdIntelligenceProductRunnerV1>,
        provider: Arc<AgentdIntelligenceInvocationRegistryV1>,
    ) -> Result<Self, AgentdError> {
        if !provider.product_ready()? {
            return Err(AgentdError::Invalid(
                "canonical intelligence product profile requires a durable learning owner, bounded registry and metrics"
                    .to_string(),
            ));
        }
        Ok(Self { runner, provider })
    }

    pub fn compose(&self, config: AgentdConfig) -> Result<AgentdConfig, AgentdError> {
        let config =
            config.with_intelligence_product_runner(Arc::clone(&self.runner))?;
        config.with_intelligence_invocation_provider(Arc::clone(&self.provider))
    }

    pub fn status(&self) -> Result<AgentdCanonicalIntelligenceStatusV1, AgentdError> {
        let learning_host = self.provider.learning_host().ok_or_else(|| {
            AgentdError::Invalid(
                "canonical intelligence product profile lost its learning owner".to_string(),
            )
        })?;
        let learning_backlog = learning_host.backlog().map_err(|error| {
            AgentdError::Protocol(format!(
                "canonical intelligence learning backlog is unavailable: {error}"
            ))
        })?;
        Ok(AgentdCanonicalIntelligenceStatusV1 {
            profile_digest: self.provider.profile_digest(),
            pending_invocations: self.provider.pending_len()?,
            learning_backlog,
            worker_capacity: self.runner.worker_capacity(),
            worker_available: self.runner.worker_available(),
            metrics: self.provider.metrics.snapshot(),
        })
    }

    #[must_use]
    pub fn provider(&self) -> Arc<AgentdIntelligenceInvocationRegistryV1> {
        Arc::clone(&self.provider)
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
    AgentdCanonicalIntelligenceRuntimeProfileV1::new(runner, provider)?.compose(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_profile_and_registration_fail_closed() {
        assert!(AgentdIntelligenceInvocationRegistryV1::new(Digest32::ZERO).is_err());
        let registry = AgentdIntelligenceInvocationRegistryV1::new(Digest32::of_bytes(b"profile"))
            .expect("registry");
        assert!(!registry.is_product_ready());
        assert!(registry.runtime_metrics().is_none());
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
