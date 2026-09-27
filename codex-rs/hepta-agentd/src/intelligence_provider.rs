//! Concrete host-owned provider for canonical intelligence invocations.
//!
//! The provider is a bounded registry of one-shot builders installed by the
//! product composition owner. Request bytes can select only a previously
//! registered durable run id; they cannot inject owner profiles, model state,
//! trust material or currentness facts.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntelligenceOwnerInputsV1;
use crate::AgentdIntelligenceProductRunnerV1;

const MAX_PENDING_CANONICAL_INVOCATIONS: usize = 256;

type InvocationFactory = Box<
    dyn FnOnce(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<
            (
                CanonicalIntelligenceRunRequestV1,
                AgentdIntelligenceOwnerInputsV1,
            ),
            AgentdError,
        > + Send,
>;

/// Bounded concrete implementation of the canonical invocation-provider seam.
///
/// A factory is consumed exactly once for the matching durable run. Retries
/// after publication therefore require the composition owner to re-register
/// freshly derived owner inputs; stale in-memory material is never reused.
pub struct AgentdIntelligenceInvocationRegistryV1 {
    profile_digest: Digest32,
    pending: Mutex<BTreeMap<StableId, InvocationFactory>>,
}

impl AgentdIntelligenceInvocationRegistryV1 {
    pub fn new(profile_digest: Digest32) -> Result<Self, AgentdError> {
        if profile_digest.is_zero() {
            return Err(AgentdError::Invalid(
                "canonical intelligence provider profile digest must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            profile_digest,
            pending: Mutex::new(BTreeMap::new()),
        })
    }

    pub fn register<F>(&self, run_id: StableId, factory: F) -> Result<(), AgentdError>
    where
        F: FnOnce(
                &AgentdIdentity,
                &RunStartRecordV1,
            ) -> Result<
                (
                    CanonicalIntelligenceRunRequestV1,
                    AgentdIntelligenceOwnerInputsV1,
                ),
                AgentdError,
            > + Send
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
}

impl AgentdIntelligenceInvocationProviderV1 for AgentdIntelligenceInvocationRegistryV1 {
    fn profile_digest(&self) -> Digest32 {
        self.profile_digest
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
        let (request, inputs) = factory(identity, record)?;
        AgentdIntelligenceInvocationV1::new(identity, record, request, inputs)
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
